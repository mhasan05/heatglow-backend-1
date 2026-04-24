from django.urls import path
from .webhooks import SM8WebhookView
from apps.campaigns.webhooks import ResendWebhookView, UnsubscribeView

urlpatterns = [
    path('sm8/', SM8WebhookView.as_view(), name='sm8-webhook'),
    path('resend/', ResendWebhookView.as_view(), name='resend-webhook'),
    path('unsubscribe/', UnsubscribeView.as_view(), name='unsubscribe'),
]