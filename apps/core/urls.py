from django.urls import path
from .views import (
    DashboardView,
    ActivityFeedView,
    SettingsView,
    SyncNowView,
    TestEmailView,
)

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('activity/', ActivityFeedView.as_view(), name='activity-feed'),
    path('settings/', SettingsView.as_view(), name='settings'),
    path('sync/now/', SyncNowView.as_view(), name='sync-now'),
    path('settings/test-email/', TestEmailView.as_view(), name='test-email'),
]