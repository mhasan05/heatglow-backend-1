"""
Campaign Manager API views.

GET  /api/v1/campaigns/              — list campaigns
POST /api/v1/campaigns/              — create draft (admin)
GET  /api/v1/campaigns/{id}/         — campaign detail + stats
PATCH /api/v1/campaigns/{id}/        — edit draft (admin)
DELETE /api/v1/campaigns/{id}/       — delete draft (admin)
POST /api/v1/campaigns/{id}/approve/ — approve Tier 2 draft (admin)
POST /api/v1/campaigns/{id}/send/    — trigger send (admin)
GET  /api/v1/campaigns/queue/        — pending Tier 2 drafts
"""
import logging
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination

from apps.core.permissions import IsAdminOrReadOnly, IsAdmin
from apps.core.models import AuditLog
from .models import Campaign, CampaignBatch
from .serializers import (
    CampaignListSerializer,
    CampaignCreateSerializer,
    CampaignDetailSerializer,
)
from .segments import build_segment_queryset

logger = logging.getLogger(__name__)


class CampaignPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class CampaignListCreateView(APIView):
    """
    GET  /api/v1/campaigns/  — list all campaigns (admin + staff read)
    POST /api/v1/campaigns/  — create draft (admin only)
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAdmin()]
        return [IsAdminOrReadOnly()]

    def get(self, request: Request) -> Response:
        qs = Campaign.objects.select_related(
            'created_by', 'approved_by'
        ).order_by('-created_at')

        # Filter by status
        campaign_status = request.query_params.get('status')
        if campaign_status:
            qs = qs.filter(status=campaign_status)

        # Filter by type
        campaign_type = request.query_params.get('type')
        if campaign_type:
            qs = qs.filter(campaign_type=campaign_type)

        paginator = CampaignPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = CampaignListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request: Request) -> Response:
        serializer = CampaignCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Calculate recipient count from segment filters
        filters = serializer.validated_data.get('segment_filters', [])
        recipient_count = build_segment_queryset(filters).count()

        campaign = serializer.save(
            created_by=request.user,
            status=Campaign.Status.DRAFT,
            recipient_count=recipient_count,
        )

        AuditLog.objects.create(
            actor_user=request.user,
            action='campaign.created',
            entity_type='campaign',
            entity_id=campaign.id,
            metadata={
                'name': campaign.name,
                'recipient_count': recipient_count,
            },
        )

        logger.info(
            'Campaign created: %s (%d recipients)',
            campaign.name, recipient_count,
        )

        return Response(
            CampaignDetailSerializer(campaign).data,
            status=status.HTTP_201_CREATED,
        )


class CampaignDetailView(APIView):
    """
    GET    /api/v1/campaigns/{id}/  — detail with stats
    PATCH  /api/v1/campaigns/{id}/  — edit draft (admin)
    DELETE /api/v1/campaigns/{id}/  — delete draft (admin)
    """
    permission_classes = [IsAdminOrReadOnly]

    def _get_campaign(self, pk):
        try:
            return Campaign.objects.select_related(
                'created_by', 'approved_by'
            ).prefetch_related('batches').get(pk=pk)
        except Campaign.DoesNotExist:
            return None

    def get(self, request: Request, pk) -> Response:
        campaign = self._get_campaign(pk)
        if not campaign:
            return Response(
                {'detail': 'Campaign not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(CampaignDetailSerializer(campaign).data)

    def patch(self, request: Request, pk) -> Response:
        from apps.core.permissions import _get_role
        from apps.accounts.models import UserProfile

        if _get_role(request) != UserProfile.Role.ADMIN:
            return Response(
                {'detail': 'Admin access required.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        campaign = self._get_campaign(pk)
        if not campaign:
            return Response(
                {'detail': 'Campaign not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if campaign.status not in (
            Campaign.Status.DRAFT, Campaign.Status.SCHEDULED
        ):
            return Response(
                {'detail': 'Only draft or scheduled campaigns can be edited.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CampaignDetailSerializer(
            campaign, data=request.data, partial=True
        )
        if serializer.is_valid():
            # Recalculate recipient count if filters changed
            if 'segment_filters' in request.data:
                filters = serializer.validated_data.get(
                    'segment_filters', campaign.segment_filters
                )
                serializer.validated_data['recipient_count'] = (
                    build_segment_queryset(filters).count()
                )
            serializer.save()
            return Response(serializer.data)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    def delete(self, request: Request, pk) -> Response:
        from apps.core.permissions import _get_role
        from apps.accounts.models import UserProfile

        if _get_role(request) != UserProfile.Role.ADMIN:
            return Response(
                {'detail': 'Admin access required.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        campaign = self._get_campaign(pk)
        if not campaign:
            return Response(
                {'detail': 'Campaign not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if campaign.status in (Campaign.Status.SENDING, Campaign.Status.SENT):
            return Response(
                {'detail': 'Cannot delete a campaign that has been sent.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        campaign_name = campaign.name
        campaign.delete()

        AuditLog.objects.create(
            actor_user=request.user,
            action='campaign.deleted',
            entity_type='campaign',
            metadata={'name': campaign_name},
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class CampaignApproveView(APIView):
    """
    POST /api/v1/campaigns/{id}/approve/
    Admin only. Approves a Tier 2 draft campaign.
    Changes status from draft to scheduled/sending.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request, pk) -> Response:
        try:
            campaign = Campaign.objects.get(pk=pk)
        except Campaign.DoesNotExist:
            return Response(
                {'detail': 'Campaign not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if campaign.status != Campaign.Status.DRAFT:
            return Response(
                {'detail': 'Only draft campaigns can be approved.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        campaign.approved_by = request.user
        campaign.approved_at = timezone.now()
        campaign.status = Campaign.Status.SCHEDULED
        campaign.save()

        AuditLog.objects.create(
            actor_user=request.user,
            action='campaign.approved',
            entity_type='campaign',
            entity_id=campaign.id,
            metadata={'name': campaign.name},
        )

        logger.info('Campaign approved: %s by %s', campaign.name, request.user)

        return Response(CampaignDetailSerializer(campaign).data)


class CampaignSendView(APIView):
    """
    POST /api/v1/campaigns/{id}/send/
    Admin only. Triggers the Celery send task.
    Creates CampaignBatch records and dispatches them.
    """
    permission_classes = [IsAdmin]

    def post(self, request: Request, pk) -> Response:
        try:
            campaign = Campaign.objects.get(pk=pk)
        except Campaign.DoesNotExist:
            return Response(
                {'detail': 'Campaign not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if campaign.status not in (
            Campaign.Status.DRAFT,
            Campaign.Status.SCHEDULED,
        ):
            return Response(
                {'detail': 'Campaign cannot be sent in its current status.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not campaign.recipient_count or campaign.recipient_count == 0:
            return Response(
                {'detail': 'No recipients match the campaign filters.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Trigger the send task
        from apps.campaigns.tasks import send_campaign
        task = send_campaign.delay(str(campaign.id))

        campaign.status = Campaign.Status.SENDING
        campaign.save(update_fields=['status', 'updated_at'])

        AuditLog.objects.create(
            actor_user=request.user,
            action='campaign.send_triggered',
            entity_type='campaign',
            entity_id=campaign.id,
            metadata={
                'name': campaign.name,
                'recipient_count': campaign.recipient_count,
                'task_id': task.id,
            },
        )

        return Response({
            'message': 'Campaign send started.',
            'task_id': task.id,
            'recipient_count': campaign.recipient_count,
        })


class CampaignQueueView(APIView):
    """
    GET /api/v1/campaigns/queue/
    Returns pending Tier 2 draft campaigns awaiting Gareth's approval.
    Both admin and staff can view the queue.
    """
    permission_classes = [IsAdminOrReadOnly]

    def get(self, request: Request) -> Response:
        drafts = Campaign.objects.filter(
            status=Campaign.Status.DRAFT,
            campaign_type=Campaign.Type.AUTOMATION_TIER2,
        ).select_related('created_by').order_by('-created_at')

        serializer = CampaignListSerializer(drafts, many=True)
        return Response({
            'count': drafts.count(),
            'results': serializer.data,
        })