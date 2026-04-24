"""
Shared base models used across all apps.
"""
import uuid
from django.db import models
from django.conf import settings
from django.db.models import Q

class TimestampedModel(models.Model):
    """Abstract base: every concrete model inherits id, created_at, updated_at."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True




class Setting(models.Model):
    """Key-value configuration store. Key is the PK."""
    key = models.CharField(max_length=100, primary_key=True)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'settings'

    def __str__(self):
        return self.key


class SuppressionListEntry(TimestampedModel):
    class Reason(models.TextChoices):
        UNSUBSCRIBE = 'unsubscribe', 'Unsubscribe'
        BOUNCE = 'bounce', 'Bounce'
        COMPLAINT = 'complaint', 'Complaint'
        MANUAL = 'manual', 'Manual'

    email = models.EmailField(unique=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    source_campaign_id = models.UUIDField(null=True, blank=True)
    suppressed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'suppression_list'
        verbose_name_plural = 'suppression list entries'

    def __str__(self):
        return f'{self.email} ({self.reason})'


class AuditLog(models.Model):
    """Append-only audit trail of admin actions."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_entries',
    )
    action = models.CharField(max_length=100)  # e.g. 'enquiry.approve'
    entity_type = models.CharField(max_length=50, blank=True, default='')
    entity_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_log'
        indexes = [
            models.Index(fields=['-created_at'], name='audit_created_idx'),
        ]

    def __str__(self):
        return f'{self.action} by {self.actor_user}'


class SyncLog(models.Model):
    class SyncType(models.TextChoices):
        SM8_FULL = 'sm8_full', 'SM8 full'
        SM8_INCREMENTAL = 'sm8_incremental', 'SM8 incremental'
        WEBHOOK = 'webhook', 'Webhook'

    class Status(models.TextChoices):
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        FAIL = 'fail', 'Fail'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sync_type = models.CharField(max_length=25, choices=SyncType.choices)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.RUNNING)
    records_synced = models.IntegerField(default=0)
    error_detail = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'sync_log'

    def __str__(self):
        return f'{self.sync_type} — {self.status}'