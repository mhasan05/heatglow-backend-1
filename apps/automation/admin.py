from django.contrib import admin
from .models import AutomationQueue


@admin.register(AutomationQueue)
class AutomationQueueAdmin(admin.ModelAdmin):
    list_display = (
        'automation_type', 'customer', 'status',
        'scheduled_for', 'attempts', 'sent_at',
    )
    list_filter = ('automation_type', 'status')
    search_fields = ('customer__name', 'idempotency_key')
    readonly_fields = (
        'id', 'idempotency_key',
        'created_at', 'updated_at',
    )
    ordering = ('-scheduled_for',)