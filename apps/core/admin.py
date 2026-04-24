from django.contrib import admin
from .models import Setting, SuppressionListEntry, AuditLog, SyncLog


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'updated_at')
    search_fields = ('key',)


@admin.register(SuppressionListEntry)
class SuppressionListAdmin(admin.ModelAdmin):
    list_display = ('email', 'reason', 'suppressed_at')
    list_filter = ('reason',)
    search_fields = ('email',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'actor_user', 'entity_type', 'entity_id', 'created_at')
    list_filter = ('action', 'entity_type')
    search_fields = ('action', 'actor_user__username')
    readonly_fields = [f.name for f in AuditLog._meta.fields]


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ('sync_type', 'status', 'records_synced',
                    'started_at', 'finished_at')
    list_filter = ('sync_type', 'status')
    readonly_fields = [f.name for f in SyncLog._meta.fields]