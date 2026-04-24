"""
Django-filter filter classes for the customers endpoints.
"""
import django_filters
from .models import Customer


class CustomerFilter(django_filters.FilterSet):
    # Segment filter: ?segment=high_value
    segment = django_filters.CharFilter(method='filter_segment')

    # Spend range: ?min_spend=1000&max_spend=5000
    min_spend = django_filters.NumberFilter(
        field_name='total_spend', lookup_expr='gte'
    )
    max_spend = django_filters.NumberFilter(
        field_name='total_spend', lookup_expr='lte'
    )

    # Last job date range
    last_job_after = django_filters.DateFilter(
        field_name='last_job_date', lookup_expr='gte'
    )
    last_job_before = django_filters.DateFilter(
        field_name='last_job_date', lookup_expr='lte'
    )

    class Meta:
        model = Customer
        fields = [
            'heatshield_status',
            'email_opt_out',
            'postcode',
        ]

    def filter_segment(self, queryset, name, value):
        """Filter customers whose segments array contains the given value."""
        return queryset.filter(segments__contains=[value])