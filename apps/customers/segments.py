"""
Customer segment calculation engine.

Segments are stored as a PostgreSQL TEXT[] array on the Customer model.
This module calculates which segments each customer belongs to and
bulk-updates the database efficiently.

Segments:
    vip              — total_spend > £2,000
    lapsed           — no completed job in last 12 months
    heatshield_active — has an active HeatShield membership
    one_time         — exactly 1 completed job, no return visits
    active           — completed job in last 6 months

A customer can belong to multiple segments simultaneously.
Segments array is recalculated nightly and after every sync.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.db.models import Q

logger = logging.getLogger(__name__)

# ── Segment thresholds ────────────────────────────────────────────────────────

VIP_SPEND_THRESHOLD = Decimal('2000.00')
LAPSED_MONTHS = 12
ACTIVE_MONTHS = 6
ONE_TIME_JOB_COUNT = 1

COMPLETED_STATUSES = ['Completed', 'Invoice Sent', 'Paid', 'Work Order']


# ── Segment definitions ───────────────────────────────────────────────────────

def get_segment_rules() -> dict:
    """
    Returns a dict mapping segment name to a Q() filter that
    selects customers belonging to that segment.

    Used by both the bulk recalculation and the segment preview endpoint.
    """
    today = date.today()
    lapsed_cutoff = today - timedelta(days=LAPSED_MONTHS * 30)
    active_cutoff = today - timedelta(days=ACTIVE_MONTHS * 30)

    return {
        'vip': Q(total_spend__gte=VIP_SPEND_THRESHOLD),

        'lapsed': Q(
            job_count__gte=1,
        ) & (
            Q(last_job_date__lt=lapsed_cutoff) |
            Q(last_job_date__isnull=True)
        ),

        'heatshield_active': Q(heatshield_status='active'),

        'one_time': Q(job_count=ONE_TIME_JOB_COUNT),

        'active': Q(
            last_job_date__gte=active_cutoff,
        ),
    }


def calculate_segments_for_customer(customer) -> list[str]:
    """
    Calculate which segments a single customer belongs to.
    Returns a list of segment name strings.

    Used when a single customer's data changes (webhook, approval).
    """
    from apps.customers.models import Customer

    rules = get_segment_rules()
    customer_segments = []

    for segment_name, q_filter in rules.items():
        if Customer.objects.filter(
            pk=customer.pk
        ).filter(q_filter).exists():
            customer_segments.append(segment_name)

    return sorted(customer_segments)


def recalculate_all_segments() -> dict:
    """
    Recalculate segment membership for ALL customers in a single
    efficient database operation using raw SQL.

    Returns a summary dict with counts per segment.

    This is called by the nightly Celery task and can also be
    triggered manually from the Django admin or Settings screen.
    """
    from apps.customers.models import Customer

    today = date.today()
    lapsed_cutoff = today - timedelta(days=LAPSED_MONTHS * 30)
    active_cutoff = today - timedelta(days=ACTIVE_MONTHS * 30)

    logger.info('Starting segment recalculation for all customers')

    # ── Build segment arrays using Django ORM ─────────────────────────────────
    # Process each customer and build their segment list
    # We use bulk_update for efficiency — one DB round-trip per batch

    all_customers = list(Customer.objects.only(
        'id', 'total_spend', 'job_count',
        'last_job_date', 'heatshield_status',
    ))

    updates = []
    segment_counts = {
        'vip': 0,
        'lapsed': 0,
        'heatshield_active': 0,
        'one_time': 0,
        'active': 0,
    }

    for customer in all_customers:
        segments = []

        # VIP: lifetime spend over threshold
        if customer.total_spend >= VIP_SPEND_THRESHOLD:
            segments.append('vip')
            segment_counts['vip'] += 1

        # Lapsed: has had jobs but none in last 12 months
        if customer.job_count >= 1 and (
            customer.last_job_date is None or
            customer.last_job_date < lapsed_cutoff
        ):
            segments.append('lapsed')
            segment_counts['lapsed'] += 1

        # HeatShield active: has active membership
        if customer.heatshield_status == 'active':
            segments.append('heatshield_active')
            segment_counts['heatshield_active'] += 1

        # One-time: exactly one completed job, never returned
        if customer.job_count == ONE_TIME_JOB_COUNT:
            segments.append('one_time')
            segment_counts['one_time'] += 1

        # Active: completed job in last 6 months
        if (
            customer.last_job_date is not None and
            customer.last_job_date >= active_cutoff
        ):
            segments.append('active')
            segment_counts['active'] += 1

        # Only update if segments changed
        if sorted(segments) != sorted(customer.segments or []):
            customer.segments = sorted(segments)
            updates.append(customer)

    # Bulk update in batches of 500
    if updates:
        Customer.objects.bulk_update(updates, ['segments'], batch_size=500)
        logger.info(
            'Segment recalculation complete: %d customers updated',
            len(updates),
        )
    else:
        logger.info('Segment recalculation complete: no changes needed')

    total = len(all_customers)
    summary = {
        'total_customers': total,
        'updated': len(updates),
        'segments': segment_counts,
    }

    logger.info('Segment summary: %s', summary)
    return summary