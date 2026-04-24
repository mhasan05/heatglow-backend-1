from django.contrib import admin
from .models import Enquiry


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ('customer_name', 'customer_email', 'customer_postcode',
                    'job_type', 'urgency', 'ai_score', 'status', 'created_at')
    list_filter = ('status', 'urgency', 'ai_recommendation', 'source')
    search_fields = ('customer_name', 'customer_email', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at', 'ai_qualified_at','reviewed_at', 'sm8_job_uuid', 'sm8_created_at')