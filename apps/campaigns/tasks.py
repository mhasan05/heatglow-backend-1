"""
Campaign send tasks.

Two tasks:
  send_campaign        — resolves recipients, creates batches, dispatches
  send_campaign_batch  — sends one batch of up to 100 emails via Resend
"""
import logging
import time

from celery import shared_task

logger = logging.getLogger(__name__)


# ── Campaign send ─────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    name='campaigns.send_campaign',
)
def send_campaign(self, campaign_id: str):
    """
    Main campaign send task.

    Steps:
      1. Resolve recipient list from segment_filters
      2. Chunk into batches of 100
      3. Create CampaignBatch records
      4. Dispatch each batch to send_campaign_batch
    """
    from datetime import date, timedelta
    from django.utils import timezone
    from apps.campaigns.models import Campaign, CampaignBatch
    from apps.campaigns.segments import build_segment_queryset

    try:
        campaign = Campaign.objects.get(id=campaign_id)
    except Campaign.DoesNotExist:
        logger.error('send_campaign: campaign %s not found', campaign_id)
        return

    logger.info('Starting campaign send: %s', campaign.name)

    try:
        # ── Resolve recipients ────────────────────────────────────────────────
        qs = build_segment_queryset(campaign.segment_filters or [])
        customer_ids = list(qs.values_list('id', flat=True))
        total = len(customer_ids)

        if total == 0:
            logger.warning(
                'Campaign %s has no recipients — aborting', campaign_id
            )
            campaign.status = Campaign.Status.FAILED
            campaign.save(update_fields=['status', 'updated_at'])
            return

        logger.info(
            'Campaign %s: %d recipients, %d batches',
            campaign.name, total, (total // 100) + 1,
        )

        # ── Create batches ────────────────────────────────────────────────────
        batch_size = 100
        today = date.today()
        batches_created = []

        for i, chunk_start in enumerate(range(0, total, batch_size)):
            chunk_ids = customer_ids[chunk_start:chunk_start + batch_size]

            # Spread-over-days: distribute batches across N days
            if (
                campaign.send_mode == Campaign.SendMode.SPREAD
                and campaign.spread_days
                and campaign.spread_days > 0
            ):
                total_batches = max((total // batch_size), 1)
                day_offset = (i * campaign.spread_days) // total_batches
                scheduled_date = today + timedelta(days=day_offset)
            else:
                scheduled_date = today

            batch = CampaignBatch.objects.create(
                campaign=campaign,
                batch_number=i + 1,
                customer_ids=[str(cid) for cid in chunk_ids],
                scheduled_for=scheduled_date,
                status=CampaignBatch.Status.PENDING,
            )
            batches_created.append(str(batch.id))

        # ── Update recipient count ────────────────────────────────────────────
        campaign.recipient_count = total
        campaign.save(update_fields=['recipient_count', 'updated_at'])

        # ── Dispatch batches ──────────────────────────────────────────────────
        for batch_id in batches_created:
            send_campaign_batch.delay(campaign_id, batch_id)

        logger.info(
            'Campaign %s: %d batches dispatched',
            campaign.name, len(batches_created),
        )

        return {
            'campaign_id': campaign_id,
            'total_recipients': total,
            'batches': len(batches_created),
        }

    except Exception as exc:
        campaign.status = Campaign.Status.FAILED
        campaign.save(update_fields=['status', 'updated_at'])
        logger.exception('Campaign send failed: %s', exc)
        raise self.retry(exc=exc)


# ── Batch send ────────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name='campaigns.send_campaign_batch',
)
def send_campaign_batch(self, campaign_id: str, batch_id: str):
    """
    Send a single campaign batch of up to 100 emails.

    Steps:
      1. Load campaign + batch records
      2. Resolve customers (excluding opt-outs and suppressed emails)
      3. Apply personalisation tokens per customer
      4. Send each email via Resend
      5. Record a CampaignEvent for every sent email
      6. Update batch status + campaign roll-up stats
    """
    from django.utils import timezone
    from apps.campaigns.models import Campaign, CampaignBatch, CampaignEvent
    from apps.customers.models import Customer
    from apps.campaigns.segments import apply_personalisation_tokens
    from apps.integrations.resend_client import send_email
    from apps.core.models import SuppressionListEntry

    # ── Load records ──────────────────────────────────────────────────────────
    try:
        campaign = Campaign.objects.get(id=campaign_id)
    except Campaign.DoesNotExist:
        logger.error('send_campaign_batch: campaign %s not found', campaign_id)
        return

    try:
        batch = CampaignBatch.objects.get(id=batch_id)
    except CampaignBatch.DoesNotExist:
        logger.error('send_campaign_batch: batch %s not found', batch_id)
        return

    # Skip if already processed (idempotency guard)
    if batch.status != CampaignBatch.Status.PENDING:
        logger.info(
            'Batch %s already processed (status=%s) — skipping',
            batch_id, batch.status,
        )
        return

    batch.status = CampaignBatch.Status.SENDING
    batch.save(update_fields=['status'])

    # ── Load suppressed emails ────────────────────────────────────────────────
    suppressed_emails = set(
        SuppressionListEntry.objects.values_list('email', flat=True)
    )

    # ── Load customers in this batch ──────────────────────────────────────────
    customers = list(
        Customer.objects.filter(
            id__in=batch.customer_ids,
            email_opt_out=False,
        ).exclude(
            email__isnull=True,
        ).exclude(
            email='',
        )
    )

    # Remove suppressed addresses
    customers = [c for c in customers if c.email not in suppressed_emails]

    if not customers:
        logger.info(
            'Batch %s: no eligible recipients after suppression filter',
            batch_id,
        )
        batch.status = CampaignBatch.Status.SENT
        batch.send_count = 0
        batch.sent_at = timezone.now()
        batch.save(update_fields=['status', 'send_count', 'sent_at'])
        return

    # ── Send emails ───────────────────────────────────────────────────────────
    sent_count = 0
    events_to_create = []

    unsubscribe_base = 'https://app.heatglow.co.uk/webhooks/unsubscribe/?email='

    for customer in customers:
        try:
            # Apply personalisation
            personalised_subject = apply_personalisation_tokens(
                campaign.subject, customer
            )
            personalised_body = apply_personalisation_tokens(
                campaign.body_html, customer
            )

            # Append unsubscribe footer
            unsubscribe_url = unsubscribe_base + (customer.email or '')
            full_html = (
                personalised_body
                + (
                    '\n<p style="color:#9ca3af;font-size:11px;'
                    'text-align:center;margin-top:32px;">'
                    f'<a href="{unsubscribe_url}" style="color:#9ca3af;">'
                    'Unsubscribe</a></p>'
                )
            )

            # Build from address
            from_address = (
                campaign.from_name + ' <' + campaign.from_email + '>'
            )

            result = send_email(
                to=customer.email,
                subject=personalised_subject,
                html=full_html,
                from_address=from_address,
                reply_to=campaign.reply_to or None,
                tags=[
                    {
                        'name': 'campaign_id',
                        'value': str(campaign_id)[:35],
                    },
                    {
                        'name': 'batch_id',
                        'value': str(batch_id)[:35],
                    },
                ],
            )

            if result.success:
                events_to_create.append(
                    CampaignEvent(
                        campaign=campaign,
                        customer=customer,
                        event_type=CampaignEvent.EventType.SENT,
                        resend_email_id=result.email_id or '',
                        occurred_at=timezone.now(),
                        metadata={
                            'batch_id': batch_id,
                            'campaign_id': campaign_id,
                        },
                    )
                )
                sent_count += 1
                logger.debug(
                    'Sent to %s (email_id=%s)',
                    customer.email, result.email_id,
                )
            else:
                logger.warning(
                    'Resend rejected email to %s: %s',
                    customer.email, result.error,
                )

        except Exception as exc:
            logger.warning(
                'Failed to send to customer %s: %s',
                customer.id, exc,
            )
            continue

        # Small delay — avoids flooding Resend (100 emails/batch * 0.05s = 5s max)
        time.sleep(0.05)

    # ── Bulk create CampaignEvent records ─────────────────────────────────────
    if events_to_create:
        CampaignEvent.objects.bulk_create(
            events_to_create,
            ignore_conflicts=True,  # idempotency: skip duplicates silently
        )

    # ── Update batch record ───────────────────────────────────────────────────
    batch.status = CampaignBatch.Status.SENT
    batch.send_count = sent_count
    batch.sent_at = timezone.now()
    batch.save(update_fields=['status', 'send_count', 'sent_at'])

    # ── Update campaign roll-up stats ─────────────────────────────────────────
    _update_campaign_totals(campaign_id)

    logger.info(
        'Batch %s complete: %d/%d emails sent',
        batch_id, sent_count, len(customers),
    )

    return {
        'batch_id': batch_id,
        'sent': sent_count,
        'total_eligible': len(customers),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _update_campaign_totals(campaign_id: str) -> None:
    """
    Recalculate roll-up stats on the Campaign record
    from its CampaignEvent rows.

    Called after every batch completes and after every
    Resend webhook event is ingested.
    """
    from django.db.models import Count
    from apps.campaigns.models import Campaign, CampaignEvent

    counts = (
        CampaignEvent.objects
        .filter(campaign_id=campaign_id)
        .values('event_type')
        .annotate(count=Count('id'))
    )

    totals = {row['event_type']: row['count'] for row in counts}

    Campaign.objects.filter(id=campaign_id).update(
        total_sent=totals.get('sent', 0),
        total_delivered=totals.get('delivered', 0),
        total_opened=totals.get('opened', 0),
        total_clicked=totals.get('clicked', 0),
        total_bounced=totals.get('bounced', 0),
    )

    logger.debug(
        'Campaign %s totals updated: %s', campaign_id, totals
    )