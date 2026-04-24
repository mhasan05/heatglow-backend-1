"""
Automation work-queue. Populated by Tier 1 automation tasks,
consumed by the queue processor that dispatches emails via Resend.
"""
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel
from apps.customers.models import Customer


class AutomationQueue(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'

    automation_type = models.CharField(max_length=100)  # e.g. 'heatshield_renewal_60'
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='automation_items',
    )
    payload = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )
    scheduled_for = models.DateTimeField()
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)

    # Prevents duplicate sends — e.g. 'heatshield_renewal_60:<member_id>:<renewal_date>'
    idempotency_key = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'automation_queue'
        indexes = [
            models.Index(
                fields=['status', 'scheduled_for'],
                name='queue_poll_idx',
                condition=Q(status__in=['pending', 'failed']),
            ),
        ]

    def __str__(self):
        return f'{self.automation_type} → {self.customer.name} ({self.status})'