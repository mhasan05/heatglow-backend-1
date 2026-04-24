"""
Customer background tasks.
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    name='customers.recalculate_segments',
)
def recalculate_segments(self):
    """
    Nightly task: recalculate segment membership for all customers.
    Scheduled at 02:00 UTC by Celery Beat.
    Also triggered manually from the Settings screen.
    """
    from apps.customers.segments import recalculate_all_segments

    try:
        summary = recalculate_all_segments()
        logger.info('Segment recalculation task complete: %s', summary)
        return summary
    except Exception as exc:
        logger.exception('Segment recalculation failed: %s', exc)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name='customers.enrich_single_customer',
)
def enrich_single_customer(self, customer_id: str):
    """
    Triggered task: recalculate metrics + segments for one customer.
    Called after a webhook updates their job data.
    """
    from apps.customers.utils import recalculate_customer_metrics
    from apps.customers.segments import calculate_segments_for_customer
    from apps.customers.models import Customer

    try:
        customer = Customer.objects.get(id=customer_id)
        recalculate_customer_metrics(customer.id)

        # Reload after metrics update
        customer.refresh_from_db()
        new_segments = calculate_segments_for_customer(customer)

        if sorted(new_segments) != sorted(customer.segments or []):
            customer.segments = new_segments
            customer.save(update_fields=['segments', 'updated_at'])
            logger.info(
                'Customer %s segments updated: %s',
                customer_id, new_segments,
            )

        return {'customer_id': customer_id, 'segments': new_segments}

    except Customer.DoesNotExist:
        logger.warning('enrich_single_customer: customer %s not found', customer_id)
    except Exception as exc:
        logger.exception('enrich_single_customer failed: %s', exc)
        raise self.retry(exc=exc)