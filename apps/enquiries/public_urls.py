from django.urls import path
from .public_views import PublicEnquiryView, PublicEnquiryStatusView

urlpatterns = [
    path('enquiry/', PublicEnquiryView.as_view(), name='public-enquiry'),
    path(
        'enquiry/<uuid:pk>/status/',
        PublicEnquiryStatusView.as_view(),
        name='public-enquiry-status',
    ),
]