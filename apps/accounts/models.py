"""
User profile extension — one-to-one link to Django's built-in User.
Stores the role that drives RBAC across the API.
"""
import uuid
from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        STAFF = 'staff', 'Staff'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.STAFF,
    )
    phone = models.CharField(max_length=30, blank=True, default='')
    notification_prefs = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_profile'

    def __str__(self):
        return f'{self.user.username} ({self.role})'

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN