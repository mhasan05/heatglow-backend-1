"""
Public-facing enquiry form views.
No authentication required.
Served at /enquiry/ — embeddable as an iframe on heatglow.co.uk
"""
import logging
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from rest_framework.throttling import AnonRateThrottle

from .models import Enquiry
from .serializers import EnquiryCreateSerializer, EnquiryDetailSerializer

logger = logging.getLogger(__name__)


class EnquiryThrottle(AnonRateThrottle):
    """10 enquiry submissions per hour per IP."""
    rate = '10/hour'


class PublicEnquiryView(APIView):
    """
    POST /api/v1/public/enquiry/

    Public enquiry submission endpoint.
    - No authentication required
    - Rate limited to 10/hour per IP
    - Honeypot field checked (bots fill hidden fields)
    - Triggers AI qualification + notification emails

    Three possible outcomes shown to the user:
      1. Success — enquiry received
      2. Out of area — polite rejection
      3. Validation error — form errors
    """
    permission_classes = [AllowAny]
    throttle_classes = [EnquiryThrottle]

    def post(self, request: Request) -> Response:
        # ── Honeypot check ────────────────────────────────────────────────────
        # Real users never fill the 'website' field — bots always do
        if request.data.get('website'):
            logger.warning(
                'Honeypot triggered from IP %s',
                self._get_client_ip(request),
            )
            # Return 201 to fool the bot — don't save anything
            return Response(
                {'status': 'received', 'outcome': 'success'},
                status=status.HTTP_201_CREATED,
            )

        # ── Validate form data ────────────────────────────────────────────────
        serializer = EnquiryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    'status': 'error',
                    'outcome': 'validation_error',
                    'errors': serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Link to existing customer ─────────────────────────────────────────
        customer = None
        email = serializer.validated_data.get('customer_email')
        if email:
            from apps.customers.models import Customer
            customer = Customer.objects.filter(email=email).first()

        # ── Save enquiry ──────────────────────────────────────────────────────
        enquiry = serializer.save(
            customer=customer,
            status=Enquiry.Status.PENDING,
            source='embed_widget',
        )

        logger.info(
            'Public enquiry submitted: %s from %s (%s)',
            enquiry.id,
            enquiry.customer_name,
            enquiry.customer_postcode,
        )

        # ── Trigger AI qualification (async) ──────────────────────────────────
        try:
            from apps.enquiries.tasks import qualify_enquiry_async
            qualify_enquiry_async.delay(str(enquiry.id))
        except Exception as exc:
            logger.warning('Could not queue qualification: %s', exc)

        return Response(
            {
                'status': 'received',
                'outcome': 'success',
                'enquiry_id': str(enquiry.id),
                'message': (
                    'Thank you for your enquiry. '
                    'We will be in touch shortly.'
                ),
            },
            status=status.HTTP_201_CREATED,
        )

    def _get_client_ip(self, request) -> str:
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            return x_forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


class PublicEnquiryStatusView(APIView):
    """
    GET /api/v1/public/enquiry/{id}/status/

    Lets the public form check the status of a submitted enquiry.
    Returns minimal info only — no AI details exposed.
    """
    permission_classes = [AllowAny]

    def get(self, request: Request, pk) -> Response:
        try:
            enquiry = Enquiry.objects.get(pk=pk)
        except Enquiry.DoesNotExist:
            return Response(
                {'detail': 'Not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            'enquiry_id': str(enquiry.id),
            'status': enquiry.status,
            'job_type': enquiry.job_type,
            'created_at': enquiry.created_at.isoformat(),
        })