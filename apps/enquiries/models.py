"""
Enquiry intake from public form + AI qualification + Gareth approval.
"""
from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel
from apps.customers.models import Customer


class Enquiry(TimestampedModel):

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        NEEDS_MANUAL_REVIEW = 'NEEDS_MANUAL_REVIEW', 'Needs Manual Review'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class Urgency(models.TextChoices):
        EMERGENCY = 'emergency', 'Emergency'
        URGENT = 'urgent', 'Urgent'
        ROUTINE = 'routine', 'Routine'
        FLEXIBLE = 'flexible', 'Flexible'

    class Source(models.TextChoices):
        WEBSITE = 'website', 'Website'
        REFERRAL = 'referral', 'Referral'
        GOOGLE = 'google', 'Google'
        FACEBOOK = 'facebook', 'Facebook'
        CHECKATRADE = 'checkatrade', 'Checkatrade'
        PHONE = 'phone', 'Phone'
        OTHER = 'other', 'Other'

    class SM8PushStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'

    # ── Customer details ──────────────────────────────────────────────────────
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='enquiries',
    )
    customer_name = models.CharField(max_length=255)
    customer_email = models.EmailField(blank=True, default='')
    customer_phone = models.CharField(max_length=30, blank=True, default='')
    customer_postcode = models.CharField(max_length=10, blank=True, default='')

    # ── Job details ───────────────────────────────────────────────────────────
    job_type = models.CharField(max_length=100)
    description = models.TextField()
    urgency = models.CharField(
        max_length=20,
        choices=Urgency.choices,
        default=Urgency.ROUTINE,
    )
    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.WEBSITE,
        blank=True,
    )
    preferred_date = models.DateField(null=True, blank=True)

    # ── Status ────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # ── AI scoring ────────────────────────────────────────────────────────────
    ai_score = models.IntegerField(null=True, blank=True)
    ai_recommendation = models.CharField(max_length=20, blank=True, default='')
    ai_confidence = models.CharField(max_length=10, blank=True, default='')
    ai_explanation = models.TextField(blank=True, default='')
    ai_flags = models.JSONField(default=list, blank=True)
    ai_qualified_at = models.DateTimeField(null=True, blank=True)

    # ── Review ────────────────────────────────────────────────────────────────
    reviewed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_enquiries',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')

    # ── SM8 integration ───────────────────────────────────────────────────────
    sm8_job_uuid = models.UUIDField(null=True, blank=True)
    sm8_created_at = models.DateTimeField(null=True, blank=True)
    sm8_push_status = models.CharField(           # NEW
        max_length=10,
        choices=SM8PushStatus.choices,
        blank=True,
        default='',
    )
    sm8_push_attempts = models.IntegerField(default=0)    # NEW
    sm8_push_error = models.TextField(blank=True, default='')  # NEW

    class Meta:
        db_table = 'enquiries'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['customer_email']),
            models.Index(fields=['customer_phone']),
        ]

    def __str__(self):
        return f'{self.customer_name} — {self.job_type} ({self.status})'