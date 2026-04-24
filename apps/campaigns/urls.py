from django.urls import path
from .views import (
    CampaignListCreateView,
    CampaignDetailView,
    CampaignApproveView,
    CampaignSendView,
    CampaignQueueView,
)

urlpatterns = [
    path('', CampaignListCreateView.as_view(), name='campaign-list'),
    path('queue/', CampaignQueueView.as_view(), name='campaign-queue'),
    path('<uuid:pk>/', CampaignDetailView.as_view(), name='campaign-detail'),
    path(
        '<uuid:pk>/approve/',
        CampaignApproveView.as_view(),
        name='campaign-approve',
    ),
    path(
        '<uuid:pk>/send/',
        CampaignSendView.as_view(),
        name='campaign-send',
    ),
]