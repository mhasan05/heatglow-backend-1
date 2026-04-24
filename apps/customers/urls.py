from django.urls import path
from .views import (
    CustomerListView,
    CustomerDetailView,
    CustomerNotesView,
    SegmentPreviewView,
    CustomerExportView,
)

urlpatterns = [
    path('', CustomerListView.as_view(), name='customer-list'),
    path('segment-preview/', SegmentPreviewView.as_view(), name='segment-preview'),
    path('export/', CustomerExportView.as_view(), name='customer-export'),
    path('<uuid:pk>/', CustomerDetailView.as_view(), name='customer-detail'),
    path('<uuid:pk>/notes/', CustomerNotesView.as_view(), name='customer-notes'),
    path(
        '<uuid:pk>/notes/<uuid:note_id>/',
        CustomerNotesView.as_view(),
        name='customer-note-delete',
    ),
]