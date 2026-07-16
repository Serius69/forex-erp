"""
Señales de rates — broadcast WebSocket cuando cambia ExchangeRate.

Las tareas de actualización guardan decenas de filas por corrida. Antes, el
receiver post_save re-consultaba TODAS las tasas activas y hacía un broadcast WS
completo en CADA save → O(N²) (N saves × re-query+broadcast idénticos).

Ahora se colapsa la ráfaga en UN solo broadcast, emitido en transaction.on_commit
(estado final ya comprometido), con un flag de coalescencia en caché para que el
resto de saves de la misma ráfaga no vuelvan a encolarlo. El payload del WS es
idéntico al anterior (contrato intacto).
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

log = logging.getLogger('kapitalya.rates.signals')

# Ventana (segundos) para colapsar una ráfaga de saves en un único broadcast.
_BROADCAST_COALESCE_TTL = 2
_PENDING_KEY = 'rates:broadcast:pending'


def _collect_active_rates() -> dict:
    """Recopila TODAS las tasas activas (valid_until IS NULL) hacia BOB."""
    from .models import ExchangeRate, Currency

    bob = Currency.objects.filter(code='BOB').first()
    if not bob:
        return {}

    rates = {}
    for r in (ExchangeRate.objects
              .filter(currency_to=bob, valid_until__isnull=True)
              .select_related('currency_from')):
        code  = r.currency_from.code
        mtype = r.market_type
        key   = f'{code}_{mtype}' if mtype != 'parallel' else code
        rates[key] = {
            'code':         code,
            'name':         r.currency_from.name,
            'scale_factor': r.currency_from.scale_factor,
            'market_type':  mtype,
            'buy':          float(r.buy_rate),
            'sell':         float(r.sell_rate),
            'official':     float(r.official_rate),
        }
    return rates


def _do_broadcast_rates():
    """
    Emite UN broadcast WS con el estado final de todas las tasas activas.
    Se ejecuta en transaction.on_commit. Limpia el flag de coalescencia al inicio
    para que un cambio posterior vuelva a re-armar el broadcast.
    """
    from django.core.cache import cache
    cache.delete(_PENDING_KEY)

    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if layer is None:
            return

        rates = _collect_active_rates()
        async_to_sync(layer.group_send)(
            'rates_updates',
            {'type': 'rates_update', 'rates': rates},
        )
        log.debug('WS_BROADCAST_RATES currencies=%d', len(rates))

    except Exception as exc:
        log.debug('WS_BROADCAST_SKIP error=%s', exc)


@receiver(post_save, sender='rates.ExchangeRate')
def broadcast_rate_change(sender, instance, created, **kwargs):
    """
    Cuando se guarda un ExchangeRate activo (valid_until IS NULL), programa UN
    único broadcast WS (coalescido) de todas las tasas activas.
    """
    if instance.valid_until is not None:
        return  # tasa histórica, no activa — ignorar

    from django.core.cache import cache
    from django.db import transaction as db_transaction

    # Solo el primer save de la ráfaga encola el broadcast; el resto lo colapsa
    # (cache.add es atómico: True solo si la clave no existía).
    if not cache.add(_PENDING_KEY, '1', timeout=_BROADCAST_COALESCE_TTL):
        return

    db_transaction.on_commit(_do_broadcast_rates)
