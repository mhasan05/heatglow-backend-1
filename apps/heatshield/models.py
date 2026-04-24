"""
HeatShield maintenance plan membership tracking.
"""
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel
from apps.customers.models import Customer


class HeatshieldMember(TimestampedModel):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        LAPSED = 'lapsed', 'Lapsed'
        CANCELLED = 'cancelled', 'Cancelled'
        PENDING_RENEWAL = 'pending_renewal', 'Pending renewal'

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='heatshield_memberships',
    )
    plan_type = models.CharField(max_length=50, default='standard')
    monthly_amount = models.DecimalField(max_digits=8, decimal_places=2, default=10.00)

    start_date = models.DateField()
    renewal_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    last_renewed_at = models.DateField(null=True, blank=True)

    # Reminder idempotency flags (prevent duplicate sends on cron re-run)
    renewal_reminder_60_sent = models.BooleanField(default=False)
    renewal_reminder_30_sent = models.BooleanField(default=False)
    renewal_reminder_0_sent = models.BooleanField(default=False)

    last_service_job_uuid = models.UUIDField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'heatshield_members'
        indexes = [
            models.Index(
                fields=['renewal_date'],
                name='hs_renewal_date_active_idx',
                condition=Q(status='active'),
            ),
        ]
        constraints = [
            # Partial unique: customer can have at most one ACTIVE membership
            models.UniqueConstraint(
                fields=['customer'],
                condition=Q(status='active'),
                name='hs_unique_active_member',
            ),
        ]

    def __str__(self):
        return f'{self.customer.name} — {self.status} (renews {self.renewal_date})'