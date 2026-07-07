"""
Reusable DRF permission classes for multi-tenant SaaS isolation.

Usage in a ViewSet:
    permission_classes = [IsAuthenticated, IsCompanyMember]

Role hierarchy:
    ADMIN       → full access within company
    SUPERVISOR  → all branches read; limited write
    CASHIER     → own branch only
"""
from rest_framework.permissions import BasePermission, IsAuthenticated


class IsCompanyMember(BasePermission):
    """Allow only users who belong to the requesting company."""

    message = 'Acceso denegado: no eres miembro de esta empresa.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'company_id', None) is not None
        )


class IsAdminRole(BasePermission):
    message = 'Se requiere rol ADMIN.'

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and getattr(request.user, 'role', None) == 'ADMIN'
        )


class IsAdminOrSupervisor(BasePermission):
    message = 'Se requiere rol ADMIN o SUPERVISOR.'

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and getattr(request.user, 'role', None) in ('ADMIN', 'SUPERVISOR')
        )


class IsCashierOwnBranch(BasePermission):
    """
    CAJEROs can only read/write their own branch.
    SUPERVISOR/ADMIN bypass this check.
    """
    message = 'Cajeros solo pueden operar en su propia sucursal.'

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        role = getattr(request.user, 'role', 'CASHIER')
        if role in ('ADMIN', 'SUPERVISOR'):
            return True
        # For CAJEROs: branch param in URL or query must match user.branch
        branch_id = (
            view.kwargs.get('branch_id')
            or view.kwargs.get('branch')
            or request.query_params.get('branch')
        )
        if branch_id is None:
            return True  # no branch filter → CompanyFilterMixin will scope to user.branch
        return str(request.user.branch_id) == str(branch_id)

    def has_object_permission(self, request, view, obj):
        role = getattr(request.user, 'role', 'CASHIER')
        if role in ('ADMIN', 'SUPERVISOR'):
            return True
        # Object must belong to cashier's branch
        obj_branch = getattr(obj, 'branch_id', None) or getattr(
            getattr(obj, 'branch', None), 'id', None
        )
        return obj_branch == request.user.branch_id


class IsCompanyAdmin(IsAuthenticated, IsCompanyMember, IsAdminRole):
    """Shorthand: authenticated + company member + ADMIN role."""
    pass
