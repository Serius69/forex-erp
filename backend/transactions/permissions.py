from rest_framework.permissions import BasePermission


class CanReverseTransaction(BasePermission):
    """
    Solo admins y supervisores pueden revertir transacciones.
    También requiere el permiso explícito 'can_reverse_transaction'.
    """
    message = 'No tiene permisos para revertir transacciones.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.role in ['ADMIN', 'SUPERVISOR'] or
            request.user.has_perm('transactions.can_reverse_transaction')
        )

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        # Verificar que la transacción puede ser revertida
        if not obj.can_be_reversed():
            self.message = 'Esta transacción no puede ser revertida (completada hace más de 24h o estado incorrecto).'
            return False
        return (
            request.user.role in ['ADMIN', 'SUPERVISOR'] or
            request.user.has_perm('transactions.can_reverse_transaction')
        )


class CanViewAllBranches(BasePermission):
    """Solo admins pueden ver transacciones de todas las sucursales."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.role == 'ADMIN' or
            request.user.has_perm('transactions.can_view_all_branches')
        )