"""
Señales de inventory — broadcast WebSocket cuando cambia el stock.
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

log = logging.getLogger('kapitalya.inventory.signals')


@receiver(post_save, sender='inventory.CurrencyInventory')
def broadcast_inventory_change(sender, instance, created, **kwargs):
    """Emite evento WebSocket cuando cambia el stock de una moneda."""
    try:
        from alerts.events import broadcast_event, INVENTORY_UPDATED
        branch_id = getattr(getattr(instance, 'branch', None), 'id', None)
        broadcast_event(
            INVENTORY_UPDATED,
            {
                'currency':         instance.currency.code if instance.currency else '',
                'physical_balance': float(instance.physical_balance or 0),
                'minimum_stock':    float(instance.minimum_stock or 0),
                'branch_id':        branch_id,
            },
            branch_id=branch_id,
        )
    except Exception as exc:
        log.debug('INVENTORY_WS_BROADCAST_SKIP err=%s', exc)
