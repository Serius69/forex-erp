# tarjetas/tasks.py
import logging
from celery import shared_task

log = logging.getLogger('tarjetas')


@shared_task(
    bind=True,
    name='tarjetas.refresh_capital_tras_venta',
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def refresh_capital_tras_venta_tarjeta(self, branch_id: int):
    """
    Recalcula la posición de capital de la sucursal tras una venta/anulación
    de tarjetas. Las tarjetas forman parte del activo D en CapitalPositionService.
    """
    try:
        from capital.position_service import CapitalPositionService
        svc = CapitalPositionService()
        svc.get_real_time_position(branch_id=branch_id, force=True)
        log.info("Capital recalculado para branch=%s tras movimiento de tarjetas", branch_id)
    except Exception as exc:
        log.error("Error recalculando capital branch=%s: %s", branch_id, exc)
        raise self.retry(exc=exc)
