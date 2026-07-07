# transactions/permissions.py
from rest_framework.permissions import BasePermission
from rest_framework.throttling import UserRateThrottle


# ── Permisos existentes ────────────────────────────────────────────────────────

class CanReverseTransaction(BasePermission):
    """Solo admins y supervisores pueden revertir transacciones."""
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


# ── Nuevos permisos granulares ─────────────────────────────────────────────────

class CanApproveHighValue(BasePermission):
    """
    Puede aprobar transacciones de alto valor que el motor antifraude
    marcó como REQUIRE_APPROVAL.
    Requiere rol ADMIN o SUPERVISOR, o permiso explícito.
    """
    message = 'No tiene permisos para aprobar transacciones de alto valor.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.role in ('ADMIN', 'SUPERVISOR') or
            request.user.has_perm('transactions.can_approve_high_value')
        )

    def has_object_permission(self, request, view, obj):
        if not self.has_permission(request, view):
            return False
        return obj.approval_required and obj.status not in ('COMPLETED', 'CANCELLED', 'REVERSED')


class CanOverrideFraudFlag(BasePermission):
    """
    Puede anular un flag de fraude y forzar la aprobación de una transacción
    que el motor marcó como BLOCK.  Solo ADMIN.
    """
    message = 'Solo administradores pueden anular flags de fraude.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.role == 'ADMIN' or
            request.user.has_perm('transactions.can_override_fraud_flag')
        )


class CanViewAuditTrail(BasePermission):
    """
    Acceso al trail de auditoría de transacciones.
    ADMIN, SUPERVISOR o usuarios con permiso explícito.
    """
    message = 'No tiene permisos para ver el trail de auditoría.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.role in ('ADMIN', 'SUPERVISOR') or
            request.user.has_perm('transactions.can_view_audit_trail')
        )


class CanUseManualRate(BasePermission):
    """
    Puede aplicar una tasa de cambio manual que difiere de la tasa de mercado.
    La justificación es obligatoria (validada en el serializer).
    """
    message = 'No tiene permisos para aplicar tasa manual.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.role == 'ADMIN' or
            request.user.has_perm('transactions.can_manual_rate')
        )


# ── Throttling por rol ─────────────────────────────────────────────────────────

class CashierThrottle(UserRateThrottle):
    """60 transacciones por minuto para cajeros."""
    scope = 'cashier_tx'
    rate  = '60/min'


class SupervisorThrottle(UserRateThrottle):
    """200 operaciones por minuto para supervisores y admins."""
    scope = 'supervisor_tx'
    rate  = '200/min'


def get_tx_throttle_classes(user):
    """Devuelve la clase de throttle correcta según el rol del usuario."""
    if user and user.role in ('ADMIN', 'SUPERVISOR'):
        return [SupervisorThrottle]
    return [CashierThrottle]
