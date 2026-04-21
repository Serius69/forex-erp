from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'ADMIN'
        )


class IsSupervisor(BasePermission):
    """Only SUPERVISOR role (not ADMIN). Use IsAdminOrSupervisor for broader access."""
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'SUPERVISOR'
        )


class IsAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role in ['ADMIN', 'SUPERVISOR']
        )


class IsAdminOrSupervisorOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return request.user.role in ['ADMIN', 'SUPERVISOR']


class IsSameBranch(BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role == 'ADMIN':
            return True
        obj_branch  = getattr(obj, 'branch', None) or getattr(obj, 'branch_id', None)
        user_branch = getattr(request.user, 'branch', None)
        if obj_branch and user_branch:
            return obj_branch == user_branch
        return False


class IsCashier(BasePermission):
    """Any authenticated user (all roles can be cashier-level)."""
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role in ['ADMIN', 'SUPERVISOR', 'CASHIER']
        )
