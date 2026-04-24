"""
ServiceM8 write-back operations.

We write to ServiceM8 in exactly two situations:
  1. When Gareth approves an enquiry  → create a job in SM8
  2. When a new enquiry comes from an unknown customer → create a company first

OAuth 2.0 is required for all writes. Tokens are stored encrypted
in the settings table using Fernet symmetric encryption.
"""
import logging
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


# ── Token encryption ─────────────────────────────────────────────────────────

def _get_fernet():
    """Return a Fernet instance using the key from settings."""
    from cryptography.fernet import Fernet
    key = settings.FERNET_ENCRYPTION_KEY
    if not key:
        raise ValueError('FERNET_ENCRYPTION_KEY is not set in environment')
    return Fernet(key.encode() if isinstance(key, str) else key)


def store_oauth_tokens(access_token: str, refresh_token: str, expires_in: int) -> None:
    """Encrypt and store SM8 OAuth tokens in the settings table."""
    import time
    from apps.core.models import Setting

    fernet = _get_fernet()
    expires_at = int(time.time()) + expires_in

    token_data = {
        'access_token': fernet.encrypt(access_token.encode()).decode(),
        'refresh_token': fernet.encrypt(refresh_token.encode()).decode(),
        'expires_at': expires_at,
    }

    Setting.objects.update_or_create(
        key='sm8_oauth_tokens',
        defaults={'value': token_data},
    )
    logger.info('SM8 OAuth tokens stored (expires in %ds)', expires_in)


def get_valid_access_token() -> Optional[str]:
    """
    Retrieve a valid SM8 access token.
    Automatically refreshes if expired.
    Returns None if no tokens are stored yet.
    """
    import time
    from apps.core.models import Setting

    try:
        setting = Setting.objects.get(key='sm8_oauth_tokens')
        token_data = setting.value
    except Setting.DoesNotExist:
        logger.warning('No SM8 OAuth tokens found in settings')
        return None

    fernet = _get_fernet()
    expires_at = token_data.get('expires_at', 0)

    # Refresh if token expires within the next 60 seconds
    if time.time() < expires_at - 60:
        access_token = fernet.decrypt(
            token_data['access_token'].encode()
        ).decode()
        return access_token

    # Token is expired — refresh it
    logger.info('SM8 access token expired, refreshing...')
    refresh_token = fernet.decrypt(
        token_data['refresh_token'].encode()
    ).decode()

    return _refresh_access_token(refresh_token)


def _refresh_access_token(refresh_token: str) -> Optional[str]:
    """Exchange a refresh token for a new access token."""
    import httpx
    from django.conf import settings as django_settings

    try:
        response = httpx.post(
            'https://go.servicem8.com/oauth/access_token',
            data={
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': django_settings.SM8_OAUTH_CLIENT_ID,
                'client_secret': django_settings.SM8_OAUTH_CLIENT_SECRET,
            },
            timeout=15,
        )
        response.raise_for_status()
        token_response = response.json()

        store_oauth_tokens(
            access_token=token_response['access_token'],
            refresh_token=token_response.get('refresh_token', refresh_token),
            expires_in=token_response.get('expires_in', 3600),
        )
        return token_response['access_token']

    except Exception as exc:
        logger.exception('SM8 token refresh failed: %s', exc)
        return None


# ── Job creation ──────────────────────────────────────────────────────────────

def create_sm8_job(enquiry) -> Optional[str]:
    """
    Create a job in ServiceM8 for an approved enquiry.

    Returns the SM8 job UUID if successful, None otherwise.
    Raises an exception if the API call fails.
    """
    import httpx

    access_token = get_valid_access_token()
    if not access_token:
        raise ValueError(
            'No valid SM8 OAuth token available. '
            'Complete the OAuth flow in Settings first.'
        )

    # Build the SM8 job payload
    company_uuid = None
    if enquiry.customer and enquiry.customer.sm8_company_uuid:
        company_uuid = str(enquiry.customer.sm8_company_uuid)

    if not company_uuid:
        # New customer — create the company in SM8 first
        company_uuid = _create_sm8_company(enquiry, access_token)

    if not company_uuid:
        raise ValueError('Could not resolve or create SM8 company for enquiry')

    payload = {
        'company_uuid': company_uuid,
        'status': 'Quote',
        'job_description': (
            f'{enquiry.job_type}\n\n'
            f'{enquiry.description}\n\n'
            f'Urgency: {enquiry.urgency}\n'
            f'Submitted via HeatGlow CRM'
        ),
        'job_address': enquiry.customer.address_line1 if enquiry.customer else '',
        'created_by_staff_uuid': '',
    }

    response = httpx.post(
        'https://api.servicem8.com/api_1.0/job.json',
        json=payload,
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        },
        timeout=15,
    )

    if response.status_code not in (200, 201):
        raise ValueError(
            f'SM8 job creation failed: {response.status_code} {response.text[:300]}'
        )

    # SM8 returns the new UUID in the x-record-uuid header
    job_uuid = response.headers.get('x-record-uuid')
    if not job_uuid:
        # Some SM8 versions return it in the body
        try:
            job_uuid = response.json().get('uuid')
        except Exception:
            pass

    logger.info('SM8 job created: %s for company %s', job_uuid, company_uuid)
    return job_uuid


def _create_sm8_company(enquiry, access_token: str) -> Optional[str]:
    """Create a new company in ServiceM8 for a first-time customer."""
    import httpx

    payload = {
        'name': enquiry.customer_name,
        'email': enquiry.customer_email,
        'phone': enquiry.customer_phone or '',
        'address': '',
        'postcode': enquiry.customer_postcode,
    }

    response = httpx.post(
        'https://api.servicem8.com/api_1.0/company.json',
        json=payload,
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        },
        timeout=15,
    )

    if response.status_code not in (200, 201):
        logger.error(
            'SM8 company creation failed: %s %s',
            response.status_code, response.text[:300],
        )
        return None

    company_uuid = response.headers.get('x-record-uuid')
    logger.info('SM8 company created: %s for %s', company_uuid, enquiry.customer_name)

    # Save the SM8 UUID to the customer record if it exists
    if enquiry.customer and company_uuid:
        enquiry.customer.sm8_company_uuid = company_uuid
        enquiry.customer.save(update_fields=['sm8_company_uuid', 'updated_at'])

    return company_uuid