import logging
import os
from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    task_failure, task_retry, task_success,
    worker_ready, worker_shutdown, celeryd_init,
)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')

app = Celery('kapitalya')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

log = logging.getLogger('kapitalya.tasks')

# ── Beat schedule ─────────────────────────────────────────────────────────────
app.conf.beat_schedule = {
    # ── Tasas de cambio multi-fuente ───────────────────────────────────────────
    # Binance P2P: cada 5 min — fuente principal USD/BOB
    'fetch-binance-p2p': {
        'task':    'rates.fetch_binance_p2p',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'high', 'expires': 300},
    },
    # DolarBlueBolivia: cada 15 min — scraping con 8 exchanges + cross rates regionales
    'fetch-dolar-blue-bolivia': {
        'task':    'rates.fetch_dolar_blue_bolivia',
        'schedule': crontab(minute='*/15'),
        'options': {'queue': 'high', 'expires': 900},
    },
    # Todas las fuentes (integrations layer) + consenso: cada 5 min
    'fetch-all-rates': {
        'task':    'rates.fetch_all_rates',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'high', 'expires': 300},
    },
    # FX Engine: cada 5 min (después de fetch Binance)
    'run-fx-engine': {
        'task':    'rates.run_fx_engine',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'high', 'expires': 300},
    },
    # Marcar tasas primarias: cada 30 min
    'mark-primary-rates': {
        'task':    'rates.mark_primary_rates',
        'schedule': crontab(minute='*/30'),
        'options': {'queue': 'default', 'expires': 1800},
    },
    # Snapshot diario al cierre de operaciones (18:00 BOT)
    'daily-rates-snapshot': {
        'task':    'rates.create_daily_snapshot',
        'schedule': crontab(hour=18, minute=0),
        'options': {'queue': 'low'},
    },
    # Tasa paralela principal: cada 15 min desde dolarbluebolivia.click
    'fetch-parallel-rate': {
        'task':    'rates.fetch_parallel_rate',
        'schedule': crontab(minute='*/15'),
        'options': {'queue': 'high', 'expires': 900},
    },
    # Plataformas digitales: cada 60 min (estimaciones cambian poco)
    'update-digital-rates': {
        'task':    'rates.update_digital_rates',
        'schedule': crontab(minute='5', hour='*/1'),
        'options': {'queue': 'high', 'expires': 3600},
    },
    # Mercado paralelo: cada 20 min (el más volátil durante horario hábil)
    'update-parallel-rates': {
        'task':    'rates.update_parallel_rates',
        'schedule': crontab(minute='*/20'),
        'options': {'queue': 'high', 'expires': 1200},
    },
    # Legado — mantener por compatibilidad hasta migración completa
    'update-exchange-rates': {
        'task':    'rates.update_exchange_rates',
        'schedule': crontab(minute='15', hour='*/2'),
        'options': {'queue': 'default', 'expires': 7200},
    },
    # ── Motor ML ──────────────────────────────────────────────────────────────
    # Reentrenamiento diario: 2 AM (todos los modelos)
    'train-all-prediction-models': {
        'task':     'predictions.train_all_prediction_models',
        'schedule':  crontab(hour=2, minute=0),
        'options':  {'queue': 'low'},
    },
    # Compatibilidad legacy (core tasks también lanza el training)
    'train-prediction-models': {
        'task':    'core.tasks.train_prediction_models',
        'schedule': crontab(hour=2, minute=30),   # 30min después, por si acaso
        'options': {'queue': 'low'},
    },
    # Pesos del ensemble: cada 4 horas
    'refresh-ensemble-weights': {
        'task':    'predictions.refresh_ensemble_weights',
        'schedule': crontab(minute=0, hour='*/4'),
        'options': {'queue': 'default', 'expires': 14400},
    },
    # Caché de pronósticos: cada hora
    'cache-forecast-hourly': {
        'task':    'predictions.cache_forecast_hourly',
        'schedule': crontab(minute=5),   # minuto 5 de cada hora (después de actualizar tasas)
        'options': {'queue': 'default', 'expires': 3600},
    },
    # Backtesting semanal: domingos a las 3 AM
    'weekly-backtest-report': {
        'task':    'predictions.weekly_backtest_report',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),
        'options': {'queue': 'low'},
    },
    # Tuning de hiperparámetros: sábados a las 4 AM (baja prioridad)
    'weekly-hyperparameter-tuning': {
        'task':    'predictions.weekly_hyperparameter_tuning',
        'schedule': crontab(hour=4, minute=0, day_of_week=6),
        'options': {'queue': 'low'},
    },
    # Evaluación de predicciones pasadas: diaria a las 12:00
    'evaluate-predictions': {
        'task':    'predictions.evaluate_predictions',
        'schedule': crontab(hour=12, minute=0),
        'options': {'queue': 'default', 'expires': 7200},
    },
    # Inventario: cada 15 minutos
    'check-inventory-alerts': {
        'task':    'core.tasks.check_inventory_alerts',
        'schedule': crontab(minute='*/15'),
        'options': {'queue': 'high', 'expires': 900},
    },
    # Reporte diario: 11:30 PM
    'generate-daily-report': {
        'task':    'core.tasks.generate_daily_report',
        'schedule': crontab(hour=23, minute=30),
        'options': {'queue': 'low'},
    },
    # Backup: cada 6 horas
    'backup-database': {
        'task':    'core.tasks.backup_database',
        'schedule': crontab(hour='*/6'),
        'options': {'queue': 'default'},
    },
    # Health check periódico: cada 5 minutos
    'periodic-health-check': {
        'task':    'core.tasks.periodic_health_check',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'default', 'expires': 300},
    },
    # ── Detección de anomalías: cada 15 min ──────────────────────────────────
    # Cubre: capital drop, missing cash, negative balances, rate issues,
    #        spread bajo, concentración de riesgo.
    'detect-anomalies': {
        'task':    'analytics.detect_anomalies',
        'schedule': crontab(minute='*/15'),
        'options': {'queue': 'high', 'expires': 900},
    },
    # ── Snapshots diarios del sistema ─────────────────────────────────────────
    # Apertura: 08:00 — captura el estado inicial antes de operar
    'daily-opening-snapshot': {
        'task':    'snapshots.take_opening_snapshot',
        'schedule': crontab(hour=8, minute=0),
        'options': {'queue': 'low'},
    },
    # Cierre: 23:45 — captura el estado final del día (después del reporte 23:30)
    'daily-closing-snapshot': {
        'task':    'snapshots.take_closing_snapshot',
        'schedule': crontab(hour=23, minute=45),
        'options': {'queue': 'low'},
    },
    # ── Sincronización automática con Google Sheets ────────────────────────────
    # Solo activo si GOOGLE_SHEETS_AUTO_SYNC_URL está configurado.
    # Intervalo configurable via GOOGLE_SHEETS_AUTO_SYNC_INTERVAL (default 30 min).
    'google-sheets-auto-sync': {
        'task':    'data_migration.auto_sync_sheets',
        'schedule': crontab(minute='*/30'),   # sobreescribir con env si se necesita otro valor
        'options': {'queue': 'default', 'expires': 1700},
    },
    # ── Capital: posición en tiempo real y P&L ────────────────────────────────
    # Snapshot diario de posición: 23:45 (después del closing snapshot general)
    'capital-daily-snapshots': {
        'task':    'capital.save_daily_snapshots',
        'schedule': crontab(hour=23, minute=45),
        'options': {'queue': 'low'},
    },
    # Alertas de capital: cada 15 minutos
    'capital-check-alerts': {
        'task':    'capital.check_capital_alerts',
        'schedule': crontab(minute='*/15'),
        'options': {'queue': 'high', 'expires': 900},
    },
    # Actualizar P&L no realizado: cada hora (valuación a tasas actuales)
    'capital-update-unrealized-pnl': {
        'task':    'capital.update_unrealized_pnl',
        'schedule': crontab(minute=10, hour='*/1'),  # minuto 10 de cada hora
        'options': {'queue': 'default', 'expires': 3600},
    },
    # ── Anti-fraude: invalidar caché de reglas ────────────────────────────────
    # Cada 5 minutos para que cambios en admin se propaguen rápido
    'fraud-rules-cache-refresh': {
        'task':    'transactions.refresh_fraud_rules_cache',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'high', 'expires': 300},
    },
}

# ── Señales de Celery para logging ────────────────────────────────────────────

@task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, traceback=None, **kwargs):
    log.error(
        "CELERY_TASK_FAILURE task=%s id=%s error=%s",
        sender.name if sender else 'unknown', task_id, exception,
    )


@task_retry.connect
def on_task_retry(sender=None, request=None, reason=None, **kwargs):
    log.warning(
        "CELERY_TASK_RETRY task=%s id=%s reason=%s attempt=%d",
        sender.name if sender else 'unknown',
        request.id if request else '-',
        reason,
        request.retries if request else 0,
    )


@worker_ready.connect
def on_worker_ready(**kwargs):
    log.info("CELERY_WORKER_READY")


@worker_shutdown.connect
def on_worker_shutdown(**kwargs):
    log.info("CELERY_WORKER_SHUTDOWN")