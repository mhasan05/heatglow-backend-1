"""
Customer intelligence layer — mirror of ServiceM8 with enrichment.
"""
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.core.models import TimestampedModel


class Customer(TimestampedModel):
    class HeatshieldStatus(models.TextChoices):
        ACTIVE = 'active', 'Active'
        LAPSED = 'lapsed', 'Lapsed'
        CANCELLED = 'cancelled', 'Cancelled'
        NONE = 'none', 'None'

    # ServiceM8 linkage
    sm8_company_uuid = models.UUIDField(unique=True, null=True, blank=True)

    # Contact
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True, default='')

    # Address
    address_line1 = models.CharField(max_length=255, blank=True, default='')
    address_line2 = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    postcode = models.CharField(max_length=20, blank=True, default='', db_index=True)

    # Computed enrichment (recalculated after every job change)
    total_spend = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    job_count = models.IntegerField(default=0)
    last_job_date = models.DateField(null=True, blank=True)
    last_job_type = models.CharField(max_length=100, blank=True, default='')

    # Segments (array of strings like ['high_value', 'heatshield_active'])
    segments = ArrayField(
        base_field=models.CharField(max_length=50),
        default=list,
        blank=True,
    )

    # Email hygiene
    email_opt_out = models.BooleanField(default=False)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    # HeatShield denormalised status (mirrors active HeatshieldMember row)
    heatshield_status = models.CharField(
        max_length=15,
        choices=HeatshieldStatus.choices,
        default=HeatshieldStatus.NONE,
    )

    # Sync tracking
    sm8_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'customers'
        indexes = [
            GinIndex(fields=['segments'], name='customers_segments_gin'),
            models.Index(fields=['-last_job_date'], name='customers_last_job_idx'),
            models.Index(fields=['heatshield_status'], name='customers_hs_status_idx'),
        ]

    def __str__(self):
        return f'{self.name} ({self.email or "no-email"})'


class JobCache(TimestampedModel):
    """Read-only mirror of ServiceM8 jobs. Powers the dashboard KPIs."""

    sm8_job_uuid = models.UUIDField(unique=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jobs',
    )
    sm8_company_uuid = models.UUIDField(null=True, blank=True)
    engineer_name = models.CharField(max_length=255, blank=True, default='')

    status = models.CharField(max_length=50)
    job_address = models.TextField(blank=True, default='')
    job_description = models.TextField(blank=True, default='')
    job_type = models.CharField(max_length=100, blank=True, default='')

    total_invoice_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    materials_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_date = models.DateField(null=True, blank=True)
    completed_date = models.DateField(null=True, blank=True)
    quote_date = models.DateField(null=True, blank=True)

    active = models.BooleanField(default=True)

    # Filled when attribution assigns a completed job to a campaign
    # (ForeignKey defined with string to avoid circular import)
    attributed_campaign = models.ForeignKey(
        'campaigns.Campaign',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attributed_jobs',
    )

    sm8_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'jobs_cache'
        indexes = [
            models.Index(fields=['customer'], name='jobs_customer_idx'),
            models.Index(fields=['status'], name='jobs_status_idx'),
            models.Index(fields=['-completed_date'], name='jobs_completed_idx'),
            models.Index(
                fields=['status', 'completed_date', 'total_invoice_amount'],
                name='jobs_kpi_composite_idx',
            ),
        ]

    def __str__(self):
        return f'{self.status} — {self.job_type} — £{self.total_invoice_amount}'
    



class CustomerNote(TimestampedModel):
    """
    Private notes on a customer — visible to admin and staff but
    never exposed to the customer.
    """
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='notes',
    )
    author = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_notes',
    )
    body = models.TextField()

    class Meta:
        db_table = 'customer_notes'
        ordering = ['-created_at']

    def __str__(self):
        return f'Note on {self.customer.name} by {self.author}'