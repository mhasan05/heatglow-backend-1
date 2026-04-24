from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),

    # API v1 — authenticated
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/customers/', include('apps.customers.urls')),
    path('api/v1/enquiries/', include('apps.enquiries.urls')),
    path('api/v1/heatshield/', include('apps.heatshield.urls')),
    path('api/v1/campaigns/', include('apps.campaigns.urls')),
    path('api/v1/', include('apps.core.urls')),

    # Public
    path('api/v1/public/', include('apps.enquiries.public_urls')),

    # Webhooks
    path('webhooks/', include('apps.integrations.urls')),

    # Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]