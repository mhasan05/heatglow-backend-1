"""
Resend email client for HeatGlow CRM.

All outbound email goes through this module:
  - Transactional (enquiry notifications, HeatShield reminders)
  - Bulk campaign sending (Phase 5)

Docs: https://resend.com/docs
"""
import logging
from dataclasses import dataclass
from typing import Optional
import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

RESEND_BASE_URL = 'https://api.resend.com'
FROM_DEFAULT = 'Gareth — HeatGlow <gareth@heatglow.co.uk>'


@dataclass
class EmailResult:
    success: bool
    email_id: Optional[str] = None
    error: Optional[str] = None


def send_email(
    to: str | list[str],
    subject: str,
    html: str,
    from_address: str = FROM_DEFAULT,
    reply_to: Optional[str] = None,
    tags: Optional[list[dict]] = None,
) -> EmailResult:
    """
    Send a single transactional email via Resend.

    Args:
        to:           recipient email(s)
        subject:      email subject line
        html:         full HTML body
        from_address: sender (must be a verified domain in Resend)
        reply_to:     optional reply-to address
        tags:         optional Resend tags for tracking

    Returns EmailResult with success flag and email_id from Resend.
    """
    api_key = settings.RESEND_API_KEY
    if not api_key:
        logger.warning('RESEND_API_KEY not set — email not sent: %s', subject)
        return EmailResult(success=False, error='RESEND_API_KEY not configured')

    payload = {
        'from': from_address,
        'to': [to] if isinstance(to, str) else to,
        'subject': subject,
        'html': html,
    }

    if reply_to:
        payload['reply_to'] = reply_to

    if tags:
        payload['tags'] = tags

    try:
        response = httpx.post(
            f'{RESEND_BASE_URL}/emails',
            json=payload,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            timeout=15,
        )

        if response.status_code in (200, 201):
            data = response.json()
            email_id = data.get('id')
            logger.info(
                'Email sent via Resend: id=%s subject=%s to=%s',
                email_id, subject, to,
            )
            return EmailResult(success=True, email_id=email_id)

        else:
            error = f'Resend API error {response.status_code}: {response.text[:300]}'
            logger.error('Failed to send email: %s', error)
            return EmailResult(success=False, error=error)

    except httpx.TimeoutException:
        error = 'Resend API timeout'
        logger.error('Email send timeout: %s', error)
        return EmailResult(success=False, error=error)

    except Exception as exc:
        error = str(exc)
        logger.exception('Unexpected error sending email: %s', error)
        return EmailResult(success=False, error=error)


def send_test_email(to: str) -> EmailResult:
    """
    Send a test email to verify Resend is configured correctly.
    Called from the Settings screen.
    """
    return send_email(
        to=to,
        subject='HeatGlow CRM — Test Email',
        html="""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #1a56db;">HeatGlow CRM</h2>
            <p>This is a test email confirming that your Resend integration is working correctly.</p>
            <p>If you received this, email notifications are set up and ready to go.</p>
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
            <p style="color: #6b7280; font-size: 12px;">
                Sent from HeatGlow CRM &mdash; gareth@heatglow.co.uk
            </p>
        </div>
        """,
    )