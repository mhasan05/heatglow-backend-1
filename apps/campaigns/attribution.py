"""
Campaign revenue attribution.

When a customer opens a campaign email and then books a job within
30 days, we attribute that revenue to the campaign.

Attribution is created by the Resend webhook handler when it
receives an 'opened' event.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

ATTRIBUTION_WINDOW_DAYS = 30


def check_attribution(campaign, customer, open_event) -> None:
    """
    Check if the customer has any jobs booked within 30 days
    of the email open event. If so, create attribution records.

    Called from the Resend webhook handler on every 'opened' event.
    """
    from apps.customers.models import JobCache
    from apps.campaigns.models import CampaignAttribution, Campaign

    window_start = open_event.occurred_at
    window_end = window_start + timedelta(days=ATTRIBUTION_WINDOW_DAYS)

    # Find jobs created within the attribution window
    recent_jobs = JobCache.objects.filter(
        customer=customer,
        status__in=['Completed', 'Invoice Sent', 'Paid', 'Work Order'],
    ).filter(
        created_date__gte=window_start.date(),
        created_date__lte=window_end.date(),
    )

    for job in recent_jobs:
        # Avoid double-attribution
        already_attributed = CampaignAttribution.objects.filter(
            campaign=campaign,
            customer=customer,
            job=job,
        ).exists()

        if already_attributed:
            continue

        attribution = CampaignAttribution.objects.create(
            campaign=campaign,
            customer=customer,
            job=job,
            open_event=open_event,
            revenue=job.total_invoice_amount,
        )

        # Update campaign attributed revenue total
        Campaign.objects.filter(id=campaign.id).update(
            attributed_revenue=(
                CampaignAttribution.objects.filter(
                    campaign=campaign
                ).aggregate(
                    total=__import__(
                        'django.db.models',
                        fromlist=['Sum']
                    ).Sum('revenue')
                )['total'] or 0
            )
        )

        logger.info(
            'Attribution created: campaign %s → customer %s → job %s (£%s)',
            campaign.name, customer.name,
            job.id, job.total_invoice_amount,
        )


def run_attribution_for_campaign(campaign_id: str) -> dict:
    """
    Retroactively run attribution for a campaign.
    Checks all customers who opened the campaign against jobs
    booked within the attribution window.
    Called manually or as a scheduled task.
    """
    from apps.campaigns.models import Campaign, CampaignEvent

    try:
        campaign = Campaign.objects.get(id=campaign_id)
    except Campaign.DoesNotExist:
        logger.error('Attribution: campaign %s not found', campaign_id)
        return {'error': 'Campaign not found'}

    open_events = CampaignEvent.objects.filter(
        campaign=campaign,
        event_type='opened',
        customer__isnull=False,
    ).select_related('customer')

    attributed = 0
    for event in open_events:
        check_attribution(campaign, event.customer, event)
        attributed += 1

    logger.info(
        'Retroactive attribution for %s: checked %d open events',
        campaign.name, attributed,
    )

    return {
        'campaign_id': campaign_id,
        'open_events_checked': attributed,
    }