# core/permissions.py
"""
Clases de permisos RBAC para DRF.

Jerarquía de roles:
    ADMIN > SUPERVISOR > CASHIER

Uso en vistas:
    from core.permissions import IsAdmin, IsAdminOrSupervisor, BranchAccessPermission

    class TransactionViewSet(ModelViewSet):
        permission_classes = [IsAuthenticated, BranchAccessPermission]

    @api_view(['POST'])
    @permission_classes([IsAuthenticated, IsAdminOrSupervisor])
    def reverse_transaction(request, pk): ...
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS


# ─────────────────────────────────────────────────────────────────────────────
# Role-level permissions
# ─────────────────────────────────────────────────────────────────────────────

class IsAdmin(BasePermission):
    """Solo ADMIN puede acceder."""
    message = 'Se requiere rol ADMIN.'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            getattr(request.user, 'role', None) == 'ADMIN'
        )


class IsSupervisor(BasePermission):
    """Solo SUPERVISOR puede acceder."""
    message = 'Se requiere rol SUPERVISOR.'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            getattr(request.user, 'role', None) == 'SUPERVISOR'
        )


class IsAdminOrSupervisor(BasePermission):
    """ADMIN o SUPERVISOR."""
    message = 'Se requiere rol ADMIN o SUPERVISOR.'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            getattr(request.user, 'role', None) in ('ADMIN', 'SUPERVISOR')
        )


class IsCashierOrAbove(BasePermission):
    """CASHIER, SUPERVISOR o ADMIN (todos los roles autenticados)."""
    message = 'Se requiere autenticación con rol válido.'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            getattr(request.user, 'role', None) in ('ADMIN', 'SUPERVISOR', 'CASHIER')
        )


# ─────────────────────────────────────────────────────────────────────────────
# Read-only for cashiers — mutations require supervisor+
# ─────────────────────────────────────────────────────────────────────────────

class ReadOnlyForCashier(BasePermission):
    """
    CASHIER → solo lectura (GET, HEAD, OPTIONS).
    SUPERVISOR / ADMIN → acceso completo.
    """
    message = 'Los cajeros solo tienen acceso de lectura.'

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return getattr(request.user, 'role', None) in ('ADMIN', 'SUPERVISOR')


# ─────────────────────────────────────────────────────────────────────────────
# Branch-scoped access
# ─────────────────────────────────────────────────────────────────────────────

class BranchAccessPermission(BasePermission):
    """
    Garantiza que los usuarios sin rol ADMIN solo accedan a datos
    de su propia sucursal.

    ADMIN puede ver cualquier sucursal (con ?all_branches=true).
    SUPERVISOR y CASHIER: solo su branch.

    La lógica de filtrado debe implementarse en las vistas usando
    get_queryset() con request.user.branch.
    """
    message = 'No tiene acceso a datos de esta sucursal.'

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        # ADMIN siempre pasa — el filtro de branch es opcional para ellos
        if getattr(user, 'role', None) == 'ADMIN':
            return True
        # Otros roles necesitan estar asignados a una sucursal
        return bool(getattr(user, 'branch_id', None))

    def has_object_permission(self, request, view, obj):
        user = request.user
        if getattr(user, 'role', None) == 'ADMIN':
            return True
        user_branch = getattr(user, 'branch_id', None)
        obj_branch  = getattr(obj, 'branch_id', None)
        if obj_branch is None:
            return True  # Objeto sin sucursal → accesible
        return user_branch == obj_branch


# ─────────────────────────────────────────────────────────────────────────────
# Transaction-specific permissions
# ─────────────────────────────────────────────────────────────────────────────

class CanReverseTransaction(BasePermission):
    """Solo ADMIN o SUPERVISOR pueden revertir transacciones."""
    message = 'Solo ADMIN o SUPERVISOR pueden revertir transacciones.'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            getattr(request.user, 'role', None) in ('ADMIN', 'SUPERVISOR')
        )


class CanViewAllBranches(BasePermission):
    """Solo ADMIN puede ver transacciones de todas las sucursales."""
    message = 'Solo ADMIN puede ver datos globales de todas las sucursales.'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            getattr(request.user, 'role', None) == 'ADMIN'
        )


# ─────────────────────────────────────────────────────────────────────────────
# Report / analytics permissions
# ─────────────────────────────────────────────────────────────────────────────

class CanGenerateReports(BasePermission):
    """Reportes ASFI y ejecutivos: ADMIN o SUPERVISOR."""
    message = 'Se requiere rol ADMIN o SUPERVISOR para generar reportes.'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            getattr(request.user, 'role', None) in ('ADMIN', 'SUPERVISOR')
        )


class CanAccessAnalytics(BasePermission):
    """
    Analytics: lectura para todos los roles;
    escritura (snapshot manual) solo ADMIN/SUPERVISOR.
    """
    message = 'Acceso denegado al módulo de analytics.'

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return getattr(request.user, 'role', None) in ('ADMIN', 'SUPERVISOR')
