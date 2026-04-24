from django.contrib import admin
from .models import Customer, JobCache, CustomerNote

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'postcode', 'total_spend', 'job_count',
                    'heatshield_status', 'last_job_date')
    list_filter = ('heatshield_status', 'email_opt_out')
    search_fields = ('name', 'email', 'phone', 'postcode')
    readonly_fields = ('id', 'created_at', 'updated_at', 'sm8_synced_at','total_spend', 'job_count', 'last_job_date', 'last_job_type')


@admin.register(JobCache)
class JobCacheAdmin(admin.ModelAdmin):
    list_display = ('sm8_job_uuid', 'customer', 'status', 'job_type',
                    'total_invoice_amount', 'completed_date')
    list_filter = ('status', 'active')
    search_fields = ('customer__name', 'job_description', 'job_address')
    readonly_fields = [f.name for f in JobCache._meta.fields]


@admin.register(CustomerNote)
class CustomerNoteAdmin(admin.ModelAdmin):
    list_display = ('customer', 'author', 'created_at')
    search_fields = ('customer__name', 'body')
    raw_id_fields = ('customer',)