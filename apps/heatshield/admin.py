from django.contrib import admin
from .models import HeatshieldMember


@admin.register(HeatshieldMember)
class HeatshieldMemberAdmin(admin.ModelAdmin):
    list_display = ('customer', 'plan_type', 'status', 'start_date',
                    'renewal_date', 'monthly_amount')
    list_filter = ('status', 'plan_type')
    search_fields = ('customer__name', 'customer__email')