"""
Enquiry background tasks.
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name='enquiries.qualify_enquiry_async',
)
def qualify_enquiry_async(self, enquiry_id: str):
    """
    1. Call Gemini to score the enquiry
    2. Save AI results to the enquiry record
    3. Send customer acknowledgement email
    4. Send Gareth notification email with one-click approve/reject
    5. Auto-approve if score meets threshold and setting is enabled
    """
    from apps.enquiries.models import Enquiry
    from apps.integrations.gemini import qualify_enquiry
    from apps.integrations.resend_client import send_email
    from apps.enquiries.emails import (
        build_gareth_notification_html,
        build_customer_acknowledgement_html,
    )
    from apps.core.models import Setting, AuditLog
    from django.conf import settings as django_settings
    from django.utils import timezone

    try:
        enquiry = Enquiry.objects.get(id=enquiry_id)
    except Enquiry.DoesNotExist:
        logger.warning('qualify_enquiry_async: enquiry %s not found', enquiry_id)
        return

    logger.info(
        'Qualifying enquiry %s — %s in %s',
        enquiry_id, enquiry.job_type, enquiry.customer_postcode,
    )

    # ── Step 1: AI qualification ──────────────────────────────────────────────
    try:
        result = qualify_enquiry(
            customer_name=enquiry.customer_name,
            postcode=enquiry.customer_postcode,
            job_type=enquiry.job_type,
            urgency=enquiry.urgency,
            description=enquiry.description,
        )
    except Exception as exc:
        logger.exception('Qualification failed for %s: %s', enquiry_id, exc)
        raise self.retry(exc=exc)

    # ── Step 2: Save AI results ───────────────────────────────────────────────
    enquiry.ai_score = result.score
    enquiry.ai_recommendation = result.recommendation
    enquiry.ai_confidence = result.confidence
    enquiry.ai_explanation = result.explanation
    enquiry.ai_flags = result.flags
    enquiry.ai_qualified_at = timezone.now()

    # ── Step 3: Customer acknowledgement email ────────────────────────────────
    if enquiry.customer_email:
        try:
            ack_html = build_customer_acknowledgement_html(enquiry)
            send_email(
                to=enquiry.customer_email,
                subject=f'HeatGlow — We received your enquiry ({enquiry.job_type})',
                html=ack_html,
                tags=[{'name': 'type', 'value': 'enquiry_ack'}],
            )
            logger.info('Acknowledgement sent to %s', enquiry.customer_email)
        except Exception as exc:
            logger.warning('Failed to send ack email: %s', exc)

    # ── Step 4: Check auto-approve settings ───────────────────────────────────
    try:
        auto_enabled = Setting.objects.get(key='ai_auto_approve_enabled').value
        threshold = int(Setting.objects.get(key='ai_auto_approve_threshold').value)
        send_notification = Setting.objects.get(
            key='automation_heatshield_enabled'
        ).value
    except Setting.DoesNotExist:
        auto_enabled = False
        threshold = 85
        send_notification = True

    if (
        auto_enabled is True
        and result.recommendation == 'APPROVE'
        and result.score >= threshold
    ):
        enquiry.status = Enquiry.Status.APPROVED
        logger.info(
            'Enquiry %s auto-approved (score=%d >= threshold=%d)',
            enquiry_id, result.score, threshold,
        )
        AuditLog.objects.create(
            action='enquiry.auto_approve',
            entity_type='enquiry',
            entity_id=enquiry.id,
            metadata={
                'score': result.score,
                'threshold': threshold,
                'recommendation': result.recommendation,
            },
        )
    else:
        enquiry.status = Enquiry.Status.NEEDS_MANUAL_REVIEW

    enquiry.save()

    # ── Step 5: Gareth notification email ─────────────────────────────────────
    try:
        frontend_origin = getattr(
            django_settings, 'FRONTEND_ORIGIN', 'http://localhost:3000'
        )
        approve_url = (
            f'{frontend_origin}/enquiries/{enquiry_id}/approve/'
        )
        reject_url = (
            f'{frontend_origin}/enquiries/{enquiry_id}/reject/'
        )

        gareth_html = build_gareth_notification_html(
            enquiry, approve_url, reject_url
        )

        urgency_prefix = '🚨 EMERGENCY — ' if enquiry.urgency == 'emergency' else ''
        send_email(
            to=django_settings.GARETH_EMAIL,
            subject=(
                f'{urgency_prefix}New Enquiry: {enquiry.job_type} '
                f'— {enquiry.customer_postcode} '
                f'(Score: {result.score})'
            ),
            html=gareth_html,
            tags=[
                {'name': 'type', 'value': 'enquiry_notification'},
                {'name': 'score', 'value': str(result.score)},
            ],
        )
        logger.info(
            'Gareth notification sent for enquiry %s (score=%d)',
            enquiry_id, result.score,
        )
    except Exception as exc:
        logger.warning('Failed to send Gareth notification: %s', exc)

    logger.info(
        'Enquiry %s qualified: score=%d recommendation=%s status=%s',
        enquiry_id, result.score, result.recommendation, enquiry.status,
    )

    return {
        'enquiry_id': enquiry_id,
        'score': result.score,
        'recommendation': result.recommendation,
        'confidence': result.confidence,
        'status': enquiry.status,
    }



@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    name='enquiries.auto_expire_enquiries',
)
def auto_expire_enquiries_task(self):
    """
    Daily at 07:00 UTC.
    Expire enquiries with no action after N days (default 14).
    """
    import logging
    logger = logging.getLogger(__name__)
    from apps.enquiries.models import Enquiry
    from apps.core.models import AuditLog, Setting
    from datetime import timedelta
    from django.utils import timezone

    try:
        days = int(Setting.objects.get(key='auto_expire_enquiry_days').value)
    except Exception:
        days = 14

    cutoff = timezone.now() - timedelta(days=days)

    stale = Enquiry.objects.filter(
        status__in=['PENDING', 'NEEDS_MANUAL_REVIEW'],
        created_at__lt=cutoff,
    )

    expired_count = 0
    for enquiry in stale:
        enquiry.status = 'CANCELLED'
        enquiry.save(update_fields=['status', 'updated_at'])
        AuditLog.objects.create(
            action='enquiry.auto_expired',
            entity_type='enquiry',
            entity_id=enquiry.id,
            metadata={
                'reason': f'No action taken within {days} days',
                'age_days': (timezone.now() - enquiry.created_at).days,
            },
        )
        expired_count += 1

    logger.info('auto_expire_enquiries: expired %d enquiries', expired_count)
    return {'expired': expired_count, 'cutoff_days': days}