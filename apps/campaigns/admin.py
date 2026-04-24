from django.contrib import admin
from .models import Campaign, CampaignBatch, CampaignEvent, CampaignAttribution


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'campaign_type', 'status', 'recipient_count',
                    'total_sent', 'total_opened', 'attributed_revenue')
    list_filter = ('campaign_type', 'status', 'send_mode')
    search_fields = ('name', 'subject')


@admin.register(CampaignBatch)
class CampaignBatchAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'batch_number', 'status', 'scheduled_for', 'send_count')
    list_filter = ('status',)


@admin.register(CampaignEvent)
class CampaignEventAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'customer', 'event_type', 'occurred_at')
    list_filter = ('event_type',)
    search_fields = ('campaign__name', 'customer__name', 'resend_email_id')


@admin.register(CampaignAttribution)
class CampaignAttributionAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'customer', 'job', 'revenue', 'attributed_at')
    search_fields = ('campaign__name', 'customer__name')