from django.urls import path
from .views import (
    EnquiryListCreateView,
    EnquiryDetailView,
    EnquiryApproveView,
    EnquiryRejectView,
    EnquiryNoteView,
    EnquiryQualifyView,
)

urlpatterns = [
    path('', EnquiryListCreateView.as_view(), name='enquiry-list-create'),
    path('<uuid:pk>/', EnquiryDetailView.as_view(), name='enquiry-detail'),
    path('<uuid:pk>/qualify/', EnquiryQualifyView.as_view(), name='enquiry-qualify'),
    path('<uuid:pk>/approve/', EnquiryApproveView.as_view(), name='enquiry-approve'),
    path('<uuid:pk>/reject/', EnquiryRejectView.as_view(), name='enquiry-reject'),
    path('<uuid:pk>/notes/', EnquiryNoteView.as_view(), name='enquiry-note'),
]