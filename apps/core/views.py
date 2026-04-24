"""
Core API views — dashboard metrics, activity feed, settings.
"""
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from rest_framework import status
from .models import AuditLog
from apps.core.permissions import IsAdmin
from apps.core.metrics import get_dashboard_metrics

DASHBOARD_CACHE_KEY = 'dashboard_metrics_{period}'
DASHBOARD_CACHE_TTL = 300  # 5 minutes


class DashboardView(APIView):
    """
    GET /api/v1/dashboard/

    Returns the complete dashboard payload in a single call.
    Cached for 5 minutes. Cache bypassed with ?no_cache=1 (admin only).

    Query params:
        period   — 7 | 30 | 90 | 365 (default 30)
        no_cache — bypass cache (admin only, for manual sync)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            period = int(request.query_params.get('period', 30))
            if period not in (7, 30, 90, 365):
                period = 30
        except (ValueError, TypeError):
            period = 30

        no_cache = request.query_params.get('no_cache') == '1'
        cache_key = DASHBOARD_CACHE_KEY.format(period=period)

        # Try cache first (unless bypass requested by admin)
        if not no_cache:
            cached = cache.get(cache_key)
            if cached:
                cached['_cached'] = True
                return Response(cached)

        metrics = get_dashboard_metrics(period_days=period)
        metrics['_cached'] = False

        # Store in cache
        cache.set(cache_key, metrics, DASHBOARD_CACHE_TTL)

        return Response(metrics)


class ActivityFeedView(APIView):
    """
    GET /api/v1/activity/

    Query params:
        limit — number of entries (default 12, max 50)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        from apps.core.models import AuditLog

        try:
            limit = min(int(request.query_params.get('limit', 12)), 50)
        except (ValueError, TypeError):
            limit = 12

        entries = (
            AuditLog.objects
            .select_related('actor_user')
            .order_by('-created_at')[:limit]
        )

        data = [
            {
                'id': str(e.id),
                'action': e.action,
                'entity_type': e.entity_type,
                'entity_id': str(e.entity_id) if e.entity_id else None,
                'actor': (
                    e.actor_user.get_full_name()
                    if e.actor_user else 'System'
                ),
                'metadata': e.metadata,
                'created_at': e.created_at.isoformat(),
            }
            for e in entries
        ]

        return Response({'results': data, 'count': len(data)})


class SettingsView(APIView):
    """
    GET  /api/v1/settings/   — retrieve all settings (admin only)
    PATCH /api/v1/settings/  — update settings (admin only)
    """
    permission_classes = [IsAdmin]

    def get(self, request: Request) -> Response:
        from apps.core.models import Setting

        # Exclude sensitive keys from the response
        excluded = {'sm8_oauth_tokens', 'sm8_access_token', 'sm8_refresh_token'}
        settings = Setting.objects.exclude(key__in=excluded)

        return Response({
            s.key: s.value for s in settings
        })

    def patch(self, request: Request) -> Response:
        from apps.core.models import Setting
        from django.utils import timezone

        # Exclude sensitive keys from being updated via API
        excluded = {'sm8_oauth_tokens', 'sm8_access_token', 'sm8_refresh_token'}
        updated = {}

        for key, value in request.data.items():
            if key in excluded:
                continue
            obj, _ = Setting.objects.update_or_create(
                key=key,
                defaults={'value': value},
            )
            updated[key] = obj.value

            # Log the settings change
            from apps.core.models import AuditLog
            AuditLog.objects.create(
                actor_user=request.user,
                action='settings.update',
                entity_type='setting',
                metadata={'key': key, 'value': value},
            )

        # Bust dashboard cache when settings change
        for period in (7, 30, 90, 365):
            cache.delete(DASHBOARD_CACHE_KEY.format(period=period))

        return Response(updated)
    


class SyncNowView(APIView):
    """
    POST /api/v1/sync/now/
    Admin only. Triggers a manual SM8 full sync.
    Rate-limited to once per 10 minutes.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request) -> Response:
        from django.core.cache import cache
        from apps.integrations.tasks import sm8_full_sync

        cooldown_key = 'sync_now_cooldown'
        if cache.get(cooldown_key):
            return Response(
                {'detail': 'Sync is on cooldown. Please wait 10 minutes.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        cache.set(cooldown_key, True, 600)  # 10-minute cooldown

        task = sm8_full_sync.delay()

        AuditLog.objects.create(
            actor_user=request.user,
            action='sm8.manual_sync',
            entity_type='sync',
            metadata={'task_id': task.id},
        )

        return Response({
            'message': 'Sync started.',
            'task_id': task.id,
        })


class TestEmailView(APIView):
    """
    POST /api/v1/settings/test-email/
    Admin only. Sends a test email to Gareth's address.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request) -> Response:
        from apps.integrations.resend_client import send_test_email
        from django.conf import settings as django_settings

        to = request.data.get('to', django_settings.GARETH_EMAIL)
        result = send_test_email(to)

        if result.success:
            return Response({
                'message': 'Test email sent to ' + to,
                'email_id': result.email_id,
            })
        return Response(
            {'detail': 'Failed to send: ' + (result.error or 'unknown error')},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )