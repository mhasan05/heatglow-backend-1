"""
Segment query builder for the campaign manager.

Converts a JSONB segment_filters array into a Django Q() queryset.

Filter format:
    [
        {"field": "segment", "value": "lapsed"},
        {"field": "min_spend", "value": 500},
        {"field": "heatshield_status", "value": "none"},
        {"field": "postcode_prefix", "value": "CF14"},
        {"field": "last_job_after", "value": "2024-01-01"},
        {"field": "last_job_before", "value": "2025-01-01"},
        {"field": "has_email", "value": true},
    ]

Multiple filters are ANDed together.
"""
import logging
from django.db.models import Q, QuerySet

logger = logging.getLogger(__name__)


def build_segment_queryset(filters: list[dict]) -> QuerySet:
    """
    Apply a list of segment filter dicts to the Customer queryset.
    Returns a filtered QuerySet.
    """
    from apps.customers.models import Customer

    qs = Customer.objects.filter(
        email_opt_out=False,
    ).exclude(
        email__isnull=True,
    ).exclude(
        email='',
    )

    for f in filters:
        field = f.get('field', '')
        value = f.get('value')

        if not field or value is None or value == '':
            continue

        try:
            qs = _apply_filter(qs, field, value)
        except (ValueError, TypeError) as exc:
            logger.warning(
                'Invalid segment filter field=%s value=%s: %s',
                field, value, exc,
            )
            continue

    return qs


def _apply_filter(qs: QuerySet, field: str, value) -> QuerySet:
    """Apply a single filter to the queryset."""
    if field == 'segment':
        return qs.filter(segments__contains=[value])

    elif field == 'heatshield_status':
        return qs.filter(heatshield_status=value)

    elif field == 'min_spend':
        return qs.filter(total_spend__gte=float(value))

    elif field == 'max_spend':
        return qs.filter(total_spend__lte=float(value))

    elif field == 'last_job_after':
        return qs.filter(last_job_date__gte=value)

    elif field == 'last_job_before':
        return qs.filter(last_job_date__lte=value)

    elif field == 'postcode_prefix':
        return qs.filter(postcode__istartswith=str(value).upper())

    elif field == 'has_email':
        if value is True or value == 'true':
            return qs.exclude(
                email__isnull=True
            ).exclude(email='')
        else:
            return qs.filter(
                Q(email__isnull=True) | Q(email='')
            )

    elif field == 'job_count_min':
        return qs.filter(job_count__gte=int(value))

    elif field == 'job_count_max':
        return qs.filter(job_count__lte=int(value))

    elif field == 'city':
        return qs.filter(city__iexact=str(value))

    else:
        logger.warning('Unknown segment filter field: %s', field)
        return qs


def apply_personalisation_tokens(text: str, customer) -> str:
    """
    Replace personalisation tokens in email subject/body with
    real customer values.

    Supported tokens:
        {{first_name}}    — first word of customer.name
        {{full_name}}     — customer.name
        {{last_job_type}} — customer.last_job_type
        {{total_spend}}   — customer.total_spend formatted as £X,XXX
        {{postcode}}      — customer.postcode
    """
    first_name = customer.name.split()[0] if customer.name else 'there'
    total_spend = '£{:,.0f}'.format(float(customer.total_spend or 0))

    replacements = {
        '{{first_name}}': first_name,
        '{{full_name}}': customer.name or '',
        '{{last_job_type}}': customer.last_job_type or 'your last service',
        '{{total_spend}}': total_spend,
        '{{postcode}}': customer.postcode or '',
    }

    for token, replacement in replacements.items():
        text = text.replace(token, replacement)

    return text