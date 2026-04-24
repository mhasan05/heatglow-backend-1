"""
Serializers for the enquiries API.
"""
from rest_framework import serializers
from .models import Enquiry


class EnquiryCreateSerializer(serializers.ModelSerializer):
    """
    Used for the public intake form — POST /api/v1/enquiries/
    Only accepts fields the customer fills out.
    AI fields and workflow fields are set by the backend.
    """
    class Meta:
        model = Enquiry
        fields = (
            'customer_name',
            'customer_email',
            'customer_phone',
            'customer_postcode',
            'job_type',
            'description',
            'urgency',
            'preferred_date',
            'source',
        )

    def validate_customer_postcode(self, value: str) -> str:
        return value.upper().strip()

    def validate_customer_email(self, value: str) -> str:
        return value.lower().strip()


class EnquiryListSerializer(serializers.ModelSerializer):
    """Compact serializer for list view."""
    customer_name_display = serializers.SerializerMethodField()

    class Meta:
        model = Enquiry
        fields = (
            'id',
            'customer_name',
            'customer_name_display',
            'customer_email',
            'customer_postcode',
            'job_type',
            'urgency',
            'ai_score',
            'ai_recommendation',
            'status',
            'source',
            'created_at',
        )
        read_only_fields = fields

    def get_customer_name_display(self, obj) -> str:
        return obj.customer_name or obj.customer_email


class EnquiryDetailSerializer(serializers.ModelSerializer):
    """Full detail serializer including activity timeline and customer match."""
    reviewed_by_name = serializers.SerializerMethodField()
    customer_match = serializers.SerializerMethodField()
    activity = serializers.SerializerMethodField()
    internal_notes = serializers.SerializerMethodField()

    class Meta:
        model = Enquiry
        fields = (
            'id',
            'customer_name', 'customer_email',
            'customer_phone', 'customer_postcode',
            'job_type', 'urgency', 'source',
            'description',
            'status',
            'ai_score', 'ai_recommendation',
            'ai_confidence', 'ai_explanation',
            'ai_flags', 'ai_qualified_at',
            'rejection_reason',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at',
            'customer', 'customer_match',
            'activity',
            'internal_notes',
            'created_at', 'updated_at',
        )
        read_only_fields = fields

    def get_reviewed_by_name(self, obj) -> str:
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name() or obj.reviewed_by.username
        return ''

    def get_customer_match(self, obj) -> dict:
        """
        Check if this enquiry matches an existing SM8 customer
        by email or phone.
        """
        from apps.customers.models import Customer
        from django.db.models import Q

        customer = None

        # Try linked customer first
        if obj.customer:
            customer = obj.customer
        else:
            # Search by email or phone
            q = Q()
            if obj.customer_email:
                q |= Q(email__iexact=obj.customer_email)
            if obj.customer_phone:
                q |= Q(phone__icontains=obj.customer_phone.replace(' ', ''))
            if q:
                customer = Customer.objects.filter(q).first()

        if customer:
            return {
                'found': True,
                'customer_id': str(customer.id),
                'name': customer.name,
                'email': customer.email,
                'phone': customer.phone,
                'postcode': customer.postcode,
                'job_count': customer.job_count,
                'total_spend': float(customer.total_spend),
                'last_job_date': (
                    customer.last_job_date.isoformat()
                    if customer.last_job_date else None
                ),
                'heatshield_status': customer.heatshield_status,
                'segments': customer.segments or [],
                'is_new_customer': False,
            }

        return {
            'found': False,
            'is_new_customer': True,
            'message': 'No match found in SM8. This appears to be a new customer.',
        }

    def get_activity(self, obj) -> list:
        """
        Build the activity timeline for this enquiry.
        Combines:
          - Enquiry submission (from created_at)
          - AI scoring completed (from ai_qualified_at)
          - Enquiry approved/rejected (from reviewed_at)
          - Audit log entries for this enquiry
          - SM8 push events
        """
        from apps.core.models import AuditLog
        from django.utils import timezone

        events = []

        # ── 1. Enquiry submitted ──────────────────────────────────────────────
        events.append({
            'id': 'submitted',
            'type': 'submitted',
            'title': 'Enquiry submitted via website',
            'description': None,
            'actor': 'System',
            'actor_type': 'system',
            'occurred_at': obj.created_at.isoformat(),
        })

        # ── 2. AI scoring completed ───────────────────────────────────────────
        if obj.ai_qualified_at and obj.ai_score is not None:
            events.append({
                'id': 'ai_scored',
                'type': 'ai_scored',
                'title': (
                    'AI scoring completed'
                    + ' \u2014 Score ' + str(obj.ai_score)
                    + ', recommendation: ' + (obj.ai_recommendation or 'N/A')
                ),
                'description': obj.ai_explanation or None,
                'actor': 'Gemini AI',
                'actor_type': 'ai',
                'occurred_at': obj.ai_qualified_at.isoformat(),
            })

        # ── 3. Approved or rejected ───────────────────────────────────────────
        if obj.reviewed_at and obj.reviewed_by:
            actor_name = (
                obj.reviewed_by.get_full_name()
                or obj.reviewed_by.username
            )
            if obj.status == 'APPROVED':
                title = 'Enquiry approved by ' + actor_name
                description = None
                event_type = 'approved'
            elif obj.status == 'REJECTED':
                title = 'Enquiry rejected by ' + actor_name
                description = (
                    'Reason: ' + obj.rejection_reason
                    if obj.rejection_reason else None
                )
                event_type = 'rejected'
            else:
                title = 'Status updated by ' + actor_name
                description = None
                event_type = 'status_change'

            events.append({
                'id': 'reviewed',
                'type': event_type,
                'title': title,
                'description': description,
                'actor': actor_name,
                'actor_type': 'user',
                'occurred_at': obj.reviewed_at.isoformat(),
            })

        # ── 4. SM8 push status ────────────────────────────────────────────────
        if obj.sm8_job_uuid and obj.sm8_push_status == 'success':
            events.append({
                'id': 'sm8_push',
                'type': 'sm8_pushed',
                'title': 'Job created in ServiceM8',
                'description': 'SM8 Job UUID: ' + str(obj.sm8_job_uuid),
                'actor': 'System',
                'actor_type': 'system',
                'occurred_at': obj.reviewed_at.isoformat() if obj.reviewed_at else obj.updated_at.isoformat(),
            })
        elif obj.sm8_push_status == 'failed':
            events.append({
                'id': 'sm8_push_failed',
                'type': 'sm8_failed',
                'title': 'ServiceM8 push failed',
                'description': 'The job could not be created in SM8. Manual entry required.',
                'actor': 'System',
                'actor_type': 'system',
                'occurred_at': obj.updated_at.isoformat(),
            })

        # ── 5. Audit log entries for this enquiry ─────────────────────────────
        audit_entries = AuditLog.objects.filter(
            entity_type='enquiry',
            entity_id=obj.id,
        ).select_related('actor_user').order_by('created_at')

        for entry in audit_entries:
            # Skip events we already added manually
            if entry.action in (
                'enquiry.created',
                'enquiry.ai_scored',
            ):
                continue

            actor_name = 'System'
            actor_type = 'system'
            if entry.actor_user:
                actor_name = (
                    entry.actor_user.get_full_name()
                    or entry.actor_user.username
                )
                actor_type = 'user'

            # Human-readable titles
            title_map = {
                'enquiry.approved': 'Enquiry approved',
                'enquiry.rejected': 'Enquiry rejected',
                'enquiry.auto_approved': 'Enquiry auto-approved by AI',
                'enquiry.auto_expired': 'Enquiry auto-expired (no action taken)',
                'enquiry.note_added': 'Internal note added',
                'enquiry.viewed': 'Enquiry viewed by ' + actor_name,
                'sm8.job_created': 'Job created in ServiceM8',
                'sm8.push_failed': 'ServiceM8 push failed',
            }
            title = title_map.get(entry.action, entry.action)

            events.append({
                'id': str(entry.id),
                'type': entry.action,
                'title': title,
                'description': (
                    str(entry.metadata) if entry.metadata else None
                ),
                'actor': actor_name,
                'actor_type': actor_type,
                'occurred_at': entry.created_at.isoformat(),
            })

        # Sort all events by time ascending
        events.sort(key=lambda x: x['occurred_at'])

        # Deduplicate by id
        seen = set()
        unique_events = []
        for event in events:
            if event['id'] not in seen:
                seen.add(event['id'])
                unique_events.append(event)

        return unique_events

    def get_internal_notes(self, obj) -> list:
        """
        Return internal notes for this enquiry from AuditLog
        where action = 'enquiry.note_added'.
        """
        from apps.core.models import AuditLog

        notes = AuditLog.objects.filter(
            entity_type='enquiry',
            entity_id=obj.id,
            action='enquiry.note_added',
        ).select_related('actor_user').order_by('-created_at')

        return [
            {
                'id': str(n.id),
                'body': n.metadata.get('note', '') if n.metadata else '',
                'author': (
                    n.actor_user.get_full_name() or n.actor_user.username
                    if n.actor_user else 'Unknown'
                ),
                'created_at': n.created_at.isoformat(),
            }
            for n in notes
        ]