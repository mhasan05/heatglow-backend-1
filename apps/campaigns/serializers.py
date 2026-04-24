"""
Serializers for the Campaign Manager API.
"""
from rest_framework import serializers
from .models import Campaign, CampaignBatch, CampaignEvent, CampaignAttribution


class CampaignListSerializer(serializers.ModelSerializer):
    """Compact serializer for campaign list view."""
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    open_rate = serializers.SerializerMethodField()
    click_rate = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = (
            'id', 'name', 'description',
            'campaign_type', 'status', 'send_mode',
            'recipient_count', 'scheduled_for',
            'total_sent', 'total_delivered',
            'total_opened', 'total_clicked', 'total_bounced',
            'attributed_revenue',
            'open_rate', 'click_rate',
            'created_by', 'created_by_name',
            'approved_by', 'approved_by_name',
            'sent_at', 'created_at',
        )
        read_only_fields = fields

    def get_created_by_name(self, obj) -> str:
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return ''

    def get_approved_by_name(self, obj) -> str:
        if obj.approved_by:
            return obj.approved_by.get_full_name() or obj.approved_by.username
        return ''

    def get_open_rate(self, obj) -> float:
        if obj.total_delivered and obj.total_delivered > 0:
            return round((obj.total_opened / obj.total_delivered) * 100, 1)
        return 0.0

    def get_click_rate(self, obj) -> float:
        if obj.total_delivered and obj.total_delivered > 0:
            return round((obj.total_clicked / obj.total_delivered) * 100, 1)
        return 0.0


class CampaignCreateSerializer(serializers.ModelSerializer):
    """Used for creating campaign drafts."""

    class Meta:
        model = Campaign
        fields = (
            'name', 'description',
            'segment_filters',
            'subject', 'body_html',
            'from_name', 'from_email', 'reply_to',
            'campaign_type', 'automation_trigger',
            'send_mode', 'scheduled_for', 'spread_days',
        )

    def validate_segment_filters(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(
                'segment_filters must be a list.'
            )
        return value

    def validate(self, data):
        send_mode = data.get('send_mode', 'immediate')
        if send_mode == 'scheduled' and not data.get('scheduled_for'):
            raise serializers.ValidationError(
                'scheduled_for is required when send_mode is scheduled.'
            )
        if send_mode == 'spread' and not data.get('spread_days'):
            raise serializers.ValidationError(
                'spread_days is required when send_mode is spread.'
            )
        return data


class CampaignDetailSerializer(serializers.ModelSerializer):
    """Full serializer for campaign detail view."""
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    open_rate = serializers.SerializerMethodField()
    click_rate = serializers.SerializerMethodField()
    batches = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = (
            'id', 'name', 'description',
            'segment_filters', 'recipient_count',
            'subject', 'body_html',
            'from_name', 'from_email', 'reply_to',
            'campaign_type', 'automation_trigger',
            'send_mode', 'scheduled_for', 'spread_days',
            'status',
            'created_by', 'created_by_name',
            'approved_by', 'approved_by_name',
            'approved_at', 'sent_at',
            'total_sent', 'total_delivered',
            'total_opened', 'total_clicked', 'total_bounced',
            'attributed_revenue',
            'open_rate', 'click_rate',
            'batches',
            'created_at', 'updated_at',
        )
        read_only_fields = (
            'id', 'recipient_count', 'status',
            'created_by', 'approved_by', 'approved_at', 'sent_at',
            'total_sent', 'total_delivered', 'total_opened',
            'total_clicked', 'total_bounced', 'attributed_revenue',
            'created_at', 'updated_at',
        )

    def get_created_by_name(self, obj) -> str:
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return ''

    def get_approved_by_name(self, obj) -> str:
        if obj.approved_by:
            return obj.approved_by.get_full_name() or obj.approved_by.username
        return ''

    def get_open_rate(self, obj) -> float:
        if obj.total_delivered and obj.total_delivered > 0:
            return round((obj.total_opened / obj.total_delivered) * 100, 1)
        return 0.0

    def get_click_rate(self, obj) -> float:
        if obj.total_delivered and obj.total_delivered > 0:
            return round((obj.total_clicked / obj.total_delivered) * 100, 1)
        return 0.0

    def get_batches(self, obj) -> list:
        return list(obj.batches.values(
            'id', 'batch_number', 'status',
            'scheduled_for', 'send_count', 'sent_at',
        ))