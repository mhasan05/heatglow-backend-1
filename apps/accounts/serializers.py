"""
Serializers for authentication and user profile endpoints.
"""
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import UserProfile


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Override SimpleJWT's default serializer to accept email
    instead of username.

    POST /api/v1/auth/login/
    Body: { "email": "gareth@heatglow.co.uk", "password": "..." }
    """
    # Replace the username field with email
    username_field = 'email'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Rename the field in the serializer
        self.fields['email'] = serializers.EmailField()
        self.fields.pop('username', None)

    def validate(self, attrs):
        email = attrs.get('email', '').strip().lower()
        password = attrs.get('password', '')

        # Look up user by email
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {'detail': 'No account found with this email address.'}
            )
        except User.MultipleObjectsReturned:
            raise serializers.ValidationError(
                {'detail': 'Multiple accounts found. Contact your administrator.'}
            )

        # Verify password
        if not user.check_password(password):
            raise serializers.ValidationError(
                {'detail': 'Incorrect password.'}
            )

        # Check account is active
        if not user.is_active:
            raise serializers.ValidationError(
                {'detail': 'This account has been deactivated.'}
            )

        # Generate tokens
        refresh = RefreshToken.for_user(user)

        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ('role', 'phone', 'notification_prefs')


class UserSerializer(serializers.ModelSerializer):
    """Full user representation including role from profile."""
    role = serializers.SerializerMethodField()
    is_admin = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email',
            'first_name', 'last_name',
            'role', 'is_admin',
            'date_joined', 'last_login',
        )
        read_only_fields = fields

    def get_role(self, obj) -> str:
        try:
            return obj.profile.role
        except UserProfile.DoesNotExist:
            return UserProfile.Role.STAFF

    def get_is_admin(self, obj) -> bool:
        try:
            return obj.profile.is_admin
        except UserProfile.DoesNotExist:
            return False


class LoginSerializer(serializers.Serializer):
    """Used only for Swagger docs."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)