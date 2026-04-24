"""
Serializers for the customers API.
"""
from rest_framework import serializers
from .models import Customer, JobCache, CustomerNote


class JobCacheSerializer(serializers.ModelSerializer):
    """Job history entry on the customer profile."""

    class Meta:
        model = JobCache
        fields = (
            'id', 'sm8_job_uuid', 'status', 'job_type',
            'job_description', 'job_address',
            'total_invoice_amount', 'materials_cost',
            'created_date', 'completed_date', 'quote_date',
            'active',
        )
        read_only_fields = fields


class CustomerNoteSerializer(serializers.ModelSerializer):
    """Customer note with author name."""
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomerNote
        fields = (
            'id', 'body', 'author', 'author_name',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'author', 'author_name', 'created_at', 'updated_at')

    def get_author_name(self, obj) -> str:
        if obj.author:
            return obj.author.get_full_name() or obj.author.username
        return 'Unknown'


class CustomerListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for list views.
    Fast — no nested relations.
    """
    segment_labels = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = (
            'id','sm8_company_uuid', 'name', 'email', 'phone',
            'postcode', 'city',
            'total_spend', 'job_count',
            'last_job_date', 'last_job_type',
            'segments', 'segment_labels',
            'heatshield_status', 'email_opt_out',
            'sm8_synced_at', 'created_at',
        )
        read_only_fields = fields

    def get_segment_labels(self, obj) -> list[dict]:
        """Return segments with display labels and colours for badges."""
        label_map = {
            'vip': {'label': 'VIP', 'colour': 'amber'},
            'lapsed': {'label': 'Lapsed', 'colour': 'red'},
            'heatshield_active': {'label': 'HeatShield', 'colour': 'teal'},
            'one_time': {'label': 'One-Time', 'colour': 'purple'},
            'active': {'label': 'Active', 'colour': 'green'},
        }
        return [
            label_map.get(s, {'label': s, 'colour': 'gray'})
            for s in (obj.segments or [])
        ]


class JobCacheDetailSerializer(serializers.ModelSerializer):
    """
    Service History tab — one row per job.
    Matches the UI: job ref, type badge, status badge,
    description, date, engineer, amount.
    """
    job_ref = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    sm8_deep_link = serializers.SerializerMethodField()

    class Meta:
        model = JobCache
        fields = (
            'id', 'sm8_job_uuid',
            'job_ref', 'job_type',
            'job_description',
            'status', 'payment_status',
            'total_invoice_amount',
            'created_date', 'completed_date',
            'engineer_name',
            'sm8_deep_link',
            'active',
        )
        read_only_fields = fields

    def get_job_ref(self, obj) -> str:
        """Generate HG-YYYY-XXXX style ref from SM8 UUID."""
        if obj.sm8_job_uuid:
            short = str(obj.sm8_job_uuid).replace('-', '')[:4].upper()
            year = obj.created_date.year if obj.created_date else '2024'
            return f'HG-{year}-{short}'
        return ''

    def get_payment_status(self, obj) -> str:
        """Map SM8 status to UI payment badge."""
        status_map = {
            'Paid': 'Paid',
            'Invoice Sent': 'Awaiting Payment',
            'Completed': 'Completed',
            'Work Order': 'In Progress',
            'Quote': 'Quote',
            'Cancelled': 'Cancelled',
        }
        return status_map.get(obj.status, obj.status)

    def get_sm8_deep_link(self, obj) -> str:
        if obj.sm8_job_uuid:
            return f'https://go.servicem8.com/job/{obj.sm8_job_uuid}'
        return ''


class HeatShieldTabSerializer(serializers.ModelSerializer):
    """
    HeatShield tab — full membership detail with progress bar data.
    """
    days_elapsed = serializers.SerializerMethodField()
    days_until_renewal = serializers.SerializerMethodField()
    progress_pct = serializers.SerializerMethodField()
    renewal_status_label = serializers.SerializerMethodField()
    next_due_date = serializers.SerializerMethodField()

    class Meta:
        from apps.heatshield.models import HeatshieldMember
        model = HeatshieldMember
        fields = (
            'id',
            'status',
            'renewal_status_label',
            'plan_type',
            'monthly_amount',
            'start_date',
            'renewal_date',
            'next_due_date',
            'last_renewed_at',
            'days_elapsed',
            'days_until_renewal',
            'progress_pct',
            'renewal_reminder_60_sent',
            'renewal_reminder_30_sent',
            'renewal_reminder_0_sent',
            'notes',
        )
        read_only_fields = fields

    def get_days_elapsed(self, obj) -> int:
        """Days since last service (last_renewed_at or start_date)."""
        from datetime import date
        reference = obj.last_renewed_at or obj.start_date
        if reference:
            return (date.today() - reference).days
        return 0

    def get_days_until_renewal(self, obj) -> int | None:
        from datetime import date
        if obj.renewal_date:
            return (obj.renewal_date - date.today()).days
        return None

    def get_next_due_date(self, obj) -> str | None:
        if obj.renewal_date:
            return obj.renewal_date.isoformat()
        return None

    def get_progress_pct(self, obj) -> float:
        """
        Percentage of the way through the annual service cycle.
        Used for the progress bar: 320/365 days = 87.7%
        """
        from datetime import date
        reference = obj.last_renewed_at or obj.start_date
        if not reference:
            return 0.0
        elapsed = (date.today() - reference).days
        return round(min((elapsed / 365) * 100, 100), 1)

    def get_renewal_status_label(self, obj) -> str:
        from datetime import date, timedelta
        if obj.status != 'active':
            return obj.status.capitalize()
        if not obj.renewal_date:
            return 'Active'
        days = (obj.renewal_date - date.today()).days
        if days < 0:
            return 'Overdue'
        elif days <= 30:
            return 'Service Due'
        elif days <= 60:
            return 'Due Soon'
        return 'Active'


class CommunicationSerializer(serializers.Serializer):
    """
    Communications tab — emails sent to this customer.
    Combines CampaignEvents + transactional email log.
    """
    id = serializers.CharField()
    email_type = serializers.CharField()
    email_type_label = serializers.CharField()
    subject = serializers.CharField()
    sent_at = serializers.CharField()
    delivery_status = serializers.CharField()
    campaign_name = serializers.CharField(allow_null=True)
    opened = serializers.BooleanField()
    clicked = serializers.BooleanField()


class CustomerDetailSerializer(serializers.ModelSerializer):
    """
    Full customer profile — powers all 3 tabs + header.

    Header:
      - sm8_banner (sync info + SM8 deep link)
      - heatshield_banner (membership status if active)
      - customer_since, total_spend, job_count
      - name, address, phone, email, postcode

    Tabs:
      - service_history  → Image 3
      - heatshield       → Image 2
      - communications   → Image 1
    """
    segment_labels = serializers.SerializerMethodField()
    lifetime_value = serializers.SerializerMethodField()
    service_history = serializers.SerializerMethodField()
    heatshield = serializers.SerializerMethodField()
    communications = serializers.SerializerMethodField()
    sm8_banner = serializers.SerializerMethodField()
    heatshield_banner = serializers.SerializerMethodField()
    customer_since = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()
    sm8_deep_link = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = (
            # Header
            'id', 'sm8_company_uuid',
            'name', 'email', 'phone',
            'address_line1', 'address_line2',
            'city', 'postcode',
            'customer_since',
            'sm8_deep_link',
            'sm8_banner',
            'heatshield_banner',

            # Stats
            'total_spend', 'job_count',
            'last_job_date', 'last_job_type',
            'lifetime_value',

            # Segments
            'segments', 'segment_labels',
            'heatshield_status',

            # Settings
            'email_opt_out', 'unsubscribed_at',
            'sm8_synced_at',
            'created_at', 'updated_at',

            # Tabs
            'service_history',
            'heatshield',
            'communications',
            'notes',
        )
        read_only_fields = fields

    def get_customer_since(self, obj) -> str | None:
        """First job date or created_at — whichever is earlier."""
        first_job = obj.jobs.filter(
            status__in=['Completed', 'Invoice Sent', 'Paid', 'Work Order']
        ).order_by('created_date').first()
        if first_job and first_job.created_date:
            return first_job.created_date.isoformat()
        return obj.created_at.date().isoformat() if obj.created_at else None

    def get_sm8_deep_link(self, obj) -> str:
        if obj.sm8_company_uuid:
            return (
                f'https://go.servicem8.com/client/{obj.sm8_company_uuid}'
            )
        return ''

    def get_sm8_banner(self, obj) -> dict:
        """Top banner: 'Synced from ServiceM8 · SM8-XXXX'"""
        if obj.sm8_company_uuid:
            short_ref = 'SM8-' + str(obj.sm8_company_uuid).upper()[:4]
            return {
                'show': True,
                'label': f'Synced from ServiceM8 · {short_ref}',
                'sm8_ref': short_ref,
                'sm8_deep_link': self.get_sm8_deep_link(obj),
                'last_synced_at': (
                    obj.sm8_synced_at.isoformat()
                    if obj.sm8_synced_at else None
                ),
            }
        return {'show': False}

    def get_heatshield_banner(self, obj) -> dict:
        """
        Second banner: 'HeatShield Member — £10/month' with status badge.
        Only shown if customer has any HeatShield membership.
        """
        try:
            from apps.heatshield.models import HeatshieldMember
            member = HeatshieldMember.objects.filter(
                customer=obj
            ).order_by('-created_at').first()

            if not member:
                return {'show': False}

            from datetime import date, timedelta
            days_elapsed = 0
            if member.last_renewed_at:
                days_elapsed = (date.today() - member.last_renewed_at).days
            elif member.start_date:
                days_elapsed = (date.today() - member.start_date).days

            status_label = 'Active'
            if member.status != 'active':
                status_label = member.status.capitalize()
            elif member.renewal_date:
                days_until = (member.renewal_date - date.today()).days
                if days_until < 0:
                    status_label = 'Overdue'
                elif days_until <= 30:
                    status_label = 'Service Due'
                elif days_until <= 60:
                    status_label = 'Due Soon'

            return {
                'show': True,
                'label': (
                    f'HeatShield Member \u2014 '
                    f'\u00a3{float(member.monthly_amount):.0f}/month'
                ),
                'status': member.status,
                'status_label': status_label,
                'member_id': str(member.id),
                'days_elapsed': days_elapsed,
                'service_due': days_elapsed >= 305,
            }
        except Exception:
            return {'show': False}

    def get_lifetime_value(self, obj) -> dict:
        return {
            'total_spend': float(obj.total_spend),
            'job_count': obj.job_count,
            'avg_job_value': (
                round(float(obj.total_spend) / obj.job_count, 2)
                if obj.job_count > 0 else 0.0
            ),
        }

    def get_segment_labels(self, obj) -> list:
        label_map = {
            'vip': {'label': 'VIP', 'colour': 'amber'},
            'lapsed': {'label': 'Lapsed', 'colour': 'red'},
            'heatshield_active': {'label': 'HeatShield', 'colour': 'teal'},
            'one_time': {'label': 'One-Time', 'colour': 'purple'},
            'active': {'label': 'Active', 'colour': 'green'},
        }
        return [
            label_map.get(s, {'label': s, 'colour': 'gray'})
            for s in (obj.segments or [])
        ]

    def get_service_history(self, obj) -> list:
        """
        Service History tab — all jobs for this customer.
        Sorted by date descending (most recent first).
        """
        jobs = obj.jobs.order_by('-created_date')
        return JobCacheDetailSerializer(jobs, many=True).data

    def get_heatshield(self, obj) -> dict | None:
        """
        HeatShield tab — full membership detail.
        Returns None if customer has no HeatShield membership.
        """
        try:
            from apps.heatshield.models import HeatshieldMember
            member = HeatshieldMember.objects.filter(
                customer=obj
            ).order_by('-created_at').first()

            if not member:
                return {
                    'has_membership': False,
                    'message': 'This customer is not a HeatShield member.',
                }

            data = HeatShieldTabSerializer(member).data
            data['has_membership'] = True
            return data
        except Exception:
            return {'has_membership': False}

    def get_communications(self, obj) -> list:
        """
        Communications tab — ALL emails sent to this customer.
        Sources:
        1. CampaignEvents (bulk + automated emails)
        2. Enquiry-generated transactional emails
        """
        from apps.campaigns.models import CampaignEvent
        from apps.enquiries.models import Enquiry
        from django.db.models import Q

        results = []

        # ── Source 1: Campaign emails ─────────────────────────────────────────────
        try:
            events = CampaignEvent.objects.filter(
                customer=obj,
                event_type='sent',
            ).select_related('campaign').order_by('-occurred_at')

            for event in events:
                email_id = event.resend_email_id

                opened = CampaignEvent.objects.filter(
                    resend_email_id=email_id,
                    event_type='opened',
                ).exists() if email_id else False

                clicked = CampaignEvent.objects.filter(
                    resend_email_id=email_id,
                    event_type='clicked',
                ).exists() if email_id else False

                bounced = CampaignEvent.objects.filter(
                    resend_email_id=email_id,
                    event_type='bounced',
                ).exists() if email_id else False

                if bounced:
                    delivery_status = 'Bounced'
                elif clicked:
                    delivery_status = 'Clicked'
                elif opened:
                    delivery_status = 'Opened'
                else:
                    delivery_status = 'Delivered'

                campaign = event.campaign
                trigger = getattr(campaign, 'automation_trigger', None) or ''

                if 'heatshield' in trigger.lower():
                    email_type_label = 'HeatShield Reminder'
                elif 'quote' in trigger.lower():
                    email_type_label = 'Quote Follow-up'
                elif 'lapsed' in trigger.lower():
                    email_type_label = 'Re-engagement'
                elif 'annual' in trigger.lower():
                    email_type_label = 'Annual Service Reminder'
                elif campaign and campaign.campaign_type == 'one_off':
                    email_type_label = 'Campaign'
                else:
                    email_type_label = 'Automated'

                results.append({
                    'id': str(event.id),
                    'email_type': trigger or 'campaign',
                    'email_type_label': email_type_label,
                    'subject': campaign.subject if campaign else 'Email',
                    'sent_at': event.occurred_at.isoformat(),
                    'delivery_status': delivery_status,
                    'campaign_name': campaign.name if campaign else None,
                    'opened': opened,
                    'clicked': clicked,
                    'source': 'campaign',
                    'enquiry_id': None,
                    'enquiry_job_type': None,
                })
        except Exception as e:
            pass

        # ── Source 2: Enquiry transactional emails ────────────────────────────────
        try:
            enquiries = Enquiry.objects.filter(
                Q(customer=obj) |
                Q(customer_email__iexact=obj.email)
            ).order_by('-created_at')

            STATUS_MAP = {
                'APPROVED': {
                    'email_type_label': 'Enquiry Confirmation',
                    'subject': 'We can help \u2014 HeatGlow will be in touch shortly',
                    'delivery_status': 'Delivered',
                },
                'REJECTED': {
                    'email_type_label': 'Enquiry Declined',
                    'subject': 'Your HeatGlow enquiry',
                    'delivery_status': 'Delivered',
                },
                'NEEDS_MANUAL_REVIEW': {
                    'email_type_label': 'Enquiry Acknowledgement',
                    'subject': "We've received your enquiry \u2014 HeatGlow",
                    'delivery_status': 'Delivered',
                },
                'PENDING': {
                    'email_type_label': 'Enquiry Acknowledgement',
                    'subject': "We've received your enquiry \u2014 HeatGlow",
                    'delivery_status': 'Delivered',
                },
                'CANCELLED': {
                    'email_type_label': 'Enquiry Expired',
                    'subject': 'Your HeatGlow enquiry has expired',
                    'delivery_status': 'Delivered',
                },
            }

            for enquiry in enquiries:
                config = STATUS_MAP.get(enquiry.status)
                if not config:
                    continue

                # Use reviewed_at for APPROVED/REJECTED,
                # otherwise use created_at
                if enquiry.status in ('APPROVED', 'REJECTED') and enquiry.reviewed_at:
                    sent_at = enquiry.reviewed_at
                else:
                    sent_at = enquiry.created_at

                # Safe isoformat — never crash on None
                sent_at_str = sent_at.isoformat() if sent_at else enquiry.created_at.isoformat()

                results.append({
                    'id': 'enquiry-' + str(enquiry.id),
                    'email_type': enquiry.status.lower(),
                    'email_type_label': config['email_type_label'],
                    'subject': config['subject'],
                    'sent_at': sent_at_str,
                    'delivery_status': config['delivery_status'],
                    'campaign_name': None,
                    'opened': False,
                    'clicked': False,
                    'source': 'enquiry',
                    'enquiry_id': str(enquiry.id),
                    'enquiry_job_type': enquiry.job_type or '',
                    'customer_name': enquiry.customer_name,
                    'customer_email': enquiry.customer_email,
                })

        except Exception as e:
            pass

        # ── Sort all by date descending ───────────────────────────────────────────
        results.sort(key=lambda x: x['sent_at'], reverse=True)

        return results

    def get_notes(self, obj) -> list:
        """Private internal notes on this customer."""
        return [
            {
                'id': str(note.id),
                'body': note.body,
                'author': (
                    note.author.get_full_name() or note.author.username
                    if note.author else 'Unknown'
                ),
                'created_at': note.created_at.isoformat(),
            }
            for note in obj.notes.order_by('-created_at')
        ]