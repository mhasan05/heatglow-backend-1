"""
Customer utility functions — metric calculation, segment assignment.
"""
import logging
from uuid import UUID

from django.db.models import Max, Sum, Count

logger = logging.getLogger(__name__)

COMPLETED_STATUSES = ['Completed', 'Invoice Sent', 'Paid', 'Work Order']


def recalculate_customer_metrics(customer_id: UUID) -> None:
    """
    Recompute total_spend, job_count, last_job_date, last_job_type
    for a single customer from their jobs_cache rows.

    Called after every sync write and every webhook update.
    Mirrors the calculate_customer_metrics() Postgres function
    described in the original blueprint.
    """
    from apps.customers.models import Customer, JobCache

    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        logger.warning('recalculate_customer_metrics: customer %s not found', customer_id)
        return

    completed_jobs = JobCache.objects.filter(
        customer=customer,
        status__in=COMPLETED_STATUSES,
    )

    agg = completed_jobs.aggregate(
        total=Sum('total_invoice_amount'),
        count=Count('id'),
        last_date=Max('completed_date'),
    )

    # Get the most recent job type separately (aggregate can't do this)
    last_job = completed_jobs.order_by('-completed_date').first()

    customer.total_spend = agg['total'] or 0
    customer.job_count = agg['count'] or 0
    customer.last_job_date = agg['last_date']
    customer.last_job_type = last_job.job_type if last_job else ''
    customer.save(update_fields=[
        'total_spend', 'job_count', 'last_job_date',
        'last_job_type', 'updated_at',
    ])