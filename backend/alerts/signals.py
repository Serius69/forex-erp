"""
Señales de alerts — broadcast WebSocket cuando se crea una alerta.
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

log = logging.getLogger('kapitalya.alerts.signals')


@receiver(post_save, sender='alerts.AlertLog')
def broadcast_alert_triggered(sender, instance, created, **kwargs):
    """Emite evento WebSocket cuando se persiste una alerta nueva."""
    if not created:
        return
    try:
        from alerts.events import broadcast_event, ALERT_TRIGGERED
        branch_id = getattr(getattr(instance, 'branch', None), 'id', None)
        broadcast_event(
            ALERT_TRIGGERED,
            {
                'alert': {
                    'id':         instance.pk,
                    'alert_type': getattr(instance, 'alert_type', ''),
                    'severity':   getattr(instance, 'severity', 'INFO'),
                    'title':      getattr(instance, 'title', ''),
                    'message':    getattr(instance, 'message', ''),
                },
            },
            branch_id=branch_id,
        )
    except Exception as exc:
        log.debug('ALERT_WS_BROADCAST_SKIP err=%s', exc)
