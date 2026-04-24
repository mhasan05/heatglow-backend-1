"""
Core sync logic — called by Celery tasks and management commands.
Handles the actual database upsert operations.
"""
import logging
from datetime import datetime
from typing import Optional

from django.utils import timezone

from apps.customers.models import Customer, JobCache

logger = logging.getLogger(__name__)


def sync_companies(client, since: Optional[datetime] = None) -> int:
    """
    Fetch companies from SM8 and upsert into customers table.
    Returns number of records synced.
    """
    synced = 0
    now = timezone.now()

    for company in client.iter_companies():
        # Skip inactive/archived companies
        if company.active != 1:
            continue

        # If incremental sync, skip records not changed since last sync
        if since and company.edit_date:
            try:
                from django.utils.dateparse import parse_datetime
                edit_dt = parse_datetime(company.edit_date)
                if edit_dt and edit_dt < since:
                    continue
            except (ValueError, TypeError):
                pass

        Customer.objects.update_or_create(
            sm8_company_uuid=company.uuid,
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
        synced += 1

    logger.info('sync_companies: upserted %d records', synced)
    return synced


def sync_jobs(client, since: Optional[datetime] = None) -> int:
    """
    Fetch jobs from SM8 and upsert into jobs_cache table.
    Also recalculates customer metrics for affected customers.
    """
    from apps.customers.utils import recalculate_customer_metrics

    synced = 0
    affected_customer_ids = set()
    now = timezone.now()

    for job in client.iter_jobs():
        # Skip incremental if not changed
        if since and job.edit_date:
            try:
                from django.utils.dateparse import parse_datetime
                edit_dt = parse_datetime(job.edit_date)
                if edit_dt and edit_dt < since:
                    continue
            except (ValueError, TypeError):
                pass

        # Find the linked customer
        customer = None
        if job.company_uuid:
            customer = Customer.objects.filter(
                sm8_company_uuid=job.company_uuid
            ).first()

        job_obj, _ = JobCache.objects.update_or_create(
            sm8_job_uuid=job.uuid,
            defaults={
                'customer': customer,
                'sm8_company_uuid': job.company_uuid or None,
                'status': job.status,
                'job_description': job.job_description or '',
                'job_type': job.job_type or '',
                'total_invoice_amount': job.total_invoice_amount,
                'materials_cost': 0,
                'created_date': job.created_date or None,
                'completed_date': job.completion_date or None,
                'quote_date': job.quote_date or None,
                'active': job.active == 1,
                'sm8_synced_at': now,
            },
        )

        if customer:
            affected_customer_ids.add(customer.id)
        synced += 1

    # Recalculate metrics for all customers whose jobs changed
    for customer_id in affected_customer_ids:
        recalculate_customer_metrics(customer_id)

    logger.info('sync_jobs: upserted %d records', synced)
    return synced