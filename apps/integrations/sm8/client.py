"""
ServiceM8 HTTP client.

Low-level wrapper around httpx with:
  - API key (HTTP Basic) authentication for reads
  - Cursor-based pagination via x-next-page-token header
  - Automatic rate limit handling (180 req/min ceiling → we self-throttle at 150)
  - Typed response parsing via the dataclasses in types.py
"""
from __future__ import annotations

import base64
import logging
import time
from collections.abc import Iterator
from typing import Any, Optional

import httpx
from django.conf import settings

from .types import SM8Company, SM8Job, SM8JobMaterial

logger = logging.getLogger(__name__)

SM8_BASE_URL = 'https://api.servicem8.com/api_1.0'
REQUEST_TIMEOUT = 30.0                  # seconds per request
RATE_LIMIT_REQUESTS_PER_MIN = 150       # self-throttle below the 180 ceiling
RATE_LIMIT_WINDOW_SECONDS = 60          # pause window when approaching limit


class SM8Error(Exception):
    """Raised when ServiceM8 returns an unexpected response."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class SM8Client:
    """
    Synchronous ServiceM8 API client.

    Usage:
        client = SM8Client()
        for company in client.iter_companies():
            print(company.name)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.SM8_API_KEY
        if not self.api_key:
            raise SM8Error('SM8_API_KEY is not set in environment')

        # HTTP Basic auth: key as username, empty password
        token = base64.b64encode(f'{self.api_key}:'.encode()).decode()
        self._headers = {
            'Authorization': f'Basic {token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        # httpx client — reused across requests for connection pooling
        self._client = httpx.Client(
            base_url=SM8_BASE_URL,
            headers=self._headers,
            timeout=REQUEST_TIMEOUT,
        )

        # Rate limit bookkeeping
        self._request_count = 0
        self._window_started_at = time.monotonic()

    # ---------- lifecycle ----------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> 'SM8Client':
        return self

    def __exit__(self, *_exc_info: Any) -> None:
        self.close()

    # ---------- internal: rate limiting ----------

    def _respect_rate_limit(self) -> None:
        """
        Simple token-bucket-ish pattern: count requests per minute,
        pause if we hit our self-imposed ceiling.
        """
        now = time.monotonic()
        elapsed = now - self._window_started_at

        if elapsed >= RATE_LIMIT_WINDOW_SECONDS:
            # Window rolled over
            self._request_count = 0
            self._window_started_at = now
            return

        if self._request_count >= RATE_LIMIT_REQUESTS_PER_MIN:
            sleep_for = RATE_LIMIT_WINDOW_SECONDS - elapsed + 1
            logger.warning(
                'SM8 self-throttle: sleeping %.1fs (%d requests in window)',
                sleep_for, self._request_count,
            )
            time.sleep(sleep_for)
            self._request_count = 0
            self._window_started_at = time.monotonic()

    # ---------- internal: HTTP ----------

    def _get(
        self,
        path: str,
        *,
        page_token: Optional[str] = None,
    ) -> httpx.Response:
        """Low-level GET with pagination token and rate limiting."""
        self._respect_rate_limit()

        headers = {}
        if page_token is not None:
            headers['x-next-page-token'] = page_token

        response = self._client.get(path, headers=headers)
        self._request_count += 1

        if response.status_code == 429:
            # Server-side rate limit hit — wait and retry once
            logger.warning('SM8 returned 429; sleeping 60s before retry')
            time.sleep(60)
            response = self._client.get(path, headers=headers)

        if response.status_code >= 400:
            raise SM8Error(
                f'SM8 {path} returned {response.status_code}: {response.text[:500]}',
                status_code=response.status_code,
            )

        return response

    # ---------- pagination iterator ----------

    def _paginate(self, path: str) -> Iterator[dict[str, Any]]:
        """
        Yield every object from a paginated SM8 list endpoint.

        SM8 uses cursor-based pagination via the x-next-page-token header.
        Start with token '-1'; loop until the response omits the header.
        """
        page_token: Optional[str] = '-1'
        page_num = 0

        while page_token is not None:
            page_num += 1
            response = self._get(path, page_token=page_token)

            try:
                data = response.json()
            except ValueError as exc:
                raise SM8Error(f'SM8 {path}: invalid JSON response') from exc

            if not isinstance(data, list):
                raise SM8Error(f'SM8 {path}: expected list, got {type(data).__name__}')

            logger.debug('SM8 %s page %d: %d records', path, page_num, len(data))
            yield from data

            # Absent header means last page
            page_token = response.headers.get('x-next-page-token')

    # ---------- high-level: companies ----------

    def iter_companies(self) -> Iterator[SM8Company]:
        """Iterate every company (active and archived)."""
        for raw in self._paginate('/company.json'):
            yield SM8Company.from_api(raw)

    def fetch_all_companies(self) -> list[SM8Company]:
        """Fetch all companies into a list. Convenience wrapper."""
        return list(self.iter_companies())

    def fetch_company(self, company_uuid: str) -> Optional[SM8Company]:
        """Fetch a single company by UUID. Returns None if not found."""
        try:
            response = self._get(f'/company/{company_uuid}.json')
        except SM8Error as exc:
            if exc.status_code == 404:
                return None
            raise
        return SM8Company.from_api(response.json())

    # ---------- high-level: jobs ----------

    def iter_jobs(self) -> Iterator[SM8Job]:
        """Iterate every job."""
        for raw in self._paginate('/job.json'):
            yield SM8Job.from_api(raw)

    def fetch_all_jobs(self) -> list[SM8Job]:
        return list(self.iter_jobs())

    def fetch_job(self, job_uuid: str) -> Optional[SM8Job]:
        try:
            response = self._get(f'/job/{job_uuid}.json')
        except SM8Error as exc:
            if exc.status_code == 404:
                return None
            raise
        return SM8Job.from_api(response.json())

    # ---------- high-level: job materials ----------

    def iter_job_materials(self) -> Iterator[SM8JobMaterial]:
        """Iterate every job material — used later to compute materials cost."""
        for raw in self._paginate('/job_material.json'):
            yield SM8JobMaterial.from_api(raw)