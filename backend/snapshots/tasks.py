# snapshots/tasks.py
"""
Tareas Celery para snapshots programados del sistema.

  apertura-snapshot  — 08:00 diario  → module='system', action='apertura'
  cierre-snapshot    — 23:45 diario  → module='system', action='cierre'

Ambas tareas:
  - No usan debounce (force=True)
  - Crean un snapshot para CADA sucursal activa
  - Registran errores por sucursal sin abortar las demás
"""
import logging

from celery import shared_task

log = logging.getLogger('snapshots')


def _run_system_snapshot(action: str):
    """
    Lógica común para apertura y cierre.
    Itera todas las sucursales activas y crea un snapshot por cada una.
    """
    from users.models import Branch
    from .services import SnapshotService

    branches = Branch.objects.filter(is_active=True)
    created  = 0
    errors   = 0

    for branch in branches:
        try:
            snap = SnapshotService.create(
                module   = 'system',
                action   = action,
                user     = None,          # tarea programada, sin usuario
                branch   = branch,
                metadata = {'trigger': f'celery_beat_{action}'},
                force    = True,          # nunca debounced
            )
            if snap:
                created += 1
                log.info(
                    'SYSTEM_SNAPSHOT_%s id=%s branch=%s total_bob=%s',
                    action.upper(), snap.id, branch.code, snap.capital_total_bob,
                )
        except Exception as exc:
            errors += 1
            log.error(
                'SYSTEM_SNAPSHOT_%s_FAIL branch=%s err=%s',
                action.upper(), branch.code, exc, exc_info=True,
            )

    log.info(
        'SYSTEM_SNAPSHOT_%s_DONE created=%d errors=%d',
        action.upper(), created, errors,
    )
    return {'action': action, 'created': created, 'errors': errors}


@shared_task(
    name='snapshots.take_opening_snapshot',
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    queue='low',
)
def take_opening_snapshot(self):
    """
    Snapshot de apertura — captura el estado del sistema al inicio del día.
    Cron: 08:00 diario.
    """
    try:
        return _run_system_snapshot('apertura')
    except Exception as exc:
        log.error('OPENING_SNAPSHOT_TASK_FAIL err=%s', exc, exc_info=True)
        raise self.retry(exc=exc)


@shared_task(
    name='snapshots.take_closing_snapshot',
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    queue='low',
)
def take_closing_snapshot(self):
    """
    Snapshot de cierre — captura el estado final del día.
    Cron: 23:45 diario (después del generate-daily-report a las 23:30).
    """
    try:
        return _run_system_snapshot('cierre')
    except Exception as exc:
        log.error('CLOSING_SNAPSHOT_TASK_FAIL err=%s', exc, exc_info=True)
        raise self.retry(exc=exc)
