"""
Enquiry API views.

POST   /api/v1/enquiries/            — public intake (no auth required)
GET    /api/v1/enquiries/            — list (admin + staff)
GET    /api/v1/enquiries/{id}/       — detail (admin + staff)
POST   /api/v1/enquiries/{id}/approve/ — approve + push to SM8 (admin)
POST   /api/v1/enquiries/{id}/reject/  — reject with reason (admin)
"""
import logging

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.pagination import PageNumberPagination

from apps.core.permissions import IsAdmin
from apps.core.models import AuditLog
from .models import Enquiry
from .serializers import (
    EnquiryCreateSerializer,
    EnquiryListSerializer,
    EnquiryDetailSerializer,
)

logger = logging.getLogger(__name__)


class EnquiryPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 50


class EnquiryListCreateView(APIView):
    """
    GET  /api/v1/enquiries/  — list all enquiries (authenticated)
    POST /api/v1/enquiries/  — submit new enquiry (public, no auth)
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request: Request) -> Response:
        qs = Enquiry.objects.select_related(
            'customer', 'reviewed_by'
        ).order_by('-created_at')

        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter.upper())

        # Filter by urgency
        urgency = request.query_params.get('urgency')
        if urgency:
            qs = qs.filter(urgency=urgency.lower())

        # Filter by source
        source = request.query_params.get('source')
        if source:
            qs = qs.filter(source=source.lower())

        # Search — name, postcode, job type, email, phone
        q = request.query_params.get('q', '').strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(customer_name__icontains=q) |
                Q(customer_postcode__icontains=q) |
                Q(job_type__icontains=q) |
                Q(customer_email__icontains=q) |
                Q(customer_phone__icontains=q)
            )

        # Quotes gone cold filter
        # Approved enquiries whose SM8 job is still in Quote status after 30+ days
        lapsed = request.query_params.get('filter')
        if lapsed == 'lapsed_quotes':
            from datetime import date, timedelta
            from apps.customers.models import JobCache
            cutoff = date.today() - timedelta(days=30)

            # Get SM8 job UUIDs that are still in Quote status and old
            lapsed_job_uuids = JobCache.objects.filter(
                status='Quote',
                quote_date__lte=cutoff,
            ).values_list('sm8_job_uuid', flat=True)

            qs = qs.filter(
                status='APPROVED',
                sm8_job_uuid__in=lapsed_job_uuids,
            )

        paginator = EnquiryPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = EnquiryListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request: Request) -> Response:
        """
        Accept a new enquiry from the public form.
        No authentication required.
        Triggers AI qualification as a background task.
        """
        serializer = EnquiryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Try to link to existing customer by email
        customer = None
        email = serializer.validated_data.get('customer_email')
        if email:
            from apps.customers.models import Customer
            customer = Customer.objects.filter(email=email).first()

        enquiry = serializer.save(
            customer=customer,
            status=Enquiry.Status.PENDING,
        )

        logger.info(
            'New enquiry received: %s from %s (%s)',
            enquiry.id,
            enquiry.customer_name,
            enquiry.customer_postcode,
        )

        # Trigger AI qualification as a background task
        try:
            from apps.enquiries.tasks import qualify_enquiry_async
            qualify_enquiry_async.delay(str(enquiry.id))
        except Exception as exc:
            # Don't fail the request if Celery is unavailable
            logger.warning('Could not queue qualification task: %s', exc)

        return Response(
            EnquiryDetailSerializer(enquiry).data,
            status=status.HTTP_201_CREATED,
        )


class EnquiryDetailView(APIView):
    """GET /api/v1/enquiries/{id}/ — enquiry detail (admin + staff)"""
    permission_classes = [IsAuthenticated]

    def _get_enquiry(self, pk):
        try:
            return Enquiry.objects.select_related(
                'customer', 'reviewed_by'
            ).get(pk=pk)
        except Enquiry.DoesNotExist:
            return None

    def get(self, request: Request, pk) -> Response:
        enquiry = self._get_enquiry(pk)
        if not enquiry:
            return Response(
                {'detail': 'Enquiry not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = EnquiryDetailSerializer(enquiry)
        return Response(serializer.data)


class EnquiryApproveView(APIView):
    """
    POST /api/v1/enquiries/{id}/approve/
    Admin only. Approves the enquiry and creates a job in ServiceM8.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request, pk) -> Response:
        try:
            enquiry = Enquiry.objects.select_related('customer').get(pk=pk)
        except Enquiry.DoesNotExist:
            return Response(
                {'detail': 'Enquiry not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if enquiry.status == Enquiry.Status.APPROVED:
            return Response(
                {'detail': 'Enquiry is already approved.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if enquiry.status == Enquiry.Status.REJECTED:
            return Response(
                {'detail': 'Cannot approve a rejected enquiry.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Attempt to create a job in ServiceM8
        sm8_job_uuid = None
        sm8_error = None

        try:
            from apps.integrations.sm8.writeback import create_sm8_job
            sm8_job_uuid = create_sm8_job(enquiry)
            logger.info(
                'SM8 job created for enquiry %s: %s',
                enquiry.id, sm8_job_uuid,
            )
        except Exception as exc:
            # Log but don't block approval if SM8 is unavailable
            sm8_error = str(exc)
            logger.warning(
                'SM8 write-back failed for enquiry %s: %s',
                enquiry.id, exc,
            )

        # Update enquiry status
        enquiry.status = Enquiry.Status.APPROVED
        enquiry.reviewed_by = request.user
        enquiry.reviewed_at = timezone.now()
        if sm8_job_uuid:
            enquiry.sm8_job_uuid = sm8_job_uuid
            enquiry.sm8_created_at = timezone.now()
        enquiry.save()

        # Write audit log
        AuditLog.objects.create(
            actor_user=request.user,
            action='enquiry.approve',
            entity_type='enquiry',
            entity_id=enquiry.id,
            metadata={
                'sm8_job_uuid': str(sm8_job_uuid) if sm8_job_uuid else None,
                'sm8_error': sm8_error,
            },
            ip_address=self._get_client_ip(request),
        )

        response_data = EnquiryDetailSerializer(enquiry).data
        if sm8_error:
            response_data['warning'] = (
                f'Approved but SM8 write-back failed: {sm8_error}'
            )

        return Response(response_data)

    def _get_client_ip(self, request) -> str | None:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


class EnquiryRejectView(APIView):
    """
    POST /api/v1/enquiries/{id}/reject/
    Admin only. Rejects the enquiry with an optional reason.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request, pk) -> Response:
        try:
            enquiry = Enquiry.objects.get(pk=pk)
        except Enquiry.DoesNotExist:
            return Response(
                {'detail': 'Enquiry not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if enquiry.status == Enquiry.Status.APPROVED:
            return Response(
                {'detail': 'Cannot reject an already approved enquiry.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rejection_reason = request.data.get('rejection_reason', '')

        enquiry.status = Enquiry.Status.REJECTED
        enquiry.reviewed_by = request.user
        enquiry.reviewed_at = timezone.now()
        enquiry.rejection_reason = rejection_reason
        enquiry.save()

        # Write audit log
        AuditLog.objects.create(
            actor_user=request.user,
            action='enquiry.reject',
            entity_type='enquiry',
            entity_id=enquiry.id,
            metadata={'rejection_reason': rejection_reason},
        )

        return Response(EnquiryDetailSerializer(enquiry).data)
    

class EnquiryNoteView(APIView):
    """
    POST /api/v1/enquiries/{id}/notes/
    Admin only. Add an internal note to an enquiry.
    Logged to AuditLog so it appears in the activity feed.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request, pk) -> Response:
        from apps.core.models import AuditLog

        try:
            enquiry = Enquiry.objects.get(pk=pk)
        except Enquiry.DoesNotExist:
            return Response(
                {'detail': 'Enquiry not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = request.data.get('body', '').strip()
        if not body:
            return Response(
                {'detail': 'Note body is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Log to audit log — this is how notes are stored
        log = AuditLog.objects.create(
            actor_user=request.user,
            action='enquiry.note_added',
            entity_type='enquiry',
            entity_id=enquiry.id,
            metadata={
                'note': body,
                'author': (
                    request.user.get_full_name()
                    or request.user.username
                ),
            },
        )

        return Response(
            {
                'id': str(log.id),
                'body': body,
                'author': (
                    request.user.get_full_name()
                    or request.user.username
                ),
                'created_at': log.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )
    

class EnquiryQualifyView(APIView):
    """
    GET  /api/v1/enquiries/{id}/qualify/
    Returns full vetting checklist data for the Qualify screen.
    Both admin and staff can view. Only admin can submit the decision.

    POST /api/v1/enquiries/{id}/qualify/
    Body: {
        "action": "approve" | "approve_no_sm8" | "reject" | "reject_silent",
        "rejection_reason": "Outside service area"  (required if action is reject*)
    }
    """
    permission_classes = [IsAuthenticated]

    SERVICE_AREA_PREFIXES = [
        'CF3', 'CF5', 'CF10', 'CF11', 'CF14', 'CF15', 'CF23', 'CF24',
        'CF38', 'CF62', 'CF63', 'CF64', 'CF83',
        'NP10', 'NP18', 'NP19', 'NP20', 'NP44',
        'SA1', 'SA2', 'SA3', 'SA4',
        'HR1', 'HR2', 'HR3', 'HR4',
        'LD1', 'LD2', 'LD3',
        'SY15', 'SY16', 'SY17',
        'CH1', 'CH2', 'CH3', 'CH4',
    ]

    ACCEPTED_JOB_TYPES = [
        'boiler service', 'boiler repair', 'boiler installation',
        'boiler replacement', 'central heating', 'power flush',
        'gas safety', 'gas safety certificate', 'emergency plumbing',
        'emergency callout', 'bathroom', 'radiator', 'heatshield',
        'boiler install', 'heating', 'plumbing',
    ]

    PRICE_SHOPPING_KEYWORDS = [
        'cheapest', 'cheap', 'ballpark', 'few quotes',
        'getting quotes', 'compare', 'best price',
        'how much', 'rough idea', 'estimate only',
    ]

    def get(self, request: Request, pk) -> Response:
        try:
            enquiry = Enquiry.objects.select_related(
                'customer', 'reviewed_by'
            ).get(pk=pk)
        except Enquiry.DoesNotExist:
            return Response(
                {'detail': 'Enquiry not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        vetting = self._build_vetting_checklist(enquiry)

        return Response({
            # Customer summary banner
            'enquiry': {
                'id': str(enquiry.id),
                'customer_name': enquiry.customer_name,
                'customer_phone': enquiry.customer_phone,
                'customer_email': enquiry.customer_email,
                'customer_postcode': enquiry.customer_postcode,
                'job_type': enquiry.job_type,
                'urgency': enquiry.urgency,
                'description': enquiry.description,
                'source': enquiry.source,
                'status': enquiry.status,
                'created_at': enquiry.created_at.isoformat(),
            },

            # Gemini AI assessment panel
            'ai_assessment': {
                'score': enquiry.ai_score,
                'recommendation': enquiry.ai_recommendation,
                'confidence': enquiry.ai_confidence,
                'explanation': enquiry.ai_explanation,
                'flags': enquiry.ai_flags or [],
                'qualified_at': (
                    enquiry.ai_qualified_at.isoformat()
                    if enquiry.ai_qualified_at else None
                ),
                'score_colour': self._score_colour(enquiry.ai_score),
            },

            # Vetting checklist panel (right side)
            'vetting': vetting,

            # Rejection reason options for dropdown
            'rejection_reasons': [
                'Outside service area',
                'Wrong trade — not our service',
                'Spam or suspicious enquiry',
                'Customer uncontactable',
                'Job too small',
                'Job too large / commercial',
                'Customer found another provider',
                'Duplicate enquiry',
                'Other',
            ],
        })

    def post(self, request: Request, pk) -> Response:
        """Submit the qualify or reject decision."""
        from apps.core.permissions import _get_role
        from apps.accounts.models import UserProfile

        # Only admins can submit decisions
        if _get_role(request) != UserProfile.Role.ADMIN:
            return Response(
                {'detail': 'Admin access required to qualify or reject.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            enquiry = Enquiry.objects.get(pk=pk)
        except Enquiry.DoesNotExist:
            return Response(
                {'detail': 'Enquiry not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if enquiry.status in ('APPROVED', 'REJECTED'):
            return Response(
                {'detail': 'This enquiry has already been decided.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = request.data.get('action', '').strip()
        if action not in (
            'approve', 'approve_no_sm8', 'reject', 'reject_silent'
        ):
            return Response(
                {
                    'detail': (
                        'action must be one of: approve, '
                        'approve_no_sm8, reject, reject_silent'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone
        from apps.core.models import AuditLog

        # ── Approve ───────────────────────────────────────────────────────────
        if action in ('approve', 'approve_no_sm8'):
            enquiry.status = Enquiry.Status.APPROVED
            enquiry.reviewed_by = request.user
            enquiry.reviewed_at = timezone.now()

            push_to_sm8 = (action == 'approve')
            sm8_result = None

            if push_to_sm8:
                try:
                    from apps.integrations.sm8.writeback import create_sm8_job
                    sm8_uuid = create_sm8_job(enquiry)
                    enquiry.sm8_job_uuid = sm8_uuid
                    enquiry.sm8_push_status = 'success'
                    enquiry.sm8_created_at = timezone.now()
                    sm8_result = str(sm8_uuid)
                except Exception as exc:
                    enquiry.sm8_push_status = 'failed'
                    enquiry.sm8_push_attempts += 1
                    enquiry.sm8_push_error = str(exc)
                    sm8_result = None

            enquiry.save()

            AuditLog.objects.create(
                actor_user=request.user,
                action='enquiry.approved',
                entity_type='enquiry',
                entity_id=enquiry.id,
                metadata={
                    'pushed_to_sm8': push_to_sm8,
                    'sm8_job_uuid': sm8_result,
                    'score': enquiry.ai_score,
                },
            )

            return Response({
                'status': 'APPROVED',
                'sm8_job_uuid': sm8_result,
                'pushed_to_sm8': push_to_sm8,
                'warning': (
                    'SM8 push failed — job not created in ServiceM8. '
                    'Please add manually.'
                    if push_to_sm8 and not sm8_result else None
                ),
            })

        # ── Reject ────────────────────────────────────────────────────────────
        if action in ('reject', 'reject_silent'):
            rejection_reason = request.data.get('rejection_reason', '').strip()
            if not rejection_reason:
                return Response(
                    {'detail': 'rejection_reason is required.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            enquiry.status = Enquiry.Status.REJECTED
            enquiry.reviewed_by = request.user
            enquiry.reviewed_at = timezone.now()
            enquiry.rejection_reason = rejection_reason
            enquiry.save()

            # Send decline email unless silent
            if action == 'reject':
                try:
                    from apps.enquiries.emails import (
                        build_customer_acknowledgement_html
                    )
                    from apps.integrations.resend_client import send_email
                    send_email(
                        to=enquiry.customer_email,
                        subject='Your HeatGlow enquiry',
                        html=build_customer_acknowledgement_html(enquiry),
                    )
                except Exception as exc:
                    pass  # Don't fail the rejection if email fails

            AuditLog.objects.create(
                actor_user=request.user,
                action='enquiry.rejected',
                entity_type='enquiry',
                entity_id=enquiry.id,
                metadata={
                    'rejection_reason': rejection_reason,
                    'silent': action == 'reject_silent',
                    'score': enquiry.ai_score,
                },
            )

            return Response({
                'status': 'REJECTED',
                'rejection_reason': rejection_reason,
                'email_sent': action == 'reject',
            })

    def _build_vetting_checklist(self, enquiry) -> dict:
        """
        Build the 5-point vetting checklist shown on the right panel.
        Each check has: passed, title, detail.
        """
        postcode = (enquiry.customer_postcode or '').upper().replace(' ', '')
        description = enquiry.description or ''
        job_type = (enquiry.job_type or '').lower()
        flags = enquiry.ai_flags or []

        # ── Check 1: In service area ──────────────────────────────────────────
        in_service_area = any(
            postcode.startswith(p.replace(' ', ''))
            for p in self.SERVICE_AREA_PREFIXES
        )
        check1 = {
            'key': 'service_area',
            'title': 'In service area',
            'passed': in_service_area,
            'detail': (
                enquiry.customer_postcode + ' — confirmed in coverage zone'
                if in_service_area
                else enquiry.customer_postcode + ' — outside service area'
            ),
            'critical': True,  # Failing this is a hard reject signal
        }

        # ── Check 2: Acceptable job type ──────────────────────────────────────
        accepted_job = any(
            t in job_type for t in self.ACCEPTED_JOB_TYPES
        ) or 'out_of_service_area' not in flags
        # Also check AI flags for wrong trade
        if 'wrong_trade' in flags or 'commercial' in flags:
            accepted_job = False
        check2 = {
            'key': 'job_type',
            'title': 'Acceptable job type',
            'passed': accepted_job,
            'detail': (
                enquiry.job_type + ' — within offered services'
                if accepted_job
                else enquiry.job_type + ' — not within offered services'
            ),
            'critical': True,
        }

        # ── Check 3: Customer appears committed ───────────────────────────────
        price_shopping = any(
            kw in description.lower()
            for kw in self.PRICE_SHOPPING_KEYWORDS
        )
        committed = not price_shopping and (enquiry.ai_score or 0) >= 40
        check3 = {
            'key': 'committed',
            'title': 'Customer appears committed',
            'passed': committed,
            'detail': (
                'Customer provided specific details and a genuine need'
                if committed
                else 'Language suggests price shopping or low commitment'
            ),
            'critical': False,
        }

        # ── Check 4: Job well described ───────────────────────────────────────
        desc_length = len(description.strip())
        well_described = desc_length >= 50
        check4 = {
            'key': 'description',
            'title': 'Job well described',
            'passed': well_described,
            'detail': (
                str(desc_length) + ' characters — good level of detail'
                if well_described
                else str(desc_length) + ' characters — more detail would help'
            ),
            'critical': False,
        }

        # ── Check 5: Budget expectations realistic ────────────────────────────
        unrealistic = any(
            kw in description.lower()
            for kw in ['free', 'very cheap', 'as cheap', 'no money', 'broke']
        )
        realistic_budget = not unrealistic
        check5 = {
            'key': 'budget',
            'title': 'Budget expectations realistic',
            'passed': realistic_budget,
            'detail': (
                'No indication of unrealistic budget expectations'
                if realistic_budget
                else 'Description suggests unrealistic budget expectations'
            ),
            'critical': False,
        }

        checks = [check1, check2, check3, check4, check5]
        passed_count = sum(1 for c in checks if c['passed'])
        critical_failed = [c for c in checks if c['critical'] and not c['passed']]

        return {
            'checks': checks,
            'passed_count': passed_count,
            'total_count': len(checks),
            'all_passed': passed_count == len(checks),
            'critical_failed': len(critical_failed) > 0,
            'critical_failed_labels': [c['title'] for c in critical_failed],
            'recommendation': (
                'REJECT' if critical_failed
                else 'APPROVE' if passed_count >= 4
                else 'REVIEW'
            ),
        }

    def _score_colour(self, score) -> str:
        if score is None:
            return 'gray'
        if score >= 70:
            return 'green'
        if score >= 40:
            return 'amber'
        return 'red'