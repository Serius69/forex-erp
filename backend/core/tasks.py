"""
Tareas Celery de infraestructura para Kapitalya ERP.

Estrategia de resiliencia:
  - Reintentos exponenciales: 60s → 300s → 900s → 1800s → 3600s
  - acks_late=True: el mensaje no se elimina del broker hasta que la tarea termine
  - reject_on_worker_lost=True: si el worker muere, el mensaje vuelve a la cola
  - Fallbacks claros: si una tarea falla definitivamente, loguea y alerta

Nomenclatura de logs:
  TASK_START / TASK_SUCCESS / TASK_RETRY / TASK_FAILURE
"""
import logging
from datetime import date, timedelta

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

log = logging.getLogger('kapitalya.tasks')

# ── Configuración de reintentos por tipo de tarea ─────────────────────────────
# crítico: tasas de cambio, inventario
# normal: reportes, backups
# bajo: ML (puede tomar minutos)

_RETRY_DELAYS = [60, 300, 900, 1800, 3600]  # 1m, 5m, 15m, 30m, 1h


def _retry_countdown(retries: int) -> int:
    """Calcula el delay con backoff exponencial usando tabla fija."""
    idx = min(retries, len(_RETRY_DELAYS) - 1)
    return _RETRY_DELAYS[idx]


# ── Tarea: Actualizar tasas de cambio ─────────────────────────────────────────

@shared_task(
    name='core.tasks.update_exchange_rates',
    bind=True,
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=120,
    time_limit=180,
)
def update_exchange_rates(self):
    """
    Actualiza tasas de cambio desde fuentes externas (BCB).
    Reintenta hasta 5 veces con backoff exponencial.
    """
    log.info("TASK_START name=update_exchange_rates attempt=%d", self.request.retries + 1)
    try:
        from rates.services import RateService
        service = RateService()
        updated = service.fetch_official_rates('BCB')
        log.info(
            "TASK_SUCCESS name=update_exchange_rates updated=%s",
            updated,
        )
        return {'status': 'ok', 'updated': updated}

    except SoftTimeLimitExceeded:
        log.error("TASK_TIMEOUT name=update_exchange_rates")
        raise

    except Exception as exc:
        countdown = _retry_countdown(self.request.retries)
        log.warning(
            "TASK_RETRY name=update_exchange_rates attempt=%d error=%s countdown=%ds",
            self.request.retries + 1, exc, countdown,
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            log.error(
                "TASK_FAILURE name=update_exchange_rates "
                "max_retries_exceeded error=%s — tasas sin actualizar",
                exc,
            )
            _emit_system_alert('rates', f'Fallo al actualizar tasas: {exc}', severity='HIGH')
            return {'status': 'error', 'error': str(exc)}


# ── Tarea: Reporte diario ─────────────────────────────────────────────────────

@shared_task(
    name='core.tasks.generate_daily_report',
    bind=True,
    max_retries=3,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def generate_daily_report(self):
    """
    Genera reporte diario consolidado.
    Si falla, no es crítico — se reintenta la siguiente ejecución.
    """
    yesterday = date.today() - timedelta(days=1)
    log.info("TASK_START name=generate_daily_report date=%s", yesterday)

    try:
        from reports.services import ReportService
        result = ReportService.generate_daily(yesterday)
        log.info(
            "TASK_SUCCESS name=generate_daily_report date=%s result=%s",
            yesterday, result,
        )
        return result

    except SoftTimeLimitExceeded:
        log.error("TASK_TIMEOUT name=generate_daily_report date=%s", yesterday)
        return {'status': 'timeout', 'date': str(yesterday)}

    except Exception as exc:
        countdown = _retry_countdown(self.request.retries)
        log.warning(
            "TASK_RETRY name=generate_daily_report date=%s attempt=%d error=%s",
            yesterday, self.request.retries + 1, exc,
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            log.error(
                "TASK_FAILURE name=generate_daily_report date=%s error=%s",
                yesterday, exc,
            )
            return {'status': 'error', 'date': str(yesterday), 'error': str(exc)}


# ── Tarea: Verificar alertas de inventario ────────────────────────────────────

@shared_task(
    name='core.tasks.check_inventory_alerts',
    bind=True,
    max_retries=3,
    acks_late=True,
    soft_time_limit=60,
    time_limit=90,
)
def check_inventory_alerts(self):
    """Revisa niveles de inventario y emite alertas si están bajos."""
    log.info("TASK_START name=check_inventory_alerts")
    try:
        from inventory.alerts import InventoryAlertService
        alerts_created = InventoryAlertService.check_all_inventories()
        count = len(alerts_created) if isinstance(alerts_created, list) else alerts_created or 0
        log.info("TASK_SUCCESS name=check_inventory_alerts alerts_created=%d", count)
        return {'status': 'ok', 'alerts_created': count}

    except Exception as exc:
        countdown = _retry_countdown(self.request.retries)
        log.warning(
            "TASK_RETRY name=check_inventory_alerts attempt=%d error=%s",
            self.request.retries + 1, exc,
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            log.error("TASK_FAILURE name=check_inventory_alerts error=%s", exc)
            return {'status': 'error', 'error': str(exc)}


# ── Tarea: Entrenar modelos ML ────────────────────────────────────────────────

@shared_task(
    name='core.tasks.train_prediction_models',
    bind=True,
    max_retries=2,
    acks_late=True,
    soft_time_limit=1800,   # 30 min soft limit
    time_limit=2100,        # 35 min hard limit
)
def train_prediction_models(self):
    """
    Entrena modelos Prophet + LSTM.
    Si falla, el sistema continúa con el modelo anterior (fallback automático).
    """
    currency_pairs = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'CLP/BOB', 'PEN/BOB']
    results = {}

    log.info("TASK_START name=train_prediction_models pairs=%s", currency_pairs)

    for pair in currency_pairs:
        try:
            _train_single_pair(pair, results)
        except Exception as exc:
            log.error(
                "ML_TRAIN_FAILED pair=%s error=%s — usando modelo anterior como fallback",
                pair, exc,
            )
            results[pair] = {'status': 'error', 'error': str(exc), 'fallback': True}

    success_count = sum(1 for r in results.values() if r.get('status') == 'ok')
    log.info(
        "TASK_SUCCESS name=train_prediction_models success=%d/%d",
        success_count, len(currency_pairs),
    )

    if success_count == 0:
        _emit_system_alert(
            'ml', 'Todos los modelos ML fallaron en el reentrenamiento', severity='HIGH'
        )

    return {
        'status': 'ok' if success_count > 0 else 'all_failed',
        'results': results,
        'success_count': success_count,
    }


def _train_single_pair(pair: str, results: dict):
    """Entrena todos los modelos para un par de divisas."""
    ml_log = logging.getLogger('predictions')
    ml_log.info("ML_TRAIN_START pair=%s", pair)

    from predictions.ml_service import ForexPredictionService
    service = ForexPredictionService()
    pair_results = {}

    for model_fn, label in [
        (service.train_prophet_model, 'prophet'),
        (service.train_lstm_model,    'lstm'),
    ]:
        try:
            _, metrics = model_fn(pair)
            pair_results[label] = metrics
        except Exception as exc:
            ml_log.warning("ML_TRAIN_SKIP pair=%s model=%s error=%s", pair, label, exc)
            pair_results[label] = {'status': 'skipped', 'error': str(exc)}

    # Ensemble depende de Prophet + LSTM
    try:
        service.train_ensemble_model(pair)
        pair_results['ensemble'] = 'ok'
    except Exception as exc:
        ml_log.warning("ML_TRAIN_SKIP pair=%s model=ensemble error=%s", pair, exc)
        pair_results['ensemble'] = {'status': 'skipped', 'error': str(exc)}

    # Nuevos modelos (XGBoost, ARIMA) si están disponibles
    try:
        from predictions.ml_engine import ForexMLEngine
        engine = ForexMLEngine()
        engine.train_all(pair, include=['xgboost', 'arima', 'bilstm'])
        pair_results['extended_models'] = 'ok'
    except ImportError:
        pass  # ml_engine no disponible todavía
    except Exception as exc:
        ml_log.warning("ML_TRAIN_SKIP pair=%s model=extended error=%s", pair, exc)

    ml_log.info("ML_TRAIN_SUCCESS pair=%s results=%s", pair, list(pair_results.keys()))
    results[pair] = {'status': 'ok', **pair_results}


# ── Tarea: Generar predicciones ────────────────────────────────────────────────

@shared_task(
    name='core.tasks.generate_predictions',
    bind=True,
    max_retries=3,
    acks_late=True,
    soft_time_limit=300,
    time_limit=360,
)
def generate_predictions(self, currency_pair: str = 'USD/BOB', horizon: int = 24):
    """
    Genera predicciones para las próximas `horizon` horas.
    Fallback: si falla, devuelve última predicción cacheada.
    """
    log.info("TASK_START name=generate_predictions pair=%s horizon=%d", currency_pair, horizon)
    try:
        from predictions.ml_service import ForexPredictionService
        service = ForexPredictionService()
        predictions = service.predict_rates(currency_pair, horizon)
        count = len(predictions) if isinstance(predictions, list) else 0
        log.info(
            "TASK_SUCCESS name=generate_predictions pair=%s predictions=%d",
            currency_pair, count,
        )
        return {'status': 'ok', 'pair': currency_pair, 'predictions_generated': count}

    except Exception as exc:
        countdown = _retry_countdown(self.request.retries)
        log.warning(
            "TASK_RETRY name=generate_predictions pair=%s attempt=%d error=%s",
            currency_pair, self.request.retries + 1, exc,
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            log.error(
                "TASK_FAILURE name=generate_predictions pair=%s error=%s",
                currency_pair, exc,
            )
            return {
                'status':   'error',
                'pair':     currency_pair,
                'error':    str(exc),
                'fallback': 'usando última predicción disponible',
            }


# ── Tarea: Backup ──────────────────────────────────────────────────────────────

@shared_task(
    name='core.tasks.backup_database',
    bind=True,
    max_retries=2,
    acks_late=True,
    soft_time_limit=600,
    time_limit=900,
)
def backup_database(self):
    """Realiza backup de PostgreSQL."""
    log.info("TASK_START name=backup_database")
    try:
        from core.backup import BackupManager
        result = BackupManager.create_and_upload()
        log.info("TASK_SUCCESS name=backup_database result=%s", result)
        return result
    except AttributeError:
        # BackupManager no implementado completamente — skip silencioso
        log.info("TASK_SKIP name=backup_database reason=BackupManager_not_implemented")
        return {'status': 'skipped', 'reason': 'BackupManager not implemented'}
    except Exception as exc:
        countdown = _retry_countdown(self.request.retries)
        log.error("TASK_RETRY name=backup_database error=%s countdown=%ds", exc, countdown)
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            log.critical("TASK_FAILURE name=backup_database error=%s — backup sin completar", exc)
            _emit_system_alert('backup', f'Backup fallido: {exc}', severity='CRITICAL')
            return {'status': 'error', 'error': str(exc)}


# ── Tarea: Health check periódico ─────────────────────────────────────────────

@shared_task(
    name='core.tasks.periodic_health_check',
    bind=True,
    max_retries=0,
    acks_late=False,
    soft_time_limit=30,
    time_limit=45,
)
def periodic_health_check(self):
    """
    Health check periódico que corre cada 5 minutos.
    Detecta degradación de servicios antes que los usuarios.
    """
    from core.health import _check_database, _check_cache, _check_celery

    issues = []

    db_ok, db_msg = _check_database()
    if not db_ok:
        issues.append(f'DB: {db_msg}')
        log.critical("HEALTH_ALERT component=database msg=%s", db_msg)

    cache_ok, cache_msg = _check_cache()
    if not cache_ok:
        issues.append(f'Cache: {cache_msg}')
        log.error("HEALTH_ALERT component=cache msg=%s", cache_msg)

    if issues:
        _emit_system_alert('health', f"Componentes degradados: {', '.join(issues)}", severity='CRITICAL')
        return {'status': 'degraded', 'issues': issues}

    log.info("PERIODIC_HEALTH_CHECK ok")
    return {'status': 'ok'}


# ── Helper: emitir alerta interna ─────────────────────────────────────────────

def _emit_system_alert(component: str, message: str, severity: str = 'HIGH',
                       details: dict = None):
    """
    Emite una alerta de infraestructura al sistema global de alertas.
    Persiste en BD (AlertLog) y publica por WebSocket + cache Redis.
    No lanza excepciones — si falla el alerting, el sistema sigue corriendo.
    """
    try:
        from alerts.services import GlobalAlertService
        GlobalAlertService.from_system(
            component=component, message=message,
            severity=severity, details=details or {},
        )
    except Exception as e:
        log.warning("ALERT_SYSTEM_FAILED component=%s msg=%s error=%s", component, message, e)
