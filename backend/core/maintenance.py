"""
Modo de mantenimiento del sistema Kapitalya.

Funcionalidades:
  - Activar/desactivar modo mantenimiento (bloquea transacciones nuevas)
  - Limpieza de cache (Redis + Django cache)
  - Recálculo completo del sistema (snapshots de capital, WAC de inventario)
  - Estado del sistema (health check extendido)

El estado de mantenimiento se almacena en Django cache (Redis en prod,
memoria en dev). La clave MAINTENANCE_KEY persiste hasta que se desactiva.
"""
from __future__ import annotations
import logging
from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger('kapitalya.maintenance')

MAINTENANCE_KEY    = 'system:maintenance_mode'
MAINTENANCE_TTL    = 60 * 60 * 8   # máximo 8h por seguridad — requiere renovación


def is_maintenance_active() -> bool:
    """Retorna True si el modo mantenimiento está activo."""
    return bool(cache.get(MAINTENANCE_KEY))


def get_maintenance_info() -> dict | None:
    """Retorna el dict con info del mantenimiento activo, o None."""
    return cache.get(MAINTENANCE_KEY)


def activate_maintenance(activated_by: str, reason: str) -> dict:
    """Activa el modo mantenimiento."""
    info = {
        'active':       True,
        'activated_by': activated_by,
        'reason':       reason,
        'activated_at': timezone.now().isoformat(),
    }
    cache.set(MAINTENANCE_KEY, info, MAINTENANCE_TTL)
    log.warning(
        "MAINTENANCE_ACTIVATED by=%s reason=%s", activated_by, reason
    )
    return info


def deactivate_maintenance() -> None:
    """Desactiva el modo mantenimiento."""
    cache.delete(MAINTENANCE_KEY)
    log.info("MAINTENANCE_DEACTIVATED")


# ── Middleware ────────────────────────────────────────────────────────────────

class MaintenanceModeMiddleware:
    """
    Si el modo mantenimiento está activo, rechaza todas las peticiones
    excepto las de administradores y el endpoint de mantenimiento mismo.
    """
    BYPASS_PATHS = [
        '/api/maintenance/',
        '/api/users/login/',
        '/api/users/me/',
        '/admin/',
        '/health/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        info = get_maintenance_info()
        if not info:
            return self.get_response(request)

        # Bypass para rutas de sistema
        path = request.path_info
        if any(path.startswith(bp) for bp in self.BYPASS_PATHS):
            return self.get_response(request)

        # Bypass para administradores autenticados
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and getattr(user, 'role', None) == 'ADMIN':
            return self.get_response(request)

        # Bloquear
        from django.http import JsonResponse
        return JsonResponse({
            'error':        'Sistema en mantenimiento',
            'reason':       info.get('reason', ''),
            'activated_at': info.get('activated_at', ''),
            'retry_after':  300,
        }, status=503)


# ── Operaciones de mantenimiento ──────────────────────────────────────────────

def clear_all_caches() -> dict:
    """Limpia todas las cachés del sistema."""
    results = {}

    # Django cache (Redis o memoria)
    try:
        cache.clear()
        results['django_cache'] = 'OK'
        log.info("MAINTENANCE_CACHE_CLEARED")
    except Exception as exc:
        results['django_cache'] = f'ERROR: {exc}'
        log.error("MAINTENANCE_CACHE_CLEAR_FAILED error=%s", exc)

    # Cache de tasas de cambio (claves específicas)
    rate_keys = [
        'live_rates_all', 'live_rates_parallel', 'live_rates_official',
        'arbitrage_all_0.5',
    ]
    for key in rate_keys:
        cache.delete(key)

    results['rate_caches'] = 'cleared'
    return results


def recalculate_system(branch=None) -> dict:
    """
    Recálculo completo del sistema:
    1. Recalcula el WAC (costo promedio ponderado) de inventario
    2. Genera un snapshot de capital con los datos recalculados
    3. Verifica consistencia de transacciones vs inventario
    """
    results = {'steps': [], 'errors': []}

    # 1. Recalcular WAC
    try:
        from inventory.models import CurrencyInventory
        qs = CurrencyInventory.objects.all()
        if branch:
            qs = qs.filter(branch=branch)

        updated = 0
        for inv in qs.select_related('currency'):
            inv.recalculate_wac()
            updated += 1
        results['steps'].append(f'WAC recalculado: {updated} inventarios')
    except Exception as exc:
        results['errors'].append(f'WAC: {exc}')

    # 2. Verificar consistencia inventario vs transacciones
    try:
        report = _verify_inventory_consistency(branch)
        results['steps'].append(f"Consistencia: {report}")
    except Exception as exc:
        results['errors'].append(f'Consistencia: {exc}')

    # 3. Limpiar cache post-recálculo
    clear_all_caches()
    results['steps'].append('Cache limpiada')

    results['success'] = len(results['errors']) == 0
    results['completed_at'] = timezone.now().isoformat()
    log.info("MAINTENANCE_RECALC_DONE steps=%d errors=%d", len(results['steps']), len(results['errors']))
    return results


def _verify_inventory_consistency(branch=None) -> str:
    """Verifica que el inventario coincida con las transacciones acumuladas."""
    from inventory.models import CurrencyInventory
    from transactions.models import Transaction
    from django.db.models import Sum, Q
    from decimal import Decimal

    discrepancies = 0
    qs = CurrencyInventory.objects.select_related('currency', 'branch')
    if branch:
        qs = qs.filter(branch=branch)

    for inv in qs:
        if inv.currency.code == 'BOB':
            continue

        # Total comprado (BUY) - Total vendido (SELL)
        txs = Transaction.objects.filter(
            currency_from=inv.currency,
            branch=inv.branch,
            status='COMPLETED',
        )
        total_in  = txs.filter(transaction_type='BUY').aggregate(
            s=Sum('amount_from'))['s'] or Decimal('0')
        total_out = txs.filter(transaction_type='SELL').aggregate(
            s=Sum('amount_from'))['s'] or Decimal('0')

        expected = total_in - total_out
        actual   = inv.total_balance
        diff     = abs(expected - actual)

        if diff > Decimal('1'):   # tolerancia 1 unidad para redondeos
            log.warning(
                "INVENTORY_DISCREPANCY currency=%s branch=%s expected=%s actual=%s diff=%s",
                inv.currency.code, inv.branch.code, expected, actual, diff,
            )
            discrepancies += 1

    return f'{discrepancies} discrepancias' if discrepancies else 'OK'
