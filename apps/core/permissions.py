"""Object-level permission classes.

Every farmer-facing resource points at a ``farm``; these permissions make it
impossible for a user to read or modify another user's data.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsOwnerOrReadOnly(BasePermission):
    """Allow safe methods to anyone authenticated; unsafe only to the owner."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        owner = getattr(obj, "user", None) or getattr(obj, "owner", None)
        return bool(owner and owner == request.user)


class IsFarmOwner(BasePermission):
    """Require that the object belongs to a farm owned by the requesting user.

    Used by generic nested views where the object carries a ``farm`` relation.
    """

    def has_object_permission(self, request, view, obj):
        farm = getattr(obj, "farm", None)
        if farm is None:
            return True
        return bool(farm and farm.user_id == request.user.id)


class IsFarmerProfile(BasePermission):
    """Require an authenticated user with a complete farmer profile."""

    message = "A complete farmer profile is required."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if not hasattr(user, "farmer_profile"):
            return False
        return True