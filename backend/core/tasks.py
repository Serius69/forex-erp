"""
Tareas Celery Beat programadas:
  - update_exchange_rates:    cada 30 min  → actualiza tasas desde BCB/API externa
  - generate_daily_report:    00:05 diario → genera reporte Excel + PDF del día anterior
  - check_inventory_alerts:   cada 15 min  → detecta stock bajo y crea alertas
  - train_ml_models:          03:00 diario → re-entrena modelos de predicción
  - backup_database:          02:00 diario → backup PostgreSQL a S3
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='update_exchange_rates', bind=True, max_retries=3)
def update_exchange_rates(self):
    """Obtiene tasas actuales del BCB y APIs externas y las guarda en BD + cache."""
    try:
        from rates.services import RateService
        updated = RateService.fetch_and_update_all()
        logger.info(f'Tasas actualizadas: {updated} divisas')
        return {'status': 'ok', 'updated': updated}
    except Exception as exc:
        logger.error(f'Error actualizando tasas: {exc}')
        raise self.retry(exc=exc, countdown=60)


@shared_task(name='generate_daily_report', bind=True)
def generate_daily_report(self):
    """Genera reporte diario Excel y PDF del día anterior."""
    try:
        from reports.services import ReportService
        from datetime import date, timedelta
        yesterday = date.today() - timedelta(days=1)
        result = ReportService.generate_daily(yesterday)
        logger.info(f'Reporte generado para {yesterday}')
        return result
    except Exception as exc:
        logger.error(f'Error generando reporte: {exc}')
        return {'status': 'error', 'error': str(exc)}


@shared_task(name='check_inventory_alerts', bind=True)
def check_inventory_alerts(self):
    """Revisa inventario y genera alertas si el stock está bajo mínimo."""
    try:
        from inventory.services import InventoryAlertService
        alerts_created = InventoryAlertService.check_all()
        logger.info(f'Alertas de inventario verificadas: {alerts_created} nuevas')
        return {'status': 'ok', 'alerts_created': alerts_created}
    except Exception as exc:
        logger.error(f'Error verificando inventario: {exc}')
        return {'status': 'error', 'error': str(exc)}


@shared_task(name='train_ml_models', bind=True)
def train_ml_models(self):
    """Re-entrena los modelos de predicción (Prophet, RF, LSTM) con datos recientes."""
    try:
        from predictions.ml_service import ForexPredictor
        for currency_pair in ['USD/BOB', 'EUR/BOB', 'BRL/BOB']:
            predictor = ForexPredictor(currency_pair)
            predictor.train()
            logger.info(f'Modelo entrenado: {currency_pair}')
        return {'status': 'ok'}
    except Exception as exc:
        logger.error(f'Error entrenando modelos: {exc}')
        return {'status': 'error', 'error': str(exc)}


@shared_task(name='backup_database', bind=True)
def backup_database(self):
    """Realiza backup de PostgreSQL y lo sube a S3."""
    try:
        from core.backup import BackupManager
        result = BackupManager.create_and_upload()
        logger.info(f'Backup completado: {result}')
        return result
    except Exception as exc:
        logger.error(f'Error en backup: {exc}')
        return {'status': 'error', 'error': str(exc)}
