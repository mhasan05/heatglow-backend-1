"""
Automation engine tasks.

Tier 1 — Fully automatic (no approval needed):
    heatshield_renewal_60  — 60-day renewal reminder
    heatshield_renewal_30  — 30-day renewal reminder
    heatshield_renewal_0   — day-of renewal reminder

Tier 2 — Requires Gareth's approval (Phase 5):
    lapsed_quote_followup
    inactive_customer_reengagement
    one_time_customer_upsell
    annual_service_reminder
    heatshield_lapsed_renewal
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)

# ── Queue processor ───────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name='automation.process_automation_queue',
)
def process_automation_queue(self):
    """
    Every 15 minutes: process pending AutomationQueue rows.
    Sends emails via Resend for each pending item.
    Marks items as sent or failed.
    Idempotent — safe to run multiple times.
    """
    from datetime import datetime
    from django.utils import timezone
    from apps.automation.models import AutomationQueue

    now = timezone.now()

    # Only pick up items scheduled for now or earlier
    pending = AutomationQueue.objects.filter(
        status=AutomationQueue.Status.PENDING,
        scheduled_for__lte=now,
    ).select_related('customer').order_by('scheduled_for')[:50]

    if not pending:
        logger.debug('process_automation_queue: nothing to process')
        return {'processed': 0}

    processed = failed = skipped = 0

    for item in pending:
        try:
            _process_queue_item(item)
            processed += 1
        except Exception as exc:
            logger.exception(
                'Queue item %s failed: %s', item.id, exc
            )
            item.status = AutomationQueue.Status.FAILED
            item.last_error = str(exc)
            item.attempts += 1
            item.save(update_fields=[
                'status', 'last_error', 'attempts', 'updated_at'
            ])
            failed += 1

    logger.info(
        'process_automation_queue complete: '
        'processed=%d failed=%d skipped=%d',
        processed, failed, skipped,
    )
    return {
        'processed': processed,
        'failed': failed,
        'skipped': skipped,
    }


def _process_queue_item(item) -> None:
    """Process a single AutomationQueue item."""
    from django.utils import timezone
    from apps.automation.models import AutomationQueue
    from apps.integrations.resend_client import send_email
    from apps.heatshield.emails import build_renewal_email

    # Mark as processing to prevent double-processing
    item.status = AutomationQueue.Status.PROCESSING
    item.save(update_fields=['status', 'updated_at'])

    automation_type = item.automation_type
    payload = item.payload
    customer = item.customer

    if not customer:
        logger.warning('Queue item %s has no customer — skipping', item.id)
        item.status = AutomationQueue.Status.SKIPPED
        item.save(update_fields=['status', 'updated_at'])
        return

    # ── HeatShield renewal reminders ──────────────────────────────────────────
    if automation_type in (
        'heatshield_renewal_60',
        'heatshield_renewal_30',
        'heatshield_renewal_0',
    ):
        _send_heatshield_reminder(item, payload, customer)
        return

    # ── Unknown type ──────────────────────────────────────────────────────────
    logger.warning(
        'Unknown automation type: %s — skipping', automation_type
    )
    item.status = AutomationQueue.Status.SKIPPED
    item.save(update_fields=['status', 'updated_at'])


def _send_heatshield_reminder(item, payload: dict, customer) -> None:
    """Send a HeatShield renewal reminder email."""
    from django.utils import timezone
    from apps.automation.models import AutomationQueue
    from apps.heatshield.models import HeatshieldMember
    from apps.integrations.resend_client import send_email
    from apps.heatshield.emails import build_renewal_email
    from apps.core.models import Setting

    # Check if automation is enabled
    try:
        enabled = Setting.objects.get(
            key='automation_heatshield_enabled'
        ).value
        if enabled is False:
            item.status = AutomationQueue.Status.SKIPPED
            item.save(update_fields=['status', 'updated_at'])
            logger.info(
                'HeatShield automation disabled — skipping item %s', item.id
            )
            return
    except Setting.DoesNotExist:
        pass  # Default to enabled

    # Verify customer has email
    if not customer.email or customer.email_opt_out:
        item.status = AutomationQueue.Status.SKIPPED
        item.save(update_fields=['status', 'updated_at'])
        logger.info(
            'Customer %s has no email or opted out — skipping', customer.id
        )
        return

    # Map automation type to reminder type
    reminder_map = {
        'heatshield_renewal_60': '60_day',
        'heatshield_renewal_30': '30_day',
        'heatshield_renewal_0': 'day_of',
    }
    reminder_type = reminder_map[item.automation_type]

    # Build and send the email
    email_content = build_renewal_email(
        customer_name=payload.get('customer_name', customer.name),
        renewal_date=payload.get('renewal_date', ''),
        plan_type=payload.get('plan_type', 'standard'),
        monthly_amount=payload.get('monthly_amount', '10.00'),
        reminder_type=reminder_type,
    )

    result = send_email(
        to=customer.email,
        subject=email_content['subject'],
        html=email_content['html'],
        tags=[
            {'name': 'type', 'value': 'heatshield_renewal'},
            {'name': 'reminder', 'value': reminder_type},
        ],
    )

    if result.success:
        # Mark the queue item as sent
        item.status = AutomationQueue.Status.SENT
        item.sent_at = timezone.now()
        item.save(update_fields=['status', 'sent_at', 'updated_at'])

        # Update the reminder flag on the HeatshieldMember
        flag_map = {
            'heatshield_renewal_60': 'renewal_reminder_60_sent',
            'heatshield_renewal_30': 'renewal_reminder_30_sent',
            'heatshield_renewal_0': 'renewal_reminder_0_sent',
        }
        flag_field = flag_map[item.automation_type]
        member_id = payload.get('member_id')
        if member_id:
            HeatshieldMember.objects.filter(id=member_id).update(
                **{flag_field: True}
            )

        logger.info(
            'HeatShield %s reminder sent to %s (member %s)',
            reminder_type, customer.email, member_id,
        )
    else:
        raise RuntimeError(
            'Resend failed: ' + (result.error or 'unknown error')
        )


# ── Tier 1 daily automation ───────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    name='automation.run_tier1_automations',
)
def run_tier1_automations(self):
    """
    Daily at 09:00 UTC.
    Scans for HeatShield members due for renewal reminders
    and populates the automation queue.

    The queue processor (every 15 min) then picks them up and sends.
    """
    try:
        summary = _check_heatshield_renewals()
        logger.info('Tier 1 automations complete: %s', summary)
        return summary
    except Exception as exc:
        logger.exception('Tier 1 automations failed: %s', exc)
        raise self.retry(exc=exc)
    

@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    name='automation.run_tier2_draft_prep',
)
def run_tier2_draft_prep(self):
    """
    Daily at 06:00 UTC.
    Runs all 6 Tier 2 automation checks and creates Campaign draft
    records for Gareth to approve in the Campaign Queue.
    """
    from apps.automation.tier2 import (
        generate_lapsed_quote_followup,
        generate_inactive_reengagement,
        generate_one_time_upsell,
        generate_annual_service_reminder,
        generate_heatshield_lapsed_renewal,
        generate_quote_no_response_chase,
    )

    results = {}
    generators = {
        'lapsed_quote': generate_lapsed_quote_followup,
        'inactive_reengagement': generate_inactive_reengagement,
        'one_time_upsell': generate_one_time_upsell,
        'annual_service': generate_annual_service_reminder,
        'heatshield_lapsed': generate_heatshield_lapsed_renewal,
        'quote_no_response': generate_quote_no_response_chase,
    }

    for name, generator in generators.items():
        try:
            results[name] = generator()
        except Exception as exc:
            logger.exception('Tier 2 generator %s failed: %s', name, exc)
            results[name] = {'error': str(exc)}

    logger.info('Tier 2 draft prep complete: %s', results)
    return results


def _check_heatshield_renewals() -> dict:
    """
    Check for HeatShield members whose renewal is in exactly
    60, 30, or 0 days and create queue entries if not already sent.
    """
    from datetime import date, timedelta
    from django.utils import timezone
    from apps.heatshield.models import HeatshieldMember
    from apps.automation.models import AutomationQueue

    today = date.today()
    created_total = 0

    checks = [
        (60, 'renewal_reminder_60_sent', 'heatshield_renewal_60'),
        (30, 'renewal_reminder_30_sent', 'heatshield_renewal_30'),
        (0,  'renewal_reminder_0_sent',  'heatshield_renewal_0'),
    ]

    for days_before, sent_flag, automation_type in checks:
        target_date = today + timedelta(days=days_before)

        # Find active members due on target_date who haven't been reminded yet
        members = HeatshieldMember.objects.filter(
            status='active',
            renewal_date=target_date,
        ).filter(**{sent_flag: False}).select_related('customer')

        for member in members:
            if not member.customer or not member.customer.email:
                continue

            idempotency_key = (
                automation_type + ':' +
                str(member.id) + ':' +
                member.renewal_date.isoformat()
            )

            _, created = AutomationQueue.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults={
                    'automation_type': automation_type,
                    'customer': member.customer,
                    'payload': {
                        'member_id': str(member.id),
                        'customer_name': member.customer.name,
                        'customer_email': member.customer.email,
                        'renewal_date': member.renewal_date.isoformat(),
                        'plan_type': member.plan_type,
                        'monthly_amount': str(member.monthly_amount),
                        'days_before': days_before,
                    },
                    'status': AutomationQueue.Status.PENDING,
                    'scheduled_for': timezone.now(),
                },
            )
            if created:
                created_total += 1
                logger.info(
                    'Queue entry created: %s for member %s',
                    automation_type, member.id,
                )

    return {
        'date_checked': today.isoformat(),
        'queue_entries_created': created_total,
    }


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=3600,
    name='automation.gdpr_anonymise_old_enquiries',
)
def gdpr_anonymise_old_enquiries(self):
    """
    Monthly on the 1st at 02:00 UTC.
    Anonymises personal data in rejected/cancelled enquiries older than 12 months.
    """
    import logging
    logger = logging.getLogger(__name__)
    from apps.enquiries.models import Enquiry
    from apps.core.models import AuditLog
    from datetime import timedelta
    from django.utils import timezone

    ANONYMISED_EMAIL = 'anonymised@deleted.invalid'
    cutoff = timezone.now() - timedelta(days=365)

    to_anonymise = Enquiry.objects.filter(
        status__in=['REJECTED', 'CANCELLED'],
        created_at__lt=cutoff,
    ).exclude(customer_email=ANONYMISED_EMAIL)

    anonymised_count = 0
    for enquiry in to_anonymise:
        enquiry.customer_name = 'Anonymised'
        enquiry.customer_email = ANONYMISED_EMAIL
        enquiry.customer_phone = '000000000'
        enquiry.customer_postcode = 'XX0 0XX'
        enquiry.description = '[Personal data removed under GDPR retention policy]'
        enquiry.save(update_fields=[
            'customer_name', 'customer_email', 'customer_phone',
            'customer_postcode', 'description', 'updated_at',
        ])
        AuditLog.objects.create(
            action='enquiry.gdpr_anonymised',
            entity_type='enquiry',
            entity_id=enquiry.id,
            metadata={
                'reason': 'GDPR 12-month retention policy',
                'age_days': (timezone.now() - enquiry.created_at).days,
            },
        )
        anonymised_count += 1

    logger.info('GDPR anonymisation: %d enquiries anonymised', anonymised_count)
    return {'anonymised': anonymised_count}