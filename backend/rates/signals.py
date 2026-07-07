"""
Señales de rates — broadcast WebSocket cuando cambia ExchangeRate.
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

log = logging.getLogger('kapitalya.rates.signals')


@receiver(post_save, sender='rates.ExchangeRate')
def broadcast_rate_change(sender, instance, created, **kwargs):
    """
    Cuando se guarda un ExchangeRate activo (valid_until IS NULL),
    publica las tasas actualizadas al grupo WebSocket 'rates_updates'.
    """
    if instance.valid_until is not None:
        return  # tasa histórica, no activa — ignorar

    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        from .models import ExchangeRate, Currency

        layer = get_channel_layer()
        if layer is None:
            return

        # Recopilar TODAS las tasas activas (no solo la recién guardada)
        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return

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

        async_to_sync(layer.group_send)(
            'rates_updates',
            {'type': 'rates_update', 'rates': rates},
        )
        log.debug('WS_BROADCAST_RATES currencies=%d trigger=%s', len(rates), instance.currency_from.code)

    except Exception as exc:
        log.debug('WS_BROADCAST_SKIP error=%s', exc)
