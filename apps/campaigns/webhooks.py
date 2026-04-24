"""
Resend webhook handler.
Ingests email events: delivered, opened, clicked, bounced,
spam_complaint, unsubscribed.

Signature verification uses the Svix library.
Idempotency guaranteed by the unique constraint on
(resend_email_id, event_type) in CampaignEvent.
"""
import json
import logging

from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

# Map Resend event types to our CampaignEvent.EventType choices
RESEND_EVENT_MAP = {
    'email.sent': 'sent',
    'email.delivered': 'delivered',
    'email.opened': 'opened',
    'email.clicked': 'clicked',
    'email.bounced': 'bounced',
    'email.spam_complaint': 'spam_complaint',
    'email.unsubscribed': 'unsubscribed',
}


class ResendWebhookView(APIView):
    """
    POST /webhooks/resend/
    Receives email events from Resend.
    Always returns 200 — Resend retries on any other status.
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        # ── Signature verification ────────────────────────────────────────────
        webhook_secret = getattr(settings, 'RESEND_WEBHOOK_SECRET', '')
        if webhook_secret:
            verified = self._verify_signature(request, webhook_secret)
            if not verified:
                logger.warning('Resend webhook: invalid signature')
                # Return 200 anyway — don't reveal verification status
                return Response({'ok': True})

        # ── Parse payload ─────────────────────────────────────────────────────
        try:
            payload = request.data
            event_type_raw = payload.get('type', '')
            event_type = RESEND_EVENT_MAP.get(event_type_raw)
            data = payload.get('data', {})
            resend_email_id = data.get('email_id', '')
        except Exception as exc:
            logger.warning('Resend webhook: malformed payload: %s', exc)
            return Response({'ok': True})

        if not event_type or not resend_email_id:
            logger.debug(
                'Resend webhook: unmapped event type %s — ignoring',
                event_type_raw,
            )
            return Response({'ok': True})

        try:
            self._ingest_event(
                event_type=event_type,
                resend_email_id=resend_email_id,
                payload=payload,
                data=data,
            )
        except Exception as exc:
            logger.exception('Resend webhook processing error: %s', exc)

        return Response({'ok': True})

    def _ingest_event(
        self,
        event_type: str,
        resend_email_id: str,
        payload: dict,
        data: dict,
    ) -> None:
        from apps.campaigns.models import CampaignEvent
        from apps.core.models import SuppressionListEntry

        # Try to find the campaign from the email tags
        tags = data.get('tags', {})
        campaign_id = tags.get('campaign_id')
        campaign = None

        if campaign_id:
            from apps.campaigns.models import Campaign
            try:
                campaign = Campaign.objects.get(id=campaign_id)
            except (Campaign.DoesNotExist, Exception):
                pass

        if not campaign:
            logger.debug(
                'Resend webhook: no campaign found for email %s — skipping',
                resend_email_id,
            )
            return

        # Find customer by email
        to_email = data.get('to', [None])[0] if data.get('to') else None
        customer = None
        if to_email:
            from apps.customers.models import Customer
            customer = Customer.objects.filter(email=to_email).first()

        # Create the event record (idempotent via unique constraint)
        try:
            event, created = CampaignEvent.objects.get_or_create(
                resend_email_id=resend_email_id,
                event_type=event_type,
                defaults={
                    'campaign': campaign,
                    'customer': customer,
                    'link_url': data.get('click', {}).get('link', ''),
                    'metadata': payload,
                    'occurred_at': timezone.now(),
                },
            )

            if not created:
                logger.debug(
                    'Resend webhook: duplicate event %s/%s — ignored',
                    resend_email_id, event_type,
                )
                return

            logger.info(
                'Resend event ingested: %s for campaign %s',
                event_type, campaign.name,
            )

        except Exception as exc:
            logger.warning(
                'Resend webhook: failed to create event: %s', exc
            )
            return

        # ── Side effects per event type ───────────────────────────────────────

        if event_type == 'unsubscribed' and to_email:
            SuppressionListEntry.objects.get_or_create(
                email=to_email,
                defaults={
                    'reason': 'unsubscribe',
                    'source_campaign_id': campaign.id,
                },
            )
            if customer:
                customer.email_opt_out = True
                customer.unsubscribed_at = timezone.now()
                customer.save(update_fields=[
                    'email_opt_out', 'unsubscribed_at', 'updated_at'
                ])
            logger.info('Customer unsubscribed: %s', to_email)

        if event_type == 'bounced' and to_email:
            SuppressionListEntry.objects.get_or_create(
                email=to_email,
                defaults={
                    'reason': 'bounce',
                    'source_campaign_id': campaign.id,
                },
            )

        if event_type == 'opened' and customer:
            # Check for 30-day attribution window
            from apps.campaigns.attribution import check_attribution
            check_attribution(campaign, customer, event)

        # Update campaign roll-up stats
        from apps.campaigns.tasks import _update_campaign_totals
        _update_campaign_totals(str(campaign.id))

    def _verify_signature(self, request: Request, secret: str) -> bool:
        """Verify Resend webhook signature using Svix."""
        try:
            from svix.webhooks import Webhook
            wh = Webhook(secret)
            wh.verify(
                request.body,
                {
                    'svix-id': request.headers.get('svix-id', ''),
                    'svix-timestamp': request.headers.get('svix-timestamp', ''),
                    'svix-signature': request.headers.get('svix-signature', ''),
                },
            )
            return True
        except Exception as exc:
            logger.warning('Svix verification failed: %s', exc)
            return False


class UnsubscribeView(APIView):
    """
    GET /webhooks/unsubscribe/
    Handles unsubscribe link clicks from email footers.
    Always returns 200 — never show an error to an unsubscribing customer.
    """
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        email = request.query_params.get('email', '').strip().lower()
        if email:
            from apps.core.models import SuppressionListEntry
            from apps.customers.models import Customer

            SuppressionListEntry.objects.get_or_create(
                email=email,
                defaults={'reason': 'unsubscribe'},
            )

            customer = Customer.objects.filter(email=email).first()
            if customer and not customer.email_opt_out:
                customer.email_opt_out = True
                customer.unsubscribed_at = timezone.now()
                customer.save(update_fields=[
                    'email_opt_out', 'unsubscribed_at', 'updated_at'
                ])
                logger.info('Unsubscribed via link: %s', email)

        return Response({
            'message': 'You have been unsubscribed successfully.'
        })