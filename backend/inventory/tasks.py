"""
Tareas Celery para el módulo de inventario.
"""
import logging
from celery import shared_task

log = logging.getLogger('inventory')


@shared_task(
    name='inventory.tasks.check_inventory_levels',
    bind=True,
    max_retries=3,
    acks_late=True,
    soft_time_limit=60,
    time_limit=90,
)
def check_inventory_levels(self):
    """
    Verifica niveles de inventario y crea alertas si están por debajo del mínimo.
    Reemplazada por core.tasks.check_inventory_alerts — se mantiene por compatibilidad.
    """
    log.info("TASK_START name=check_inventory_levels (delegating to InventoryAlertService)")
    try:
        from inventory.alerts import InventoryAlertService
        alerts = InventoryAlertService.check_all_inventories()
        count = len(alerts) if isinstance(alerts, list) else 0
        log.info("TASK_SUCCESS name=check_inventory_levels alerts=%d", count)
        return {'status': 'ok', 'alerts_created': count}
    except Exception as exc:
        log.error("TASK_FAILURE name=check_inventory_levels error=%s", exc)
        try:
            raise self.retry(exc=exc, countdown=60)
        except self.MaxRetriesExceededError:
            return {'status': 'error', 'error': str(exc)}
