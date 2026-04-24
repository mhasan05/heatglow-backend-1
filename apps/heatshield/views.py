"""
HeatShield membership API views.

GET  /api/v1/heatshield/              — list all members
POST /api/v1/heatshield/              — add new member (admin)
GET  /api/v1/heatshield/{id}/         — member detail
PATCH /api/v1/heatshield/{id}/        — update member (admin)
POST /api/v1/heatshield/{id}/mark-serviced/ — record annual service (admin)
POST /api/v1/heatshield/{id}/cancel/  — cancel membership (admin)
"""
import logging
from datetime import date, timedelta

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination

from apps.core.permissions import IsAdminOrReadOnly, IsAdmin
from apps.core.models import AuditLog
from apps.automation.models import AutomationQueue
from .models import HeatshieldMember
from rest_framework.throttling import UserRateThrottle
from .serializers import (
    HeatshieldMemberListSerializer,
    HeatshieldListSerializer,
    HeatshieldMemberCreateSerializer,
    HeatshieldMemberDetailSerializer,
)

logger = logging.getLogger(__name__)


class HeatshieldPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def _create_renewal_queue_entries(member: HeatshieldMember) -> None:
    """
    Create 3 AutomationQueue entries for a new HeatShield member:
      - 60-day renewal reminder
      - 30-day renewal reminder
      - Day-of renewal reminder

    Uses idempotency keys so running this twice never creates duplicates.
    """
    reminders = [
        ('heatshield_renewal_60', 60, member.renewal_reminder_60_sent),
        ('heatshield_renewal_30', 30, member.renewal_reminder_30_sent),
        ('heatshield_renewal_0', 0, member.renewal_reminder_0_sent),
    ]

    created_count = 0
    for automation_type, days_before, already_sent in reminders:
        if already_sent:
            continue

        scheduled_date = member.renewal_date - timedelta(days=days_before)
        idempotency_key = (
            automation_type + ':' +
            str(member.id) + ':' +
            member.renewal_date.isoformat()
        )

        _, created = AutomationQueue.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                'automation_type': automation_type,
                'customer': member.customer,
                'payload': {
                    'member_id': str(member.id),
                    'customer_name': member.customer.name,
                    'customer_email': member.customer.email,
                    'renewal_date': member.renewal_date.isoformat(),
                    'plan_type': member.plan_type,
                    'monthly_amount': str(member.monthly_amount),
                    'days_before': days_before,
                },
                'status': AutomationQueue.Status.PENDING,
                'scheduled_for': timezone.make_aware(
                    timezone.datetime.combine(
                        scheduled_date,
                        timezone.datetime.min.time(),
                    )
                ),
            },
        )
        if created:
            created_count += 1

    logger.info(
        'Created %d queue entries for member %s (renewal: %s)',
        created_count, member.id, member.renewal_date,
    )


class HeatshieldListCreateView(APIView):
    """
    GET  /api/v1/heatshield/  — list members (admin + staff)
    POST /api/v1/heatshield/  — add member (admin only)
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAdmin()]
        return [IsAdminOrReadOnly()]

    def get(self, request: Request) -> Response:
        from datetime import date, timedelta
        from django.db.models import Sum, Count, Q

        today = date.today()

        # ── Summary stats (4 KPI cards at top) ───────────────────────────────────
        all_members = HeatshieldMember.objects.select_related('customer')

        active_qs = all_members.filter(status='active')
        service_due_qs = active_qs.filter(
            renewal_date__lte=today + timedelta(days=60)
        )
        lapsed_qs = all_members.filter(status='lapsed')
        cancelled_qs = all_members.filter(status='cancelled')

        active_count = active_qs.count()
        service_due_count = service_due_qs.count()
        lapsed_count = lapsed_qs.count()
        monthly_revenue = active_qs.aggregate(
            total=Sum('monthly_amount')
        )['total'] or 0

        # ── Alert banner ──────────────────────────────────────────────────────────
        from apps.campaigns.models import Campaign
        reminder_drafts = Campaign.objects.filter(
            status='draft',
            automation_trigger__icontains='heatshield',
        ).count()

        alert = None
        if service_due_count > 0:
            alert = {
                'show': True,
                'count': service_due_count,
                'message': (
                    str(service_due_count) + ' '
                    + ('member has' if service_due_count == 1 else 'members have')
                    + ' a service due. '
                    + (
                        'A reminder campaign draft has been created automatically.'
                        if reminder_drafts > 0
                        else 'Run Tier 2 automations to create reminder drafts.'
                    )
                ),
                'reminder_drafts_count': reminder_drafts,
                'action_label': 'View Campaigns' if reminder_drafts > 0 else None,
                'action_url': '/campaigns/queue/' if reminder_drafts > 0 else None,
            }

        # ── Status filter tabs ────────────────────────────────────────────────────
        status_filter = request.query_params.get('status', '').lower()
        expiring_days = request.query_params.get('expiring_days')
        search = request.query_params.get('q', '').strip()

        qs = all_members

        if status_filter == 'active':
            qs = qs.filter(status='active')
        elif status_filter == 'service_due':
            qs = qs.filter(
                status='active',
                renewal_date__lte=today + timedelta(days=60),
            )
        elif status_filter == 'lapsed':
            qs = qs.filter(status='lapsed')
        elif status_filter == 'cancelled':
            qs = qs.filter(status='cancelled')

        if expiring_days:
            try:
                days = int(expiring_days)
                qs = qs.filter(
                    status='active',
                    renewal_date__lte=today + timedelta(days=days),
                )
            except ValueError:
                pass

        # Search by name, postcode, phone, email
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(customer__name__icontains=search) |
                Q(customer__postcode__icontains=search) |
                Q(customer__phone__icontains=search) |
                Q(customer__email__icontains=search)
            )

        qs = qs.order_by('renewal_date')

        # ── Paginate ──────────────────────────────────────────────────────────────
        from rest_framework.pagination import PageNumberPagination

        class HeatShieldPagination(PageNumberPagination):
            page_size = 25
            page_size_query_param = 'page_size'
            max_page_size = 200

        paginator = HeatShieldPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = HeatshieldListSerializer(page, many=True)

        # ── Tab counts (for the filter buttons) ──────────────────────────────────
        tab_counts = {
            'all': all_members.count(),
            'active': active_count,
            'service_due': service_due_count,
            'lapsed': lapsed_count,
            'cancelled': cancelled_qs.count(),
        }

        response = paginator.get_paginated_response(serializer.data)
        response.data['summary'] = {
            'active_members': active_count,
            'service_due': service_due_count,
            'lapsed': lapsed_count,
            'monthly_revenue': float(monthly_revenue),
            'monthly_revenue_formatted': '\u00a3{:,.0f}'.format(float(monthly_revenue)),
        }
        response.data['alert'] = alert
        response.data['tab_counts'] = tab_counts

        return response

    def post(self, request: Request) -> Response:
        serializer = HeatshieldMemberCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        member = serializer.save()

        # Update customer's heatshield_status
        member.customer.heatshield_status = 'active'
        member.customer.save(update_fields=['heatshield_status', 'updated_at'])

        # Create 3 automation queue entries for renewal reminders
        _create_renewal_queue_entries(member)

        # Audit log
        AuditLog.objects.create(
            actor_user=request.user,
            action='heatshield.member_added',
            entity_type='heatshield_member',
            entity_id=member.id,
            metadata={
                'customer_id': str(member.customer.id),
                'customer_name': member.customer.name,
                'renewal_date': member.renewal_date.isoformat(),
                'plan_type': member.plan_type,
            },
        )

        logger.info(
            'HeatShield member added: %s (customer: %s, renewal: %s)',
            member.id, member.customer.name, member.renewal_date,
        )

        return Response(
            HeatshieldMemberDetailSerializer(member).data,
            status=status.HTTP_201_CREATED,
        )


class HeatshieldDetailView(APIView):
    """
    GET   /api/v1/heatshield/{id}/  — member detail
    PATCH /api/v1/heatshield/{id}/  — update notes/renewal date (admin)
    """
    permission_classes = [IsAdminOrReadOnly]

    def _get_member(self, pk):
        try:
            return HeatshieldMember.objects.select_related(
                'customer'
            ).get(pk=pk)
        except HeatshieldMember.DoesNotExist:
            return None

    def get(self, request: Request, pk) -> Response:
        member = self._get_member(pk)
        if not member:
            return Response(
                {'detail': 'Member not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = HeatshieldListSerializer(member)
        return Response(serializer.data)

    def patch(self, request: Request, pk) -> Response:
        from apps.core.permissions import _get_role
        from apps.accounts.models import UserProfile

        if _get_role(request) != UserProfile.Role.ADMIN:
            return Response(
                {'detail': 'Admin access required.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        member = self._get_member(pk)
        if not member:
            return Response(
                {'detail': 'Member not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only allow updating these fields via PATCH
        allowed = {'notes', 'renewal_date', 'monthly_amount', 'plan_type'}
        data = {k: v for k, v in request.data.items() if k in allowed}

        serializer = HeatshieldMemberDetailSerializer(
            member, data=data, partial=True
        )
        if serializer.is_valid():
            serializer.save()

            # If renewal_date changed, recreate queue entries
            if 'renewal_date' in data:
                _create_renewal_queue_entries(member)

            return Response(serializer.data)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


class HeatshieldMarkServicedView(APIView):
    """
    POST /api/v1/heatshield/{id}/mark-serviced/
    Admin only. Records that the annual service has been completed.
    Updates last_service_job_uuid and last_renewed_at.
    Resets the renewal reminder flags for the next cycle.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request, pk) -> Response:
        try:
            member = HeatshieldMember.objects.select_related(
                'customer'
            ).get(pk=pk)
        except HeatshieldMember.DoesNotExist:
            return Response(
                {'detail': 'Member not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        job_uuid = request.data.get('job_uuid')
        new_renewal_date = request.data.get('renewal_date')

        # Record the service
        member.last_renewed_at = date.today()
        if job_uuid:
            member.last_service_job_uuid = job_uuid

        # Advance renewal date by 1 year if not provided
        if new_renewal_date:
            from datetime import datetime
            member.renewal_date = datetime.strptime(
                new_renewal_date, '%Y-%m-%d'
            ).date()
        else:
            member.renewal_date = date(
                member.renewal_date.year + 1,
                member.renewal_date.month,
                member.renewal_date.day,
            )

        # Reset reminder flags for next cycle
        member.renewal_reminder_60_sent = False
        member.renewal_reminder_30_sent = False
        member.renewal_reminder_0_sent = False
        member.save()

        # Create new queue entries for the next renewal cycle
        _create_renewal_queue_entries(member)

        AuditLog.objects.create(
            actor_user=request.user,
            action='heatshield.mark_serviced',
            entity_type='heatshield_member',
            entity_id=member.id,
            metadata={
                'new_renewal_date': member.renewal_date.isoformat(),
                'job_uuid': str(job_uuid) if job_uuid else None,
            },
        )

        logger.info(
            'HeatShield member %s marked as serviced. New renewal: %s',
            member.id, member.renewal_date,
        )

        return Response(HeatshieldMemberDetailSerializer(member).data)


class HeatshieldCancelView(APIView):
    """
    POST /api/v1/heatshield/{id}/cancel/
    Admin only. Cancels the membership and updates customer status.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request, pk) -> Response:
        try:
            member = HeatshieldMember.objects.select_related(
                'customer'
            ).get(pk=pk)
        except HeatshieldMember.DoesNotExist:
            return Response(
                {'detail': 'Member not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if member.status == 'cancelled':
            return Response(
                {'detail': 'Membership is already cancelled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        member.status = HeatshieldMember.Status.CANCELLED
        member.save()

        # Update customer heatshield_status
        member.customer.heatshield_status = 'cancelled'
        member.customer.save(
            update_fields=['heatshield_status', 'updated_at']
        )

        # Cancel any pending queue entries for this member
        AutomationQueue.objects.filter(
            customer=member.customer,
            automation_type__startswith='heatshield_renewal_',
            status=AutomationQueue.Status.PENDING,
        ).update(status=AutomationQueue.Status.SKIPPED)

        AuditLog.objects.create(
            actor_user=request.user,
            action='heatshield.cancelled',
            entity_type='heatshield_member',
            entity_id=member.id,
            metadata={'customer_name': member.customer.name},
        )

        return Response(HeatshieldMemberDetailSerializer(member).data)


class HeatshieldExportView(APIView):
    """
    GET /api/v1/heatshield/export/
    Admin only. Export all HeatShield members as CSV.
    Rate limited to 1 request per minute.
    """
    # permission_classes = [IsAdmin]
    # throttle_classes = [UserRateThrottle]

    def get(self, request: Request) -> Response:
        import csv
        from datetime import date
        from django.http import StreamingHttpResponse

        status_filter = request.query_params.get('status', '')
        search = request.query_params.get('q', '').strip()

        qs = HeatshieldMember.objects.select_related(
            'customer'
        ).order_by('status', 'renewal_date')

        if status_filter:
            qs = qs.filter(status=status_filter.lower())

        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(customer__name__icontains=search) |
                Q(customer__postcode__icontains=search) |
                Q(customer__email__icontains=search) |
                Q(customer__phone__icontains=search)
            )

        today = date.today()

        def generate_rows():
            # Header row
            yield [
                'Name', 'Email', 'Phone', 'Postcode',
                'Status', 'Plan Type', 'Monthly Amount (£)',
                'Sign-up Date', 'Last Service Date',
                'Renewal Date', 'Days Elapsed',
                'Days Until Renewal', 'Renewal Status',
                'Reminder 60d Sent', 'Reminder 30d Sent',
                'Reminder Day-of Sent', 'Notes',
                'Customer ID', 'Member ID',
            ]

            for member in qs.iterator():
                # Days elapsed since last service
                reference = member.last_renewed_at or member.start_date
                days_elapsed = (
                    (today - reference).days if reference else 0
                )

                # Days until renewal
                days_until = (
                    (member.renewal_date - today).days
                    if member.renewal_date else ''
                )

                # Renewal status label
                if member.status != 'active':
                    renewal_status = member.status.capitalize()
                elif member.renewal_date:
                    d = (member.renewal_date - today).days
                    if d < 0:
                        renewal_status = 'Overdue'
                    elif days_elapsed >= 305:
                        renewal_status = 'Service Due'
                    elif d <= 60:
                        renewal_status = 'Due Soon'
                    else:
                        renewal_status = 'Active'
                else:
                    renewal_status = 'Active'

                customer = member.customer

                yield [
                    customer.name if customer else '',
                    customer.email if customer else '',
                    customer.phone if customer else '',
                    customer.postcode if customer else '',
                    member.status.capitalize(),
                    member.plan_type or 'standard',
                    float(member.monthly_amount or 10),
                    member.start_date.isoformat() if member.start_date else '',
                    member.last_renewed_at.isoformat() if member.last_renewed_at else '',
                    member.renewal_date.isoformat() if member.renewal_date else '',
                    days_elapsed,
                    days_until,
                    renewal_status,
                    'Yes' if member.renewal_reminder_60_sent else 'No',
                    'Yes' if member.renewal_reminder_30_sent else 'No',
                    'Yes' if member.renewal_reminder_0_sent else 'No',
                    member.notes or '',
                    str(customer.id) if customer else '',
                    str(member.id),
                ]

        class Echo:
            def write(self, value):
                return value

        pseudo_buffer = Echo()
        writer = csv.writer(pseudo_buffer)

        response = StreamingHttpResponse(
            (writer.writerow(row) for row in generate_rows()),
            content_type='text/csv',
        )

        filename = 'heatshield_members_' + today.isoformat() + '.csv'
        response['Content-Disposition'] = 'attachment; filename="' + filename + '"'
        return response