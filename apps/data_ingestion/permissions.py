"""Permission classes for the data-ingestion API.

The default cluster is read-only for authenticated users; every mutation
(register/create, compliance check, collect, manual import, review decisions,
publication) requires a staff/admin account so every write keeps a named human
in the audit trail.
"""
from rest_framework.permissions import BasePermission, IsAuthenticated


class IsStaffOrAdmin(BasePermission):
    """Deny unless the user is a Django staff/admin account."""

    message = "staff/admin privileges required for this data-ingestion operation"

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


class StaffOrReadOnly(BasePermission):
    """Authenticated users may read; staff may mutate."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.is_staff or request.user.is_superuser


class IsAuthenticatedRead(IsAuthenticated):
    """Read-only endpoints that still require an authenticated session."""