"""
HeatShield renewal reminder email templates.
Three variants: 60-day, 30-day, day-of renewal.
"""
from django.conf import settings


def build_renewal_email(
    customer_name: str,
    renewal_date: str,
    plan_type: str,
    monthly_amount: str,
    reminder_type: str,   # '60_day' | '30_day' | 'day_of'
) -> dict:
    """
    Build subject + HTML for a HeatShield renewal reminder.
    Returns { 'subject': str, 'html': str }
    """
    first_name = customer_name.split()[0] if customer_name else 'there'

    subjects = {
        '60_day': (
            'Your HeatShield plan renews in 60 days'
        ),
        '30_day': (
            'Your HeatShield plan renews in 30 days'
        ),
        'day_of': (
            'Your HeatShield plan renews today'
        ),
    }

    intro_messages = {
        '60_day': (
            'Just a friendly heads-up that your HeatShield maintenance plan '
            'is due for renewal in <strong>60 days</strong> on '
            f'<strong>{renewal_date}</strong>.'
        ),
        '30_day': (
            'Your HeatShield maintenance plan renews in '
            '<strong>30 days</strong> on '
            f'<strong>{renewal_date}</strong>. '
            'We will be in touch to schedule your annual service visit.'
        ),
        'day_of': (
            'Your HeatShield maintenance plan <strong>renews today</strong>. '
            'Your monthly direct debit of '
            f'<strong>£{monthly_amount}</strong> '
            'will be collected as normal.'
        ),
    }

    action_messages = {
        '60_day': (
            'No action is needed from you — your plan continues automatically. '
            'We will be in touch closer to your renewal date to arrange '
            'your annual boiler service.'
        ),
        '30_day': (
            'We will contact you shortly to book your annual service visit. '
            'If you have any questions about your plan, please reply to '
            'this email or call us directly.'
        ),
        'day_of': (
            'Thank you for being a HeatShield member. Your annual service '
            'visit will be arranged shortly. If you have any questions '
            'or would like to discuss your plan, please get in touch.'
        ),
    }

    subject = subjects.get(reminder_type, 'HeatShield plan renewal')
    intro = intro_messages.get(reminder_type, '')
    action = action_messages.get(reminder_type, '')

    html = f"""
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
        HeatGlow HeatShield
      </h1>
      <p style="margin:4px 0 0; color:#bfdbfe; font-size:13px;">
        Maintenance Plan
      </p>
    </div>

    <!-- Body -->
    <div style="padding:32px;">
      <p style="color:#374151; font-size:16px; margin:0 0 16px;">
        Hi {first_name},
      </p>

      <p style="color:#374151; font-size:15px; line-height:1.7; margin:0 0 20px;">
        {intro}
      </p>

      <!-- Plan summary box -->
      <div style="background:#f0f9ff; border-radius:8px; padding:20px;
                  margin:24px 0; border-left:4px solid #1a56db;">
        <p style="margin:0 0 6px; color:#1e40af; font-weight:bold;
                  font-size:14px; text-transform:uppercase; letter-spacing:0.5px;">
          Your Plan Summary
        </p>
        <table style="width:100%; border-collapse:collapse;">
          <tr>
            <td style="padding:4px 0; color:#6b7280; font-size:14px; width:160px;">
              Plan type
            </td>
            <td style="padding:4px 0; color:#111827; font-size:14px;
                       font-weight:bold; text-transform:capitalize;">
              {plan_type}
            </td>
          </tr>
          <tr>
            <td style="padding:4px 0; color:#6b7280; font-size:14px;">
              Monthly amount
            </td>
            <td style="padding:4px 0; color:#111827; font-size:14px;
                       font-weight:bold;">
              £{monthly_amount}
            </td>
          </tr>
          <tr>
            <td style="padding:4px 0; color:#6b7280; font-size:14px;">
              Renewal date
            </td>
            <td style="padding:4px 0; color:#111827; font-size:14px;
                       font-weight:bold;">
              {renewal_date}
            </td>
          </tr>
        </table>
      </div>

      <p style="color:#374151; font-size:15px; line-height:1.7; margin:0 0 24px;">
        {action}
      </p>

      <p style="color:#374151; font-size:15px; margin:0;">
        Kind regards,<br>
        <strong>Gareth Jones</strong><br>
        HeatGlow Heating &amp; Plumbing
      </p>
    </div>

    <!-- Footer -->
    <div style="padding:16px 32px; background:#f3f4f6;
                border-top:1px solid #e5e7eb;">
      <p style="margin:0; color:#9ca3af; font-size:12px; text-align:center;">
        HeatGlow Heating &amp; Plumbing &mdash;
        66 Park Road, Whitchurch, Cardiff, CF14 7BR<br>
        Questions? Reply to this email or call us directly.
      </p>
    </div>

  </div>
</body>
</html>
"""

    return {'subject': subject, 'html': html}