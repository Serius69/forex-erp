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
    # BCB oficial + referencial: cada 30 min (BCB actualiza ~2x al día, pero
    # verificamos con más frecuencia por si hay conexión intermitente)
    'update-bcb-rates': {
        'task':    'rates.update_bcb_rates',
        'schedule': crontab(minute='*/30'),
        'options': {'queue': 'high', 'expires': 1800},
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
    # Modelos ML: 2 AM diario
    'train-prediction-models': {
        'task':    'core.tasks.train_prediction_models',
        'schedule': crontab(hour=2, minute=0),
        'options': {'queue': 'low'},
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