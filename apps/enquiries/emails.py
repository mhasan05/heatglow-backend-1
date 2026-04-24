"""
Email templates for the enquiry workflow.

Two emails:
  1. Gareth notification — sent when a new enquiry is scored
  2. Customer acknowledgement — sent to the customer on submission
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def _score_colour(score: int) -> str:
    """Return a hex colour based on the AI score."""
    if score >= 70:
        return '#059669'   # green
    elif score >= 40:
        return '#d97706'   # amber
    else:
        return '#dc2626'   # red


def _recommendation_label(recommendation: str) -> str:
    labels = {
        'APPROVE': '✓ Recommend Approve',
        'REJECT': '✗ Recommend Reject',
        'MANUAL_REVIEW': '⚠ Manual Review Required',
    }
    return labels.get(recommendation, recommendation)


def build_gareth_notification_html(enquiry, approve_url: str, reject_url: str) -> str:
    """
    Build the HTML email Gareth receives for each new enquiry.
    Includes AI score, recommendation, one-click approve/reject buttons.
    """
    score = enquiry.ai_score or 0
    score_colour = _score_colour(score)
    rec_label = _recommendation_label(enquiry.ai_recommendation or 'MANUAL_REVIEW')
    score_bar_filled = '█' * (score // 10)
    score_bar_empty = '░' * (10 - score // 10)

    urgency_colours = {
        'emergency': '#dc2626',
        'urgent': '#d97706',
        'routine': '#059669',
        'flexible': '#6b7280',
    }
    urgency_colour = urgency_colours.get(enquiry.urgency, '#6b7280')

    flags_html = ''
    if enquiry.ai_flags:
        flags_html = '<p style="color:#dc2626; font-size:13px;">⚑ Flags: ' + \
                     ', '.join(enquiry.ai_flags) + '</p>'

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#f9fafb; font-family:Arial,sans-serif;">
  <div style="max-width:600px; margin:32px auto; background:#ffffff;
              border-radius:8px; overflow:hidden;
              box-shadow:0 1px 3px rgba(0,0,0,0.1);">

    <!-- Header -->
    <div style="background:#1a56db; padding:24px 32px;">
      <h1 style="margin:0; color:#ffffff; font-size:20px;">
        New Enquiry — HeatGlow CRM
      </h1>
      <p style="margin:4px 0 0; color:#bfdbfe; font-size:13px;">
        Received {enquiry.created_at.strftime('%d %b %Y at %H:%M')}
      </p>
    </div>

    <!-- Customer details -->
    <div style="padding:24px 32px; border-bottom:1px solid #e5e7eb;">
      <h2 style="margin:0 0 16px; font-size:16px; color:#111827;">
        Customer Details
      </h2>
      <table style="width:100%; border-collapse:collapse;">
        <tr>
          <td style="padding:6px 0; color:#6b7280; font-size:14px; width:140px;">Name</td>
          <td style="padding:6px 0; color:#111827; font-size:14px; font-weight:bold;">
            {enquiry.customer_name}
          </td>
        </tr>
        <tr>
          <td style="padding:6px 0; color:#6b7280; font-size:14px;">Email</td>
          <td style="padding:6px 0; color:#111827; font-size:14px;">
            <a href="mailto:{enquiry.customer_email}" style="color:#1a56db;">
              {enquiry.customer_email}
            </a>
          </td>
        </tr>
        <tr>
          <td style="padding:6px 0; color:#6b7280; font-size:14px;">Phone</td>
          <td style="padding:6px 0; color:#111827; font-size:14px;">
            {enquiry.customer_phone or 'Not provided'}
          </td>
        </tr>
        <tr>
          <td style="padding:6px 0; color:#6b7280; font-size:14px;">Postcode</td>
          <td style="padding:6px 0; color:#111827; font-size:14px;">
            {enquiry.customer_postcode}
          </td>
        </tr>
        <tr>
          <td style="padding:6px 0; color:#6b7280; font-size:14px;">Job type</td>
          <td style="padding:6px 0; color:#111827; font-size:14px;">
            {enquiry.job_type}
          </td>
        </tr>
        <tr>
          <td style="padding:6px 0; color:#6b7280; font-size:14px;">Urgency</td>
          <td style="padding:6px 0; font-size:14px;">
            <span style="background:{urgency_colour}; color:#fff;
                         padding:2px 10px; border-radius:12px; font-size:12px;">
              {enquiry.urgency.upper()}
            </span>
          </td>
        </tr>
      </table>
    </div>

    <!-- Description -->
    <div style="padding:24px 32px; border-bottom:1px solid #e5e7eb;">
      <h2 style="margin:0 0 8px; font-size:16px; color:#111827;">Description</h2>
      <p style="margin:0; color:#374151; font-size:14px; line-height:1.6;">
        {enquiry.description}
      </p>
    </div>

    <!-- AI Score -->
    <div style="padding:24px 32px; background:#f8fafc;
                border-bottom:1px solid #e5e7eb;">
      <h2 style="margin:0 0 16px; font-size:16px; color:#111827;">
        AI Assessment
      </h2>
      <div style="display:flex; align-items:center; gap:16px; margin-bottom:12px;">
        <div style="font-size:48px; font-weight:bold; color:{score_colour};">
          {score}
        </div>
        <div>
          <div style="font-size:13px; color:#6b7280; font-family:monospace;">
            {score_bar_filled}{score_bar_empty}
          </div>
          <div style="font-size:14px; font-weight:bold; color:{score_colour}; margin-top:4px;">
            {rec_label}
          </div>
          <div style="font-size:13px; color:#6b7280;">
            Confidence: {enquiry.ai_confidence or 'Unknown'}
          </div>
        </div>
      </div>
      <p style="margin:0; color:#374151; font-size:14px; line-height:1.6;
                background:#ffffff; padding:12px; border-radius:6px;
                border-left:3px solid {score_colour};">
        {enquiry.ai_explanation or 'No explanation provided.'}
      </p>
      {flags_html}
    </div>

    <!-- Action buttons -->
    <div style="padding:24px 32px; text-align:center;">
      <p style="margin:0 0 20px; color:#374151; font-size:14px;">
        Take action on this enquiry:
      </p>
      <a href="{approve_url}"
         style="display:inline-block; background:#059669; color:#ffffff;
                padding:14px 32px; border-radius:6px; text-decoration:none;
                font-weight:bold; font-size:15px; margin-right:16px;">
        ✓ Approve
      </a>
      <a href="{reject_url}"
         style="display:inline-block; background:#dc2626; color:#ffffff;
                padding:14px 32px; border-radius:6px; text-decoration:none;
                font-weight:bold; font-size:15px;">
        ✗ Reject
      </a>
      <p style="margin:16px 0 0; color:#9ca3af; font-size:12px;">
        Or log in to
        <a href="{settings.FRONTEND_ORIGIN}" style="color:#1a56db;">
          the CRM
        </a>
        to review the full enquiry.
      </p>
    </div>

    <!-- Footer -->
    <div style="padding:16px 32px; background:#f3f4f6; border-top:1px solid #e5e7eb;">
      <p style="margin:0; color:#9ca3af; font-size:12px; text-align:center;">
        HeatGlow CRM &mdash; 66 Park Road, Whitchurch, Cardiff, CF14 7BR
      </p>
    </div>

  </div>
</body>
</html>
"""


def build_customer_acknowledgement_html(enquiry) -> str:
    """
    Build the HTML acknowledgement email sent to the customer
    immediately after they submit an enquiry.
    """
    urgency_messages = {
        'emergency': 'We treat emergency requests as a priority and will contact you as soon as possible.',
        'urgent': 'We aim to respond to urgent requests within a few hours.',
        'routine': 'We will review your enquiry and be in touch within 1-2 business days.',
        'flexible': 'We will review your enquiry and be in touch shortly.',
    }
    urgency_msg = urgency_messages.get(
        enquiry.urgency,
        'We will be in touch shortly.'
    )

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#f9fafb; font-family:Arial,sans-serif;">
  <div style="max-width:600px; margin:32px auto; background:#ffffff;
              border-radius:8px; overflow:hidden;
              box-shadow:0 1px 3px rgba(0,0,0,0.1);">

    <div style="background:#1a56db; padding:24px 32px;">
      <h1 style="margin:0; color:#ffffff; font-size:20px;">
        HeatGlow Heating &amp; Plumbing
      </h1>
    </div>

    <div style="padding:32px;">
      <h2 style="margin:0 0 16px; color:#111827; font-size:18px;">
        Thanks for your enquiry, {enquiry.customer_name.split()[0]}
      </h2>
      <p style="color:#374151; font-size:14px; line-height:1.6;">
        We have received your enquiry for <strong>{enquiry.job_type}</strong>
        at postcode <strong>{enquiry.customer_postcode}</strong>.
      </p>
      <p style="color:#374151; font-size:14px; line-height:1.6;">
        {urgency_msg}
      </p>
      <div style="background:#f0f9ff; border-radius:8px; padding:16px;
                  margin:24px 0; border-left:4px solid #1a56db;">
        <p style="margin:0 0 8px; color:#1e40af; font-weight:bold; font-size:14px;">
          Your enquiry summary
        </p>
        <p style="margin:0; color:#374151; font-size:14px;">
          Job type: {enquiry.job_type}<br>
          Urgency: {enquiry.urgency.capitalize()}<br>
          Postcode: {enquiry.customer_postcode}
        </p>
      </div>
      <p style="color:#374151; font-size:14px; line-height:1.6;">
        If you have any questions or your situation changes, please call us directly.
      </p>
      <p style="color:#374151; font-size:14px;">
        Kind regards,<br>
        <strong>Gareth Jones</strong><br>
        HeatGlow Heating &amp; Plumbing
      </p>
    </div>

    <div style="padding:16px 32px; background:#f3f4f6; border-top:1px solid #e5e7eb;">
      <p style="margin:0; color:#9ca3af; font-size:12px; text-align:center;">
        HeatGlow Heating &amp; Plumbing &mdash; 66 Park Road, Whitchurch, Cardiff, CF14 7BR
      </p>
    </div>

  </div>
</body>
</html>
"""