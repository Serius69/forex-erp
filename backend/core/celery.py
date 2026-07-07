import logging
import os
from celery import Celery
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
# NOTA (2026-07-07): el beat_schedule que antes se asignaba aquí vía
# `app.conf.beat_schedule = {...}` era CONFIG MUERTA: `config_from_object`
# con namespace CELERY hace que `CELERY_BEAT_SCHEDULE` de
# `core/settings/base.py` sea la fuente de verdad (verificado empíricamente:
# el schedule efectivo contiene las 18 claves de settings, ninguna de las que
# definía este archivo). Además, en runtime beat usa DatabaseScheduler
# (django_celery_beat), sembrado por la data migration
# `analytics/migrations/0007_populate_celery_beat_schedules.py`.
# Editar schedules SOLO en settings (y re-sembrar la DB si aplica).

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
