from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    """Solo administradores."""
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'ADMIN'
        )


class IsAdminOrSupervisor(BasePermission):
    """Administradores y supervisores."""
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role in ['ADMIN', 'SUPERVISOR']
        )


class IsAdminOrSupervisorOrReadOnly(BasePermission):
    """
    Admins y supervisores pueden escribir.
    Cajeros solo pueden leer (GET, HEAD, OPTIONS).
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return request.user.role in ['ADMIN', 'SUPERVISOR']


class IsSameBranch(BasePermission):
    """
    Admins ven todo.
    El resto solo ve objetos de su propia sucursal.
    """
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role == 'ADMIN':
            return True
        # El objeto debe tener atributo branch o branch_id
        obj_branch = getattr(obj, 'branch', None) or getattr(obj, 'branch_id', None)
        user_branch = getattr(request.user, 'branch', None)
        if obj_branch and user_branch:
            return obj_branch == user_branch
        return False


class IsCashier(BasePermission):
    """Cualquier usuario autenticado con rol cajero o superior."""
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role in ['ADMIN', 'SUPERVISOR', 'CASHIER']
        )