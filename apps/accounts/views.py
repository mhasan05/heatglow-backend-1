"""
Authentication and user profile views.
"""
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import UserSerializer, EmailTokenObtainPairSerializer


class LoginView(APIView):
    """
    POST /api/v1/auth/login/
    Body: { "email": "gareth@heatglow.co.uk", "password": "..." }
    Returns: {
        "access": "...",
        "refresh": "...",
        "user": { id, username, email, full_name, role, is_admin }
    }
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = EmailTokenObtainPairSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_401_UNAUTHORIZED,
            )

        data = serializer.validated_data

        # Get the user from the email
        from django.contrib.auth.models import User
        email = request.data.get('email', '').strip().lower()
        try:
            user = User.objects.select_related('profile').get(
                email__iexact=email
            )
        except User.DoesNotExist:
            return Response(
                {'detail': 'User not found.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Build user payload
        try:
            role = user.profile.role
            is_admin = user.profile.is_admin
            phone = user.profile.phone or ''
        except Exception:
            role = 'staff'
            is_admin = False
            phone = ''

        return Response({
            'access': data['access'],
            'refresh': data['refresh'],
            'user': {
                'id': user.id,
                'uuid': str(user.profile.id) if hasattr(user, 'profile') else None,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'full_name': user.get_full_name() or user.username,
                'role': role,
                'is_admin': is_admin,
                'phone': phone,
                'date_joined': user.date_joined.isoformat(),
                'last_login': (
                    user.last_login.isoformat()
                    if user.last_login else None
                ),
            },
        })


class TokenRefreshAPIView(TokenRefreshView):
    """
    POST /api/v1/auth/refresh/
    Body: { "refresh": "..." }
    Returns: { "access": "..." }
    """
    permission_classes = [AllowAny]


class MeView(APIView):
    """
    GET /api/v1/auth/me/
    Returns the currently authenticated user with their role.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        serializer = UserSerializer(request.user)
        return Response(serializer.data)