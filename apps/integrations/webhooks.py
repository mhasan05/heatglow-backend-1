"""
Webhook handlers for incoming ServiceM8 events.

ServiceM8 fires webhooks for:
  - Company.add    — new customer created in SM8
  - Job.update     — job status changed in SM8

These endpoints must be publicly accessible (no auth).
ServiceM8 does not send a signature header, so we rely on
URL obscurity + idempotent upserts for safety.

Webhook format: application/x-www-form-urlencoded
  object        — 'Company' or 'Job'
  entry[0][uuid] — UUID of the changed record
"""
import logging

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from apps.core.models import SyncLog

logger = logging.getLogger(__name__)


class SM8WebhookView(APIView):
    """
    POST /webhooks/sm8/

    Handles incoming ServiceM8 webhook events.
    Always returns 200 — SM8 retries on any other status code.
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        # SM8 sends form-encoded data
        event_object = request.data.get('object', '')
        object_uuid = request.data.get('entry[0][uuid]', '')

        if not object_uuid:
            logger.warning('SM8 webhook: missing entry[0][uuid]')
            return Response({'ok': True})

        logger.info(
            'SM8 webhook received: object=%s uuid=%s',
            event_object, object_uuid,
        )

        try:
            if event_object == 'Company':
                self._handle_company(object_uuid)
            elif event_object == 'Job':
                self._handle_job(object_uuid)
            else:
                logger.warning(
                    'SM8 webhook: unknown object type %s', event_object
                )
        except Exception as exc:
            # Log but always return 200 to stop SM8 retrying
            logger.exception(
                'SM8 webhook handler failed for %s/%s: %s',
                event_object, object_uuid, exc,
            )

        # Always return 200 — SM8 retries on any other status
        return Response({'ok': True})

    def _handle_company(self, company_uuid: str) -> None:
        """Upsert a single company by UUID."""
        from apps.integrations.sm8.client import SM8Client, SM8Error
        from apps.customers.models import Customer

        try:
            with SM8Client() as client:
                company = client.fetch_company(company_uuid)
        except SM8Error as exc:
            logger.warning('SM8 webhook: could not fetch company %s: %s', company_uuid, exc)
            return

        if not company:
            logger.warning('SM8 webhook: company %s not found', company_uuid)
            return

        now = timezone.now()
        customer, created = Customer.objects.update_or_create(
            sm8_company_uuid=company_uuid,
            defaults={
                'name': company.name or 'Unknown',
                'email': (company.email or '').lower() or None,
                'phone': company.phone or company.mobile or '',
                'address_line1': company.address or '',
                'city': company.city or '',
                'postcode': (company.postcode or '').upper(),
                'sm8_synced_at': now,
            },
        )

        action = 'Created' if created else 'Updated'
        logger.info(
            'SM8 webhook: %s customer %s (%s)',
            action, customer.id, customer.name,
        )

        SyncLog.objects.create(
            sync_type=SyncLog.SyncType.WEBHOOK,
            status=SyncLog.Status.SUCCESS,
            records_synced=1,
            finished_at=now,
        )

    def _handle_job(self, job_uuid: str) -> None:
        """Upsert a single job by UUID and recalculate customer metrics."""
        from apps.integrations.sm8.client import SM8Client, SM8Error
        from apps.customers.models import Customer, JobCache
        from apps.customers.utils import recalculate_customer_metrics

        try:
            with SM8Client() as client:
                job = client.fetch_job(job_uuid)
        except SM8Error as exc:
            logger.warning('SM8 webhook: could not fetch job %s: %s', job_uuid, exc)
            return

        if not job:
            logger.warning('SM8 webhook: job %s not found', job_uuid)
            return

        # Find linked customer
        customer = None
        if job.company_uuid:
            customer = Customer.objects.filter(
                sm8_company_uuid=job.company_uuid
            ).first()

        now = timezone.now()
        job_obj, created = JobCache.objects.update_or_create(
            sm8_job_uuid=job_uuid,
            defaults={
                'customer': customer,
                'sm8_company_uuid': job.company_uuid or None,
                'status': job.status,
                'job_description': job.job_description or '',
                'job_type': job.job_type or '',
                'total_invoice_amount': job.total_invoice_amount,
                'created_date': job.created_date or None,
                'completed_date': job.completion_date or None,
                'quote_date': job.quote_date or None,
                'active': job.active == 1,
                'sm8_synced_at': now,
            },
        )

        action = 'Created' if created else 'Updated'
        logger.info('SM8 webhook: %s job %s (status=%s)', action, job_uuid, job.status)

        # Recalculate customer metrics since a job changed
        if customer:
            recalculate_customer_metrics(customer.id)

        SyncLog.objects.create(
            sync_type=SyncLog.SyncType.WEBHOOK,
            status=SyncLog.Status.SUCCESS,
            records_synced=1,
            finished_at=now,
        )