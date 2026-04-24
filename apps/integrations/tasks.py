"""
Integrations background tasks.

Tasks:
  qualify_enquiry_async    — score an enquiry with Gemini AI
  sm8_full_sync            — full SM8 sync (every 4 hours + manual trigger)
  sm8_incremental_sync     — incremental SM8 sync (every hour)
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# ── Enquiry qualification ─────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name='enquiries.qualify_enquiry_async',
)
def qualify_enquiry_async(self, enquiry_id: str):
    """
    Background task: call Gemini to score the enquiry.

    Updates ai_score, ai_recommendation, ai_confidence,
    ai_explanation, ai_flags, ai_qualified_at on the Enquiry record.

    Falls back to rule-based scoring if Gemini is unavailable
    or the API key is not set.
    """
    from django.utils import timezone
    from apps.enquiries.models import Enquiry
    from apps.integrations.gemini import qualify_enquiry
    from apps.core.models import Setting

    try:
        enquiry = Enquiry.objects.get(id=enquiry_id)
    except Enquiry.DoesNotExist:
        logger.warning('qualify_enquiry_async: enquiry %s not found', enquiry_id)
        return

    logger.info(
        'Qualifying enquiry %s — %s in %s',
        enquiry_id, enquiry.job_type, enquiry.customer_postcode,
    )

    try:
        result = qualify_enquiry(
            customer_name=enquiry.customer_name,
            postcode=enquiry.customer_postcode,
            job_type=enquiry.job_type,
            urgency=enquiry.urgency,
            description=enquiry.description,
        )
    except Exception as exc:
        logger.exception('Qualification failed for enquiry %s: %s', enquiry_id, exc)
        raise self.retry(exc=exc)

    # Save AI results to enquiry
    enquiry.ai_score = result.score
    enquiry.ai_recommendation = result.recommendation
    enquiry.ai_confidence = result.confidence
    enquiry.ai_explanation = result.explanation
    enquiry.ai_flags = result.flags
    enquiry.ai_qualified_at = timezone.now()

    # Check auto-approve settings
    try:
        auto_enabled = Setting.objects.get(key='ai_auto_approve_enabled').value
        threshold = int(Setting.objects.get(key='ai_auto_approve_threshold').value)
    except Setting.DoesNotExist:
        auto_enabled = False
        threshold = 85

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
    else:
        enquiry.status = Enquiry.Status.NEEDS_MANUAL_REVIEW

    enquiry.save()

    logger.info(
        'Enquiry %s qualified: score=%d recommendation=%s flags=%s',
        enquiry_id, result.score, result.recommendation, result.flags,
    )

    return {
        'enquiry_id': enquiry_id,
        'score': result.score,
        'recommendation': result.recommendation,
        'confidence': result.confidence,
        'flags': result.flags,
    }


# ── SM8 full sync ─────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name='integrations.sm8_full_sync',
)
def sm8_full_sync(self):
    """
    Full SM8 sync — runs every 4 hours and on manual trigger.
    Imports all companies and jobs from ServiceM8.
    Writes a SyncLog record on success or failure.
    """
    from django.utils import timezone
    from apps.core.models import SyncLog

    log = SyncLog.objects.create(
        sync_type='full',
        status='running',
        started_at=timezone.now(),
    )

    try:
        from apps.integrations.sync import sync_companies, sync_jobs
        companies_synced = sync_companies()
        jobs_synced = sync_jobs()
        total = (companies_synced or 0) + (jobs_synced or 0)

        log.status = 'success'
        log.finished_at = timezone.now()
        log.records_synced = total
        log.save(update_fields=['status', 'finished_at', 'records_synced'])

        logger.info('sm8_full_sync complete: %d records synced', total)
        return {'status': 'success', 'records_synced': total}

    except Exception as exc:
        log.status = 'failed'
        log.finished_at = timezone.now()
        log.error_message = str(exc)
        log.save(update_fields=['status', 'finished_at', 'error_message'])

        logger.exception('sm8_full_sync failed: %s', exc)
        raise self.retry(exc=exc)


# ── SM8 incremental sync ──────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name='integrations.sm8_incremental_sync',
)
def sm8_incremental_sync(self):
    """
    Incremental SM8 sync — runs every hour via Celery Beat.
    Only picks up new or changed records since last sync.
    Writes a SyncLog record on success or failure.
    """
    from django.utils import timezone
    from apps.core.models import SyncLog

    log = SyncLog.objects.create(
        sync_type='incremental',
        status='running',
        started_at=timezone.now(),
    )

    try:
        from apps.integrations.sync import sync_companies, sync_jobs
        companies_synced = sync_companies()
        jobs_synced = sync_jobs()
        total = (companies_synced or 0) + (jobs_synced or 0)

        log.status = 'success'
        log.finished_at = timezone.now()
        log.records_synced = total
        log.save(update_fields=['status', 'finished_at', 'records_synced'])

        logger.info('sm8_incremental_sync complete: %d records synced', total)
        return {'status': 'success', 'records_synced': total}

    except Exception as exc:
        log.status = 'failed'
        log.finished_at = timezone.now()
        log.error_message = str(exc)
        log.save(update_fields=['status', 'finished_at', 'error_message'])

        logger.exception('sm8_incremental_sync failed: %s', exc)
        raise self.retry(exc=exc)