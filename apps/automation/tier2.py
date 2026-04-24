"""
Tier 2 automation draft generators.

These run daily and create Campaign draft records for Gareth to approve.
They do NOT send emails directly — Gareth sees the draft in the
Campaign Queue and approves with one click.

Six automations:
  1. Lapsed quote follow-up (quote > 30 days, no response)
  2. Inactive customer re-engagement (no job in 12+ months)
  3. One-time customer upsell (exactly 1 job, 6+ months ago)
  4. Annual service reminder (last boiler service 11+ months ago)
  5. HeatShield lapsed renewal (lapsed membership)
  6. Quote no-response chase (quote sent, no reply in 7 days)
"""
import logging
from datetime import date, timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


def generate_lapsed_quote_followup() -> dict:
    """
    Customers with a Quote status job older than 30 days
    and no subsequent Work Order or Completed job.
    """
    from apps.customers.models import Customer, JobCache
    from apps.campaigns.models import Campaign

    cutoff = date.today() - timedelta(days=30)

    customers_with_old_quotes = Customer.objects.filter(
        jobs__status='Quote',
        jobs__quote_date__lte=cutoff,
        email_opt_out=False,
    ).exclude(
        jobs__status__in=['Work Order', 'Completed', 'Paid', 'Invoice Sent']
    ).exclude(email__isnull=True).distinct()

    count = customers_with_old_quotes.count()
    if count == 0:
        return {'automation': 'lapsed_quote_followup', 'skipped': True, 'reason': 'No matching customers'}

    filters = [
        {'field': 'segment', 'value': 'lapsed'},
    ]

    return _create_tier2_draft(
        name='Lapsed Quote Follow-up',
        subject='Still interested? Your HeatGlow quote is waiting',
        body_html=_lapsed_quote_body(),
        automation_trigger='lapsed_quote_30d',
        segment_filters=filters,
        recipient_count=count,
    )


def generate_inactive_reengagement() -> dict:
    """
    Customers with no completed job in the last 12 months.
    """
    from apps.customers.models import Customer

    cutoff = date.today() - timedelta(days=365)
    count = Customer.objects.filter(
        last_job_date__lt=cutoff,
        job_count__gte=1,
        email_opt_out=False,
    ).exclude(email__isnull=True).count()

    if count == 0:
        return {'automation': 'inactive_reengagement', 'skipped': True, 'reason': 'No matching customers'}

    return _create_tier2_draft(
        name='Inactive Customer Re-engagement',
        subject="Hi {{first_name}}, it's been a while — how's your heating?",
        body_html=_inactive_reengagement_body(),
        automation_trigger='inactive_12m',
        segment_filters=[{'field': 'segment', 'value': 'lapsed'}],
        recipient_count=count,
    )


def generate_one_time_upsell() -> dict:
    """
    Customers with exactly 1 completed job, last job 6+ months ago.
    """
    from apps.customers.models import Customer

    cutoff = date.today() - timedelta(days=180)
    count = Customer.objects.filter(
        job_count=1,
        last_job_date__lt=cutoff,
        email_opt_out=False,
    ).exclude(
        heatshield_status='active'
    ).exclude(email__isnull=True).count()

    if count == 0:
        return {'automation': 'one_time_upsell', 'skipped': True, 'reason': 'No matching customers'}

    return _create_tier2_draft(
        name='One-Time Customer — HeatShield Upsell',
        subject='Protect your boiler year-round with HeatShield',
        body_html=_one_time_upsell_body(),
        automation_trigger='one_time_upsell',
        segment_filters=[{'field': 'segment', 'value': 'one_time'}],
        recipient_count=count,
    )


def generate_annual_service_reminder() -> dict:
    """
    Customers whose last boiler service was 11+ months ago.
    """
    from apps.customers.models import Customer

    cutoff = date.today() - timedelta(days=335)
    count = Customer.objects.filter(
        last_job_date__lt=cutoff,
        last_job_type__icontains='service',
        email_opt_out=False,
    ).exclude(
        heatshield_status='active'
    ).exclude(email__isnull=True).count()

    if count == 0:
        return {'automation': 'annual_service_reminder', 'skipped': True, 'reason': 'No matching customers'}

    return _create_tier2_draft(
        name='Annual Boiler Service Reminder',
        subject="{{first_name}}, is your boiler due for its annual service?",
        body_html=_annual_service_body(),
        automation_trigger='annual_service_11m',
        segment_filters=[
            {'field': 'last_job_before', 'value': cutoff.isoformat()},
        ],
        recipient_count=count,
    )


def generate_heatshield_lapsed_renewal() -> dict:
    """
    HeatShield members whose membership has lapsed.
    """
    from apps.heatshield.models import HeatshieldMember

    count = HeatshieldMember.objects.filter(
        status='lapsed',
        customer__email_opt_out=False,
    ).exclude(customer__email__isnull=True).count()

    if count == 0:
        return {'automation': 'heatshield_lapsed_renewal', 'skipped': True, 'reason': 'No lapsed members'}

    return _create_tier2_draft(
        name='HeatShield Lapsed — Renewal Offer',
        subject='Renew your HeatShield plan today',
        body_html=_heatshield_lapsed_body(),
        automation_trigger='heatshield_lapsed',
        segment_filters=[{'field': 'heatshield_status', 'value': 'lapsed'}],
        recipient_count=count,
    )


def generate_quote_no_response_chase() -> dict:
    """
    Customers with a quote sent 7+ days ago and no response.
    """
    from apps.customers.models import JobCache

    cutoff = date.today() - timedelta(days=7)
    count = JobCache.objects.filter(
        status='Quote',
        quote_date__lte=cutoff,
        customer__email_opt_out=False,
    ).exclude(
        customer__email__isnull=True
    ).values('customer').distinct().count()

    if count == 0:
        return {'automation': 'quote_no_response', 'skipped': True, 'reason': 'No pending quotes'}

    return _create_tier2_draft(
        name='Quote No-Response Chase',
        subject='Following up on your HeatGlow quote',
        body_html=_quote_chase_body(),
        automation_trigger='quote_no_response_7d',
        segment_filters=[],
        recipient_count=count,
    )


# ── Shared helpers ────────────────────────────────────────────────────────────

def _create_tier2_draft(
    name: str,
    subject: str,
    body_html: str,
    automation_trigger: str,
    segment_filters: list,
    recipient_count: int,
) -> dict:
    """Create a Tier 2 Campaign draft record."""
    from apps.campaigns.models import Campaign

    # Don't create a duplicate draft if one already exists today
    existing = Campaign.objects.filter(
        automation_trigger=automation_trigger,
        status=Campaign.Status.DRAFT,
    ).first()

    if existing:
        return {
            'automation': automation_trigger,
            'skipped': True,
            'reason': 'Draft already exists',
            'campaign_id': str(existing.id),
        }

    campaign = Campaign.objects.create(
        name=name,
        subject=subject,
        body_html=body_html,
        campaign_type=Campaign.Type.AUTOMATION_TIER2,
        automation_trigger=automation_trigger,
        segment_filters=segment_filters,
        recipient_count=recipient_count,
        status=Campaign.Status.DRAFT,
        send_mode=Campaign.SendMode.IMMEDIATE,
    )

    logger.info(
        'Tier 2 draft created: %s (%d recipients)',
        name, recipient_count,
    )

    return {
        'automation': automation_trigger,
        'created': True,
        'campaign_id': str(campaign.id),
        'recipient_count': recipient_count,
    }


# ── Email body templates ──────────────────────────────────────────────────────

def _base_template(body_content: str) -> str:
    return f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:Arial,sans-serif;">
<div style="max-width:600px;margin:32px auto;background:#fff;
            border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1);">
  <div style="background:#1a56db;padding:24px 32px;">
    <h1 style="margin:0;color:#fff;font-size:20px;">HeatGlow Heating &amp; Plumbing</h1>
  </div>
  <div style="padding:32px;">
    {body_content}
    <p style="color:#374151;font-size:14px;margin-top:24px;">
      Kind regards,<br><strong>Gareth Jones</strong><br>HeatGlow Heating &amp; Plumbing
    </p>
  </div>
  <div style="padding:16px 32px;background:#f3f4f6;border-top:1px solid #e5e7eb;">
    <p style="margin:0;color:#9ca3af;font-size:11px;text-align:center;">
      HeatGlow &mdash; 66 Park Road, Whitchurch, Cardiff CF14 7BR
    </p>
  </div>
</div>
</body></html>"""


def _lapsed_quote_body() -> str:
    return _base_template("""
<p style="color:#374151;font-size:15px;">Hi {{first_name}},</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  We sent you a quote recently and wanted to follow up to see if you have any questions
  or if there is anything we can help clarify.
</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  We are happy to discuss the work in more detail or adjust the quote if needed.
  Just reply to this email or give us a call.
</p>""")


def _inactive_reengagement_body() -> str:
    return _base_template("""
<p style="color:#374151;font-size:15px;">Hi {{first_name}},</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  It has been a while since we last worked together and we just wanted to check in.
  Whether you need a boiler service, a repair, or anything else heating and plumbing
  related, we are here to help.
</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  As a previous customer you will always get our best service. Get in touch any time.
</p>""")


def _one_time_upsell_body() -> str:
    return _base_template("""
<p style="color:#374151;font-size:15px;">Hi {{first_name}},</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  Thank you for choosing HeatGlow. We wanted to let you know about our
  <strong>HeatShield maintenance plan</strong> — just £10/month for annual boiler
  servicing, priority call-outs, and peace of mind all year round.
</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  Reply to this email to find out more or to sign up today.
</p>""")


def _annual_service_body() -> str:
    return _base_template("""
<p style="color:#374151;font-size:15px;">Hi {{first_name}},</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  Your boiler is due for its annual service. Regular servicing keeps your boiler
  running efficiently, maintains your warranty, and catches small problems before
  they become expensive ones.
</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  Reply to this email to book your service. We can usually accommodate you within
  1-2 weeks.
</p>""")


def _heatshield_lapsed_body() -> str:
    return _base_template("""
<p style="color:#374151;font-size:15px;">Hi {{first_name}},</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  Your HeatShield maintenance plan has lapsed. We would love to have you back —
  renew today for just £10/month and get your annual boiler service included.
</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  Reply to this email to renew or to discuss your options.
</p>""")


def _quote_chase_body() -> str:
    return _base_template("""
<p style="color:#374151;font-size:15px;">Hi {{first_name}},</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  We sent you a quote recently and just wanted to follow up. If you have any questions
  about the work or the price, we are happy to talk it through.
</p>
<p style="color:#374151;font-size:15px;line-height:1.7;">
  Reply to this email or call us directly — we are always happy to help.
</p>""")