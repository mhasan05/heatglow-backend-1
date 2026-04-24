from django.urls import path
from .views import (
    HeatshieldListCreateView,
    HeatshieldDetailView,
    HeatshieldMarkServicedView,
    HeatshieldCancelView,
    HeatshieldExportView,
)

urlpatterns = [
    path('', HeatshieldListCreateView.as_view(), name='heatshield-list'),
    path('<uuid:pk>/', HeatshieldDetailView.as_view(), name='heatshield-detail'),
    path('export/', HeatshieldExportView.as_view(), name='heatshield-export'),
    path(
        '<uuid:pk>/mark-serviced/',
        HeatshieldMarkServicedView.as_view(),
        name='heatshield-mark-serviced',
    ),
    path(
        '<uuid:pk>/cancel/',
        HeatshieldCancelView.as_view(),
        name='heatshield-cancel',
    ),
]