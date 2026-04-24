"""
Campaign subsystem: Campaign → Batch → Event → Attribution.
"""
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel
from apps.customers.models import Customer, JobCache


class Campaign(TimestampedModel):
    class Type(models.TextChoices):
        ONE_OFF = 'one_off', 'One-off'
        AUTOMATION_TIER2 = 'automation_tier2', 'Automation tier 2'

    class SendMode(models.TextChoices):
        IMMEDIATE = 'immediate', 'Immediate'
        SCHEDULED = 'scheduled', 'Scheduled'
        SPREAD = 'spread', 'Spread'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SCHEDULED = 'scheduled', 'Scheduled'
        SENDING = 'sending', 'Sending'
        SENT = 'sent', 'Sent'
        PAUSED = 'paused', 'Paused'
        FAILED = 'failed', 'Failed'

    # Identity
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')

    # Targeting
    segment_filters = models.JSONField(default=list, blank=True)
    recipient_count = models.IntegerField(null=True, blank=True)

    # Content
    subject = models.CharField(max_length=255)
    body_html = models.TextField()
    from_name = models.CharField(max_length=100, default='Gareth — HeatGlow')
    from_email = models.EmailField(default='gareth@heatglow.co.uk')
    reply_to = models.EmailField(blank=True, default='')

    # Classification
    campaign_type = models.CharField(
        max_length=25,
        choices=Type.choices,
        default=Type.ONE_OFF,
    )
    automation_trigger = models.CharField(max_length=100, blank=True, default='')

    # Scheduling
    send_mode = models.CharField(
        max_length=15,
        choices=SendMode.choices,
        default=SendMode.IMMEDIATE,
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    spread_days = models.IntegerField(null=True, blank=True)

    # Workflow
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaigns_approved',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaigns_created',
    )

    # Roll-up metrics (updated by webhook event ingestion)
    total_sent = models.IntegerField(default=0)
    total_delivered = models.IntegerField(default=0)
    total_opened = models.IntegerField(default=0)
    total_clicked = models.IntegerField(default=0)
    total_bounced = models.IntegerField(default=0)
    attributed_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = 'campaigns'

    def __str__(self):
        return f'{self.name} ({self.status})'


class CampaignBatch(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENDING = 'sending', 'Sending'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='batches',
    )
    batch_number = models.IntegerField()
    customer_ids = ArrayField(base_field=models.UUIDField())
    scheduled_for = models.DateField()
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    send_count = models.IntegerField(null=True, blank=True)
    error_detail = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'campaign_batches'

    def __str__(self):
        return f'Batch {self.batch_number} of {self.campaign.name} ({self.status})'


class CampaignEvent(TimestampedModel):
    class EventType(models.TextChoices):
        SENT = 'sent', 'Sent'
        DELIVERED = 'delivered', 'Delivered'
        OPENED = 'opened', 'Opened'
        CLICKED = 'clicked', 'Clicked'
        BOUNCED = 'bounced', 'Bounced'
        SPAM_COMPLAINT = 'spam_complaint', 'Spam complaint'
        UNSUBSCRIBED = 'unsubscribed', 'Unsubscribed'

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='events',
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaign_events',
    )
    event_type = models.CharField(
        max_length=20,
        choices=EventType.choices,
    )
    resend_email_id = models.CharField(max_length=255, blank=True, default='')
    link_url = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = 'campaign_events'
        constraints = [
            # Partial unique: idempotent webhook processing
            models.UniqueConstraint(
                fields=['resend_email_id', 'event_type'],
                condition=~Q(resend_email_id=''),
                name='events_resend_idempotency',
            ),
        ]

    def __str__(self):
        return f'{self.event_type} — {self.campaign.name}'


class CampaignAttribution(TimestampedModel):
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='attributions',
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='attributions',
    )
    job = models.ForeignKey(
        JobCache,
        on_delete=models.CASCADE,
        related_name='attributions',
    )
    open_event = models.ForeignKey(
        CampaignEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    attributed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'campaign_attributions'

    def __str__(self):
        return f'£{self.revenue} → {self.campaign.name}'