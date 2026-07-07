# tarjetas/signals.py
"""
Signal de integración del módulo tarjetas con el módulo de capital.

Cuando se registra una venta de tarjetas (o se anula), el inventario de tarjetas
cambia su valor como activo. Disparamos una tarea Celery de baja prioridad para
que el servicio de capital recalcule la posición de la sucursal afectada.

El capital ya incluye tarjetas telefónicas como activo D en position_service.py:
    D) TARJETAS TELEFÓNICAS = Σ (stock × precio_venta_prom_últimas_30_ventas)
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import VentaTarjeta

log = logging.getLogger('tarjetas')


@receiver(post_save, sender=VentaTarjeta)
def actualizar_capital_tras_venta(sender, instance: VentaTarjeta, created: bool, **kwargs):
    """
    Dispara el recálculo de posición de capital de la sucursal afectada.

    Se ejecuta tanto en creación (venta completada) como en actualización
    (anulación de venta). Usa on_commit para no ejecutar dentro de la
    transacción atómica del servicio FIFO.
    """
    if not instance.branch_id:
        return

    branch_id = instance.branch_id

    def _dispatch():
        try:
            from .tasks import refresh_capital_tras_venta_tarjeta
            refresh_capital_tras_venta_tarjeta.apply_async(
                args=[branch_id],
                queue='default',
                countdown=2,
            )
        except Exception:
            # Silencioso cuando Celery/Redis no está disponible en dev
            pass

    from django.db import transaction
    transaction.on_commit(_dispatch)
