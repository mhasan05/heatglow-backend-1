"""
Customers API views.

GET  /api/v1/customers/                    — paginated list
GET  /api/v1/customers/{id}/               — full profile
PATCH /api/v1/customers/{id}/              — update opt-out (admin)
POST /api/v1/customers/{id}/notes/         — add note (admin)
DELETE /api/v1/customers/{id}/notes/{nid}/ — delete note (admin)
POST /api/v1/customers/segment-preview/    — live segment count
GET  /api/v1/customers/export/             — CSV download (admin)
"""
import csv
import logging
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.throttling import UserRateThrottle

from apps.core.permissions import IsAdminOrReadOnly, IsAdmin
from apps.core.models import AuditLog
from .models import Customer, CustomerNote
from .serializers import (
    CustomerListSerializer,
    CustomerDetailSerializer,
    CustomerNoteSerializer,
)

logger = logging.getLogger(__name__)


class CustomerPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class CustomerListView(APIView):
    """
    GET /api/v1/customers/

    Query params:
        q                 — search name, email, phone, postcode
        segment           — vip | lapsed | heatshield_active | one_time | active
        heatshield_status — active | lapsed | cancelled | none
        min_spend         — minimum total spend
        max_spend         — maximum total spend
        has_email         — true | false
        ordering          — name | -name | total_spend | -total_spend |
                            job_count | -job_count | last_job_date | -last_job_date
    """
    permission_classes = [IsAdminOrReadOnly]

    def get(self, request: Request) -> Response:
        qs = Customer.objects.all()

        # ── free-text search ──────────────────────────────────────────────────
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(email__icontains=q) |
                Q(phone__icontains=q) |
                Q(postcode__icontains=q)
            )

        # ── segment filter ────────────────────────────────────────────────────
        segment = request.query_params.get('segment', '').strip()
        if segment:
            qs = qs.filter(segments__contains=[segment])

        # ── heatshield status ─────────────────────────────────────────────────
        hs = request.query_params.get('heatshield_status', '').strip()
        if hs:
            qs = qs.filter(heatshield_status=hs)

        # ── spend range ───────────────────────────────────────────────────────
        min_spend = request.query_params.get('min_spend')
        if min_spend:
            try:
                qs = qs.filter(total_spend__gte=float(min_spend))
            except ValueError:
                pass

        max_spend = request.query_params.get('max_spend')
        if max_spend:
            try:
                qs = qs.filter(total_spend__lte=float(max_spend))
            except ValueError:
                pass

        # ── email filter ──────────────────────────────────────────────────────
        has_email = request.query_params.get('has_email')
        if has_email == 'true':
            qs = qs.exclude(email__isnull=True).exclude(email='')
        elif has_email == 'false':
            qs = qs.filter(Q(email__isnull=True) | Q(email=''))

        # ── ordering ──────────────────────────────────────────────────────────
        allowed = {
            'name', '-name',
            'total_spend', '-total_spend',
            'job_count', '-job_count',
            'last_job_date', '-last_job_date',
            'created_at', '-created_at',
        }
        ordering = request.query_params.get('ordering', '-total_spend')
        if ordering not in allowed:
            ordering = '-total_spend'
        qs = qs.order_by(ordering)

        # ── paginate ──────────────────────────────────────────────────────────
        paginator = CustomerPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = CustomerListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class CustomerDetailView(APIView):
    """
    GET   /api/v1/customers/{id}/  — full profile with jobs + notes
    PATCH /api/v1/customers/{id}/  — update email_opt_out (admin only)
    """
    permission_classes = [IsAdminOrReadOnly]

    def _get_customer(self, pk):
        try:
            return Customer.objects.prefetch_related(
                'jobs', 'notes__author'
            ).get(pk=pk)
        except Customer.DoesNotExist:
            return None

    def get(self, request: Request, pk) -> Response:
        customer = self._get_customer(pk)
        if not customer:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = CustomerDetailSerializer(customer)
        return Response(serializer.data)

    def patch(self, request: Request, pk) -> Response:
        from apps.core.permissions import _get_role
        from apps.accounts.models import UserProfile

        if _get_role(request) != UserProfile.Role.ADMIN:
            return Response(
                {'detail': 'Admin access required.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        customer = self._get_customer(pk)
        if not customer:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        allowed_fields = {'email_opt_out'}
        data = {k: v for k, v in request.data.items() if k in allowed_fields}

        serializer = CustomerDetailSerializer(
            customer, data=data, partial=True
        )
        if serializer.is_valid():
            serializer.save()

            AuditLog.objects.create(
                actor_user=request.user,
                action='customer.update',
                entity_type='customer',
                entity_id=customer.id,
                metadata={'fields': list(data.keys()), 'values': data},
            )
            return Response(serializer.data)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


class CustomerNotesView(APIView):
    """
    POST   /api/v1/customers/{id}/notes/      — add note (admin)
    DELETE /api/v1/customers/{id}/notes/{nid}/ — delete note (admin)
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request, pk) -> Response:
        try:
            customer = Customer.objects.get(pk=pk)
        except Customer.DoesNotExist:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = request.data.get('body', '').strip()
        if not body:
            return Response(
                {'detail': 'Note body is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        note = CustomerNote.objects.create(
            customer=customer,
            author=request.user,
            body=body,
        )

        AuditLog.objects.create(
            actor_user=request.user,
            action='customer.note_added',
            entity_type='customer',
            entity_id=customer.id,
            metadata={'note_id': str(note.id)},
        )

        serializer = CustomerNoteSerializer(note)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def delete(self, request: Request, pk, note_id) -> Response:
        try:
            note = CustomerNote.objects.get(pk=note_id, customer_id=pk)
        except CustomerNote.DoesNotExist:
            return Response(
                {'detail': 'Note not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        note.delete()

        AuditLog.objects.create(
            actor_user=request.user,
            action='customer.note_deleted',
            entity_type='customer',
            entity_id=pk,
            metadata={'note_id': str(note_id)},
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class SegmentPreviewView(APIView):
    """
    POST /api/v1/customers/segment-preview/
    Body: { "filters": [{"field": "segment", "value": "vip"}] }
    Returns: { "count": 412 }
    Admin only.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request) -> Response:
        filters = request.data.get('filters', [])
        qs = Customer.objects.all()

        for f in filters:
            field = f.get('field', '')
            value = f.get('value', '')
            if not field or value == '':
                continue

            try:
                if field == 'segment':
                    qs = qs.filter(segments__contains=[value])
                elif field == 'heatshield_status':
                    qs = qs.filter(heatshield_status=value)
                elif field == 'min_spend':
                    qs = qs.filter(total_spend__gte=float(value))
                elif field == 'max_spend':
                    qs = qs.filter(total_spend__lte=float(value))
                elif field == 'last_job_after':
                    qs = qs.filter(last_job_date__gte=value)
                elif field == 'last_job_before':
                    qs = qs.filter(last_job_date__lte=value)
                elif field == 'postcode_prefix':
                    qs = qs.filter(postcode__istartswith=value)
                elif field == 'has_email':
                    if value is True or value == 'true':
                        qs = qs.exclude(
                            email__isnull=True
                        ).exclude(email='')
                elif field == 'email_opt_out':
                    qs = qs.filter(email_opt_out=bool(value))
            except (ValueError, TypeError):
                continue

        return Response({'count': qs.count()})


class CustomerExportThrottle(UserRateThrottle):
    """Rate-limit CSV exports to 1 per minute per user."""
    rate = '1/min'


class CustomerExportView(APIView):
    """
    GET /api/v1/customers/export/
    Streams a CSV of all matching customers.
    Same filters as the list endpoint.
    Admin only. Rate limited to 1 per minute.
    """
    permission_classes = [IsAdmin]
    throttle_classes = [CustomerExportThrottle]

    def get(self, request: Request) -> Response:
        qs = Customer.objects.all().order_by('-total_spend')

        # Apply same filters as list view
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(email__icontains=q) |
                Q(phone__icontains=q) |
                Q(postcode__icontains=q)
            )

        segment = request.query_params.get('segment', '').strip()
        if segment:
            qs = qs.filter(segments__contains=[segment])

        hs = request.query_params.get('heatshield_status', '').strip()
        if hs:
            qs = qs.filter(heatshield_status=hs)

        def generate_csv(queryset):
            """Stream CSV rows one at a time."""
            yield ','.join([
                'Name', 'Email', 'Phone', 'Postcode', 'City',
                'Total Spend', 'Job Count', 'Last Job Date',
                'Last Job Type', 'Segments', 'HeatShield Status',
                'Email Opt Out',
            ]) + '\r\n'

            for customer in queryset.iterator(chunk_size=500):
                row = [
                    customer.name or '',
                    customer.email or '',
                    customer.phone or '',
                    customer.postcode or '',
                    customer.city or '',
                    str(customer.total_spend),
                    str(customer.job_count),
                    str(customer.last_job_date or ''),
                    customer.last_job_type or '',
                    '|'.join(customer.segments or []),
                    customer.heatshield_status,
                    str(customer.email_opt_out),
                ]
                # Escape any commas in fields
                row = [
                    '"' + field.replace('"', '""') + '"'
                    for field in row
                ]
                yield ','.join(row) + '\r\n'

        response = StreamingHttpResponse(
            generate_csv(qs),
            content_type='text/csv',
        )
        response['Content-Disposition'] = (
            'attachment; filename="heatglow_customers.csv"'
        )

        AuditLog.objects.create(
            actor_user=request.user,
            action='customers.export',
            entity_type='customer',
            metadata={
                'filters': dict(request.query_params),
                'count': qs.count(),
            },
        )

        return response