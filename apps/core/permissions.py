"""
Custom DRF permission classes implementing the HeatGlow RBAC matrix.

Two roles exist:
    admin  — Gareth. Full read + write access everywhere.
    staff  — Rebecca. Read access everywhere; write access on enquiries only.

Usage:
    class MyView(APIView):
        permission_classes = [IsAdminOrReadOnly]
"""
from rest_framework.permissions import BasePermission, IsAuthenticated
from apps.accounts.models import UserProfile


def _get_role(request) -> str:
    """Extract the role from the authenticated user's profile."""
    try:
        return request.user.profile.role
    except (AttributeError, UserProfile.DoesNotExist):
        return UserProfile.Role.STAFF


class IsAdmin(BasePermission):
    """
    Allow access only to admin users (Gareth).
    Used for: settings, campaign approval, GDPR actions.
    """
    message = 'Admin access required.'

    def has_permission(self, request, view) -> bool:
        return (
            request.user
            and request.user.is_authenticated
            and _get_role(request) == UserProfile.Role.ADMIN
        )


class IsAdminOrReadOnly(BasePermission):
    """
    Read access for all authenticated users.
    Write access (POST, PUT, PATCH, DELETE) for admins only.

    Used for: customers, heatshield members, campaigns list.
    """
    message = 'Admin access required for write operations.'

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return _get_role(request) == UserProfile.Role.ADMIN


class IsAuthenticatedStaff(IsAuthenticated):
    """
    Any authenticated user (admin or staff).
    Used for: reading customers, enquiries list, dashboard.
    """
    pass


class IsAdminOrEnquiryCreate(BasePermission):
    """
    Allow POST (create enquiry) for any authenticated user.
    All other mutating methods (approve, reject) require admin.

    Used for: enquiry creation vs approval workflow.
    """
    message = 'Admin access required for this action.'

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method == 'POST':
            return True
        return _get_role(request) == UserProfile.Role.ADMIN