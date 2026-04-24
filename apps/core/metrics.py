"""
Dashboard KPI calculations.
All metrics computed from jobs_cache — the read-only SM8 mirror.
Single function returns everything the dashboard needs in one DB round-trip.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Q
from django.utils import timezone

COMPLETED = ['Completed', 'Invoice Sent', 'Paid']
AWAITING = ['Invoice Sent']
WON = ['Work Order', 'Completed', 'Invoice Sent', 'Paid']


# ── Standalone helper — defined at module level ───────────────────────────────

def get_quote_pipeline_chart(months: int = 6) -> list:
    """
    Returns monthly quote pipeline data for the bar chart.

    Each entry covers one calendar month going back N months from today.
    Used by the frontend Quote Pipeline bar chart (Accepted / Declined / Sent).

    Format:
    [
        {
            "month": "Oct",
            "year": 2025,
            "month_key": "2025-10",
            "sent": 12,
            "accepted": 7,
            "declined": 1
        },
        ...
    ]
    """
    from apps.customers.models import JobCache

    WON_STATUSES = ['Work Order', 'Completed', 'Invoice Sent', 'Paid']

    today = date.today()
    result = []

    for i in range(months - 1, -1, -1):
        # Pure Python month arithmetic — no external dependencies
        raw_month = today.month - i
        year = today.year

        # Normalise negative months
        while raw_month <= 0:
            raw_month += 12
            year -= 1

        month_start = date(year, raw_month, 1)

        # First day of the following month
        if raw_month == 12:
            month_end = date(year + 1, 1, 1)
        else:
            month_end = date(year, raw_month + 1, 1)

        # Quotes sent — any job with a quote_date in this month
        sent = JobCache.objects.filter(
            quote_date__gte=month_start,
            quote_date__lt=month_end,
        ).count()

        # Accepted — quote converted to a won status in this month
        accepted = JobCache.objects.filter(
            quote_date__gte=month_start,
            quote_date__lt=month_end,
            status__in=WON_STATUSES,
        ).count()

        # Declined / lapsed — cancelled in this month
        declined = JobCache.objects.filter(
            quote_date__gte=month_start,
            quote_date__lt=month_end,
            status='Cancelled',
        ).count()

        result.append({
            'month': month_start.strftime('%b'),         # "Oct"
            'year': month_start.year,                    # 2025
            'month_key': month_start.strftime('%Y-%m'),  # "2025-10"
            'sent': sent,
            'accepted': accepted,
            'declined': declined,
        })

    return result


# ── Main metrics function ─────────────────────────────────────────────────────

def get_dashboard_metrics(period_days: int = 30) -> dict:
    """
    Return the full dashboard payload for the given period window.

    Single function — one call returns everything:
      - 9 KPI cards with deltas vs previous period
      - Alert strip (4 cards: enquiries, quotes, invoices, HeatShield)
      - Quote funnel chart data (period totals)
      - Quote pipeline monthly chart (last 6 months, bar chart)
      - Enquiry quality donut data
      - Last 8 enquiries
      - Last 12 activity feed entries
      - Last 15 SM8 jobs snapshot
      - Last sync info
    """
    from apps.customers.models import Customer, JobCache
    from apps.enquiries.models import Enquiry
    from apps.heatshield.models import HeatshieldMember
    from apps.core.models import AuditLog, SyncLog

    today = date.today()
    start = today - timedelta(days=period_days)
    prev_start = start - timedelta(days=period_days)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def jobs_in(start_date, end_date=None, statuses=COMPLETED):
        qs = JobCache.objects.filter(
            status__in=statuses,
            completed_date__gte=start_date,
        )
        if end_date:
            qs = qs.filter(completed_date__lt=end_date)
        return qs

    def delta_pct(current, previous):
        """Percentage change vs previous period. Returns None if no previous data."""
        if not previous:
            return None
        return round(((current - previous) / previous) * 100, 1)

    # ── KPI: revenue + jobs ───────────────────────────────────────────────────
    rev_agg = jobs_in(start).aggregate(
        total=Sum('total_invoice_amount'),
        materials=Sum('materials_cost'),
        count=Count('id'),
    )
    prev_rev_agg = jobs_in(prev_start, start).aggregate(
        total=Sum('total_invoice_amount'),
        count=Count('id'),
    )

    revenue = rev_agg['total'] or Decimal('0')
    prev_revenue = prev_rev_agg['total'] or Decimal('0')
    materials = rev_agg['materials'] or Decimal('0')
    jobs_completed = rev_agg['count'] or 0
    prev_jobs = prev_rev_agg['count'] or 0

    # ── KPI: awaiting payment ─────────────────────────────────────────────────
    awaiting = (
        JobCache.objects.filter(status='Invoice Sent')
        .aggregate(total=Sum('total_invoice_amount'))['total']
        or Decimal('0')
    )

    # ── KPI: quotes (current period) ─────────────────────────────────────────
    quotes_sent = JobCache.objects.filter(
        status='Quote',
        quote_date__gte=start,
    ).count()

    quotes_accepted = JobCache.objects.filter(
        status__in=WON,
        quote_date__gte=start,
    ).count()

    quotes_declined = JobCache.objects.filter(
        status='Cancelled',
        quote_date__gte=start,
    ).count()

    # ── KPI: quotes (previous period — for deltas) ────────────────────────────
    prev_quotes_sent = JobCache.objects.filter(
        status='Quote',
        quote_date__gte=prev_start,
        quote_date__lt=start,
    ).count()

    prev_quotes_accepted = JobCache.objects.filter(
        status__in=WON,
        quote_date__gte=prev_start,
        quote_date__lt=start,
    ).count()

    prev_quotes_declined = JobCache.objects.filter(
        status='Cancelled',
        quote_date__gte=prev_start,
        quote_date__lt=start,
    ).count()

    # ── Computed rates ────────────────────────────────────────────────────────
    total_quoted = quotes_sent + quotes_accepted + quotes_declined
    quote_win_rate = (
        round((quotes_accepted / total_quoted) * 100, 1)
        if total_quoted > 0 else 0.0
    )

    # ── KPI: HeatShield ───────────────────────────────────────────────────────
    hs_active = HeatshieldMember.objects.filter(status='active').count()
    hs_mrr = (
        HeatshieldMember.objects.filter(status='active')
        .aggregate(mrr=Sum('monthly_amount'))['mrr']
        or Decimal('0')
    )

    # ── KPI: enquiries ────────────────────────────────────────────────────────
    enquiries_mtd = Enquiry.objects.filter(
        created_at__date__gte=start,
    ).count()
    prev_enquiries_mtd = Enquiry.objects.filter(
        created_at__date__gte=prev_start,
        created_at__date__lt=start,
    ).count()

    # ── Computed: avg job value + gross margin ────────────────────────────────
    avg_job_value = (
        round(revenue / jobs_completed, 2)
        if jobs_completed > 0 else Decimal('0')
    )
    gp_margin = (
        round(((revenue - materials) / revenue) * 100, 1)
        if revenue > 0 else 0.0
    )

    # ── Computed: returning customer rate ─────────────────────────────────────
    total_with_jobs = Customer.objects.filter(job_count__gte=1).count()
    returning = Customer.objects.filter(job_count__gte=2).count()
    returning_rate = (
        round((returning / total_with_jobs) * 100, 1)
        if total_with_jobs > 0 else 0.0
    )

    # ── Alerts: raw counts ────────────────────────────────────────────────────
    unreviewed_enquiries = Enquiry.objects.filter(
        status__in=['PENDING', 'NEEDS_MANUAL_REVIEW']
    ).count()

    lapsed_quotes = JobCache.objects.filter(
        status='Quote',
        quote_date__lte=today - timedelta(days=30),
    ).count()

    overdue_invoices_qs = JobCache.objects.filter(
        status='Invoice Sent',
        completed_date__lte=today - timedelta(days=14),
    )
    overdue_invoices_count = overdue_invoices_qs.count()
    overdue_invoices_value = (
        overdue_invoices_qs.aggregate(total=Sum('total_invoice_amount'))['total']
        or Decimal('0')
    )

    hs_service_due = HeatshieldMember.objects.filter(
        status='active',
        renewal_date__lte=today + timedelta(days=60),
    ).count()

    # Check if any HeatShield reminder campaign drafts exist
    try:
        from apps.campaigns.models import Campaign
        hs_reminder_drafts = Campaign.objects.filter(
            status='draft',
            automation_trigger__icontains='heatshield',
        ).count()
    except Exception:
        hs_reminder_drafts = 0

    # Total active alert count — used for nav badge
    total_alerts = sum([
        1 if unreviewed_enquiries > 0 else 0,
        1 if lapsed_quotes > 0 else 0,
        1 if overdue_invoices_count > 0 else 0,
        1 if hs_service_due > 0 else 0,
    ])

    # ── Chart: quote funnel (period totals) ───────────────────────────────────
    quote_funnel = {
        'sent': quotes_sent,
        'accepted': quotes_accepted,
        'declined': quotes_declined,
    }

    # ── Chart: quote pipeline monthly (last 6 months bar chart) ──────────────
    quote_pipeline_monthly = get_quote_pipeline_chart(months=6)

    # ── Chart: enquiry quality donut ──────────────────────────────────────────
    enquiry_quality = {
        'qualified': Enquiry.objects.filter(
            created_at__date__gte=start,
            status='APPROVED',
        ).count(),
        'rejected': Enquiry.objects.filter(
            created_at__date__gte=start,
            status='REJECTED',
        ).count(),
        'pending': Enquiry.objects.filter(
            created_at__date__gte=start,
            status__in=['PENDING', 'NEEDS_MANUAL_REVIEW'],
        ).count(),
        'total': enquiries_mtd,
    }

    # ── Table: recent enquiries (last 8) ──────────────────────────────────────
    recent_enquiries = list(
        Enquiry.objects.select_related('customer')
        .order_by('-created_at')[:8]
        .values(
            'id', 'customer_name', 'customer_postcode',
            'job_type', 'urgency', 'ai_score',
            'ai_recommendation', 'status', 'created_at',
        )
    )
    for eq in recent_enquiries:
        eq['id'] = str(eq['id'])
        eq['created_at'] = eq['created_at'].isoformat()

    # ── Feed: activity log (last 12) ──────────────────────────────────────────
    activity_entries = list(
        AuditLog.objects.select_related('actor_user')
        .order_by('-created_at')[:12]
    )
    activity_feed = [
        {
            'id': str(e.id),
            'action': e.action,
            'entity_type': e.entity_type,
            'entity_id': str(e.entity_id) if e.entity_id else None,
            'actor': (
                e.actor_user.get_full_name() or e.actor_user.username
                if e.actor_user else 'System'
            ),
            'metadata': e.metadata,
            'created_at': e.created_at.isoformat(),
        }
        for e in activity_entries
    ]

    # ── Table: SM8 jobs snapshot (last 15) ────────────────────────────────────
    recent_jobs = list(
        JobCache.objects.select_related('customer')
        .order_by('-created_date')[:15]
        .values(
            'id', 'sm8_job_uuid', 'status',
            'job_type', 'total_invoice_amount',
            'created_date', 'completed_date',
            'customer__name','engineer_name',
        )
    )
    for job in recent_jobs:
        job['id'] = str(job['id'])
        job['sm8_job_uuid'] = str(job['sm8_job_uuid'])
        if job['created_date']:
            job['created_date'] = job['created_date'].isoformat()
        if job['completed_date']:
            job['completed_date'] = job['completed_date'].isoformat()
        job['total_invoice_amount'] = float(job['total_invoice_amount'] or 0)

    # ── System: last sync info ────────────────────────────────────────────────
    last_sync = (
        SyncLog.objects.filter(status='success')
        .order_by('-finished_at')
        .first()
    )
    sync_info = {
        'last_synced_at': last_sync.finished_at.isoformat() if last_sync else None,
        'sync_type': last_sync.sync_type if last_sync else None,
        'records_synced': last_sync.records_synced if last_sync else 0,
        'status': last_sync.status if last_sync else 'never_run',
    }

    # ── Assemble and return ───────────────────────────────────────────────────
    return {
        'period_days': period_days,

        # ── 9 KPI cards ───────────────────────────────────────────────────────
        'kpis': {
            'revenue_paid': {
                'value': float(revenue),
                'delta_pct': delta_pct(float(revenue), float(prev_revenue)),
                'label': 'Revenue Paid',
            },
            'awaiting_payment': {
                'value': float(awaiting),
                'delta_pct': None,
                'label': 'Awaiting Payment',
                'alert': float(awaiting) > 5000,
            },
            'quotes_sent': {
                'value': quotes_sent,
                'delta_pct': delta_pct(quotes_sent, prev_quotes_sent),
                'label': 'Quotes Sent',
            },
            'quotes_accepted': {
                'value': quotes_accepted,
                'delta_pct': delta_pct(quotes_accepted, prev_quotes_accepted),
                'label': 'Quotes Accepted',
                'conversion_rate': quote_win_rate,
            },
            'quotes_declined': {
                'value': quotes_declined,
                'delta_pct': delta_pct(quotes_declined, prev_quotes_declined),
                'label': 'Quotes Declined / Lapsed',
            },
            'jobs_completed': {
                'value': jobs_completed,
                'delta_pct': delta_pct(jobs_completed, prev_jobs),
                'label': 'Jobs Completed',
            },
            'avg_job_value': {
                'value': float(avg_job_value),
                'delta_pct': None,
                'label': 'Avg Job Value',
            },
            'heatshield_active': {
                'value': hs_active,
                'mrr': float(hs_mrr),
                'label': 'HeatShield Members',
            },
            'enquiries_received': {
                'value': enquiries_mtd,
                'delta_pct': delta_pct(enquiries_mtd, prev_enquiries_mtd),
                'label': 'New Enquiries',
            },
        },

        # ── Computed summary metrics ───────────────────────────────────────────
        'gross_profit_margin': gp_margin,
        'quote_win_rate': quote_win_rate,
        'returning_customer_rate': returning_rate,

        # ── Alert strip ───────────────────────────────────────────────────────
        # Each alert card: show=False means hide this card entirely.
        # The entire strip should be hidden when total_alerts == 0.
        # action_external=True means open in new tab (used for SM8 link).
        'alerts': {
            'total_alerts': total_alerts,

            'unreviewed_enquiries': {
                'count': unreviewed_enquiries,
                'show': unreviewed_enquiries > 0,
                'label': (
                    str(unreviewed_enquiries) + ' unreviewed '
                    + ('enquiry' if unreviewed_enquiries == 1 else 'enquiries')
                ),
                'sub_label': None,
                'action_label': 'Review',
                'action_url': '/enquiries?status=PENDING',
                'action_external': False,
                'severity': 'warning',
            },
            'lapsed_quotes': {
                'count': lapsed_quotes,
                'show': lapsed_quotes > 0,
                'label': (
                    str(lapsed_quotes) + ' '
                    + ('quote' if lapsed_quotes == 1 else 'quotes')
                    + ' gone cold'
                ),
                'sub_label': None,
                'action_label': 'Follow up',
                'action_url': '/enquiries?filter=lapsed_quotes',
                'action_external': False,
                'severity': 'warning',
            },
            'overdue_invoices': {
                'count': overdue_invoices_count,
                'show': overdue_invoices_count > 0,
                'label': (
                    str(overdue_invoices_count) + ' overdue '
                    + ('invoice' if overdue_invoices_count == 1 else 'invoices')
                ),
                'sub_label': (
                    '\u00a3{:,.0f} outstanding'.format(float(overdue_invoices_value))
                    if overdue_invoices_count > 0 else None
                ),
                'action_label': 'Chase',
                'action_url': 'https://go.servicem8.com',
                'action_external': True,
                'severity': 'warning',
            },
            'heatshield_service_due': {
                'count': hs_service_due,
                'show': hs_service_due > 0,
                'label': (
                    str(hs_service_due) + ' HeatShield '
                    + ('service' if hs_service_due == 1 else 'services')
                    + ' due'
                ),
                'sub_label': (
                    'Reminder drafts ready to approve'
                    if hs_reminder_drafts > 0 else None
                ),
                'action_label': 'Book',
                'action_url': '/heatshield?status=active&expiring_days=60',
                'action_external': False,
                'severity': 'warning',
            },

            # Raw counts kept for gate checks and backwards compatibility
            '_raw': {
                'unreviewed_enquiries': unreviewed_enquiries,
                'lapsed_quotes': lapsed_quotes,
                'overdue_invoices_count': overdue_invoices_count,
                'overdue_invoices_value': float(overdue_invoices_value),
                'heatshield_service_due': hs_service_due,
            },
        },

        # ── Chart data ────────────────────────────────────────────────────────
        'quote_funnel': quote_funnel,
        'quote_pipeline_monthly': quote_pipeline_monthly,
        'enquiry_quality': enquiry_quality,

        # ── Table data ────────────────────────────────────────────────────────
        'recent_enquiries': recent_enquiries,
        'activity_feed': activity_feed,
        'recent_jobs': recent_jobs,

        # ── System info ───────────────────────────────────────────────────────
        'sync_info': sync_info,
    }