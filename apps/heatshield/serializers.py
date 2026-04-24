"""
Serializers for the HeatShield membership API.
"""
from rest_framework import serializers
from apps.customers.models import Customer
from .models import HeatshieldMember


class HeatshieldMemberListSerializer(serializers.ModelSerializer):
    """Compact serializer for list view."""
    customer_name = serializers.SerializerMethodField()
    customer_email = serializers.SerializerMethodField()
    customer_postcode = serializers.SerializerMethodField()
    days_until_renewal = serializers.SerializerMethodField()
    renewal_status = serializers.SerializerMethodField()

    class Meta:
        model = HeatshieldMember
        fields = (
            'id', 'customer', 'customer_name',
            'customer_email', 'customer_postcode',
            'plan_type', 'monthly_amount',
            'start_date', 'renewal_date', 'status',
            'last_renewed_at',
            'renewal_reminder_60_sent',
            'renewal_reminder_30_sent',
            'renewal_reminder_0_sent',
            'days_until_renewal', 'renewal_status',
            'created_at',
        )
        read_only_fields = fields

    def get_customer_name(self, obj) -> str:
        return obj.customer.name if obj.customer else ''

    def get_customer_email(self, obj) -> str:
        return obj.customer.email or '' if obj.customer else ''

    def get_customer_postcode(self, obj) -> str:
        return obj.customer.postcode or '' if obj.customer else ''

    def get_days_until_renewal(self, obj) -> int | None:
        from datetime import date
        if obj.renewal_date:
            return (obj.renewal_date - date.today()).days
        return None

    def get_renewal_status(self, obj) -> str:
        """
        Returns a UI-friendly status badge label.
        """
        from datetime import date, timedelta
        if obj.status != 'active':
            return obj.status

        days = (obj.renewal_date - date.today()).days if obj.renewal_date else None
        if days is None:
            return 'active'
        elif days < 0:
            return 'overdue'
        elif days <= 7:
            return 'due_soon'
        elif days <= 30:
            return 'expiring_soon'
        elif days <= 60:
            return 'expiring_60'
        else:
            return 'active'


class HeatshieldMemberCreateSerializer(serializers.ModelSerializer):
    """Used for creating and updating HeatShield members."""
    customer_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = HeatshieldMember
        fields = (
            'customer_id', 'plan_type', 'monthly_amount',
            'start_date', 'renewal_date', 'status',
            'notes',
        )

    def validate_customer_id(self, value):
        try:
            Customer.objects.get(id=value)
        except Customer.DoesNotExist:
            raise serializers.ValidationError(
                'Customer not found.'
            )
        return value

    def validate(self, data):
        customer_id = data.get('customer_id')
        # Check for existing active membership
        if HeatshieldMember.objects.filter(
            customer_id=customer_id,
            status='active',
        ).exists():
            raise serializers.ValidationError(
                'This customer already has an active HeatShield membership.'
            )
        return data

    def create(self, validated_data):
        customer_id = validated_data.pop('customer_id')
        customer = Customer.objects.get(id=customer_id)
        member = HeatshieldMember.objects.create(
            customer=customer,
            **validated_data,
        )
        return member


class HeatshieldMemberDetailSerializer(serializers.ModelSerializer):
    """Full detail serializer."""
    customer_name = serializers.SerializerMethodField()
    customer_email = serializers.SerializerMethodField()
    days_until_renewal = serializers.SerializerMethodField()
    renewal_status = serializers.SerializerMethodField()

    class Meta:
        model = HeatshieldMember
        fields = (
            'id', 'customer', 'customer_name', 'customer_email',
            'plan_type', 'monthly_amount',
            'start_date', 'renewal_date', 'status',
            'last_renewed_at',
            'renewal_reminder_60_sent',
            'renewal_reminder_30_sent',
            'renewal_reminder_0_sent',
            'last_service_job_uuid',
            'notes',
            'days_until_renewal', 'renewal_status',
            'created_at', 'updated_at',
        )
        read_only_fields = (
            'id', 'customer', 'customer_name', 'customer_email',
            'renewal_reminder_60_sent',
            'renewal_reminder_30_sent',
            'renewal_reminder_0_sent',
            'days_until_renewal', 'renewal_status',
            'created_at', 'updated_at',
        )

    def get_customer_name(self, obj) -> str:
        return obj.customer.name if obj.customer else ''

    def get_customer_email(self, obj) -> str:
        return obj.customer.email or '' if obj.customer else ''

    def get_days_until_renewal(self, obj) -> int | None:
        from datetime import date
        if obj.renewal_date:
            return (obj.renewal_date - date.today()).days
        return None

    def get_renewal_status(self, obj) -> str:
        from datetime import date
        if obj.status != 'active':
            return obj.status
        days = (obj.renewal_date - date.today()).days if obj.renewal_date else None
        if days is None:
            return 'active'
        elif days < 0:
            return 'overdue'
        elif days <= 7:
            return 'due_soon'
        elif days <= 30:
            return 'expiring_soon'
        elif days <= 60:
            return 'expiring_60'
        return 'active'
    


class HeatshieldListSerializer(serializers.ModelSerializer):
    """
    List serializer — powers every row in the HeatShield Members table.

    Columns from screenshot:
      Member        — name + postcode
      Contact       — phone + email
      Monthly       — £10/mo
      Sign-up       — start_date
      Last Service  — last_renewed_at
      Status        — Active / Service Due / Lapsed / Cancelled badge
      Days Elapsed  — days since last service, colour coded
      Actions       — mark serviced, cancel, edit
    """
    # Member column
    customer_name = serializers.SerializerMethodField()
    customer_postcode = serializers.SerializerMethodField()
    customer_id = serializers.SerializerMethodField()

    # Contact column
    customer_phone = serializers.SerializerMethodField()
    customer_email = serializers.SerializerMethodField()

    # Status + days
    renewal_status = serializers.SerializerMethodField()
    days_elapsed = serializers.SerializerMethodField()
    days_elapsed_colour = serializers.SerializerMethodField()
    days_until_renewal = serializers.SerializerMethodField()
    progress_pct = serializers.SerializerMethodField()

    # Formatted fields
    monthly_amount_formatted = serializers.SerializerMethodField()
    sm8_deep_link = serializers.SerializerMethodField()

    class Meta:
        model = HeatshieldMember
        fields = (
            'id',
            # Member column
            'customer_id',
            'customer_name',
            'customer_postcode',
            # Contact column
            'customer_phone',
            'customer_email',
            # Plan
            'plan_type',
            'monthly_amount',
            'monthly_amount_formatted',
            # Dates
            'start_date',
            'renewal_date',
            'last_renewed_at',
            # Status
            'status',
            'renewal_status',
            # Days elapsed
            'days_elapsed',
            'days_elapsed_colour',
            'days_until_renewal',
            'progress_pct',
            # Reminder flags (for bell icon state)
            'renewal_reminder_60_sent',
            'renewal_reminder_30_sent',
            'renewal_reminder_0_sent',
            # SM8 link
            'sm8_deep_link',
            # Meta
            'notes',
            'created_at',
        )
        read_only_fields = fields

    def get_customer_name(self, obj) -> str:
        return obj.customer.name if obj.customer else ''

    def get_customer_postcode(self, obj) -> str:
        return obj.customer.postcode if obj.customer else ''

    def get_customer_id(self, obj) -> str:
        return str(obj.customer.id) if obj.customer else ''

    def get_customer_phone(self, obj) -> str:
        return obj.customer.phone if obj.customer else ''

    def get_customer_email(self, obj) -> str:
        return obj.customer.email if obj.customer else ''

    def get_monthly_amount_formatted(self, obj) -> str:
        return '\u00a3{:.0f}/mo'.format(float(obj.monthly_amount or 10))

    def get_sm8_deep_link(self, obj) -> str:
        if obj.customer and obj.customer.sm8_company_uuid:
            return (
                'https://go.servicem8.com/client/'
                + str(obj.customer.sm8_company_uuid)
            )
        return ''

    def get_days_elapsed(self, obj) -> int:
        from datetime import date
        reference = obj.last_renewed_at or obj.start_date
        if reference:
            return (date.today() - reference).days
        return 0

    def get_days_elapsed_colour(self, obj) -> str:
        """
        Colour for the days elapsed column.
        Green < 200d, Amber 200-305d, Red > 305d (service overdue).
        Matches the screenshot colours.
        """
        days = self.get_days_elapsed(obj)
        if days >= 305:
            return 'red'
        elif days >= 200:
            return 'amber'
        return 'green'

    def get_days_until_renewal(self, obj) -> int | None:
        from datetime import date
        if obj.renewal_date:
            return (obj.renewal_date - date.today()).days
        return None

    def get_progress_pct(self, obj) -> float:
        """Days elapsed as % of 365 — for the progress bar."""
        days = self.get_days_elapsed(obj)
        return round(min((days / 365) * 100, 100), 1)

    def get_renewal_status(self, obj) -> dict:
        """
        Status badge with label and colour.
        Matches screenshot: Active (green), Service Due (amber), Lapsed (red).
        """
        from datetime import date, timedelta

        if obj.status == 'cancelled':
            return {'label': 'Cancelled', 'colour': 'gray'}

        if obj.status == 'lapsed':
            return {'label': 'Lapsed', 'colour': 'red'}

        if obj.status != 'active':
            return {'label': obj.status.capitalize(), 'colour': 'gray'}

        # Active — check how close to renewal
        if not obj.renewal_date:
            return {'label': 'Active', 'colour': 'green'}

        days_until = (obj.renewal_date - date.today()).days
        days_elapsed = self.get_days_elapsed(obj)

        if days_until < 0 or days_elapsed >= 365:
            return {'label': 'Overdue', 'colour': 'red'}
        elif days_elapsed >= 305:
            return {'label': 'Service Due', 'colour': 'amber'}
        elif days_until <= 60:
            return {'label': 'Due Soon', 'colour': 'amber'}
        return {'label': 'Active', 'colour': 'green'}