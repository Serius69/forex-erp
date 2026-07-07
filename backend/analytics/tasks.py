# analytics/tasks.py
"""
Tareas Celery para el motor analítico de Kapitalya.

SCHEDULE sugerido (Celery Beat):
  analytics.snapshot_spreads       → cada 15 min
  analytics.snapshot_exposure      → cada 30 min
  analytics.recalculate_pnl_daily  → cada hora (o al cierre del día)
  analytics.cleanup_old_snapshots  → diario a las 02:00
"""
from __future__ import annotations
import logging
from celery import shared_task
from django.utils import timezone

log = logging.getLogger('analytics.tasks')

_RETRY = [60, 300, 900]   # 1m, 5m, 15m


# ─────────────────────────────────────────────────────────────────────────────
# Spread snapshot — cada 15 min
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, acks_late=True, max_retries=3,
    name='analytics.snapshot_spreads',
)
def snapshot_spreads(self):
    """
    Persiste un SpreadSnapshot para todas las tasas activas.
    También guarda ExposureSnapshot para todas las sucursales activas.
    """
    log.info('TASK_START analytics.snapshot_spreads')
    try:
        from .services import SpreadService
        SpreadService.guardar_snapshot()
        log.info('TASK_DONE analytics.snapshot_spreads')
        return {'success': True}
    except Exception as exc:
        delay = _RETRY[min(self.request.retries, len(_RETRY) - 1)]
        log.error('TASK_ERROR analytics.snapshot_spreads err=%s retry_in=%ds', exc, delay)
        raise self.retry(exc=exc, countdown=delay)


# ─────────────────────────────────────────────────────────────────────────────
# Exposure snapshot — cada 30 min
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, acks_late=True, max_retries=3,
    name='analytics.snapshot_exposure',
)
def snapshot_exposure(self):
    """
    Guarda ExposureSnapshot para todas las sucursales activas.
    Emite alertas WebSocket si hay concentración crítica.
    """
    log.info('TASK_START analytics.snapshot_exposure')
    try:
        from users.models import Branch
        from .services import ExposureService

        branches = Branch.objects.filter(is_active=True)
        total_snaps = 0

        for branch in branches:
            snaps = ExposureService.guardar_snapshot(branch)
            total_snaps += len(snaps)

            # Emitir alertas WebSocket si hay niveles críticos
            for snap in snaps:
                if snap.alert_level in ('WARNING', 'CRITICAL'):
                    _emit_exposure_alert(snap)

        log.info('TASK_DONE analytics.snapshot_exposure branches=%d snaps=%d',
                 branches.count(), total_snaps)
        return {'success': True, 'snapshots': total_snaps}

    except Exception as exc:
        delay = _RETRY[min(self.request.retries, len(_RETRY) - 1)]
        log.error('TASK_ERROR analytics.snapshot_exposure err=%s retry_in=%ds', exc, delay)
        raise self.retry(exc=exc, countdown=delay)


# ─────────────────────────────────────────────────────────────────────────────
# P&L recálculo diario — cada hora
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, acks_late=True, max_retries=3,
    name='analytics.recalculate_pnl_daily',
)
def recalculate_pnl_daily(self):
    """
    Recalcula el PnLDailySnapshot de HOY para todas las sucursales.
    Útil para asegurar consistencia aunque se hayan procesado reversas durante el día.
    """
    log.info('TASK_START analytics.recalculate_pnl_daily')
    try:
        from users.models import Branch
        from .services import PnLService

        branches = Branch.objects.filter(is_active=True)
        for branch in branches:
            PnLService.recalcular_snapshot_hoy(branch)

        log.info('TASK_DONE analytics.recalculate_pnl_daily branches=%d', branches.count())
        return {'success': True, 'branches': branches.count()}

    except Exception as exc:
        delay = _RETRY[min(self.request.retries, len(_RETRY) - 1)]
        log.error('TASK_ERROR analytics.recalculate_pnl_daily err=%s retry_in=%ds', exc, delay)
        raise self.retry(exc=exc, countdown=delay)


# ─────────────────────────────────────────────────────────────────────────────
# Limpieza de snapshots antiguos — diario
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, acks_late=True, max_retries=2,
    name='analytics.cleanup_old_snapshots',
)
def cleanup_old_snapshots(self):
    """
    Elimina SpreadSnapshot y ExposureSnapshot con más de 90 días de antigüedad.
    PnLDailySnapshot y TransactionProfitLedger se conservan indefinidamente (auditoría).
    """
    log.info('TASK_START analytics.cleanup_old_snapshots')
    try:
        from .models import SpreadSnapshot, ExposureSnapshot
        cutoff = timezone.now() - timezone.timedelta(days=90)

        spread_del   = SpreadSnapshot.objects.filter(timestamp__lt=cutoff).delete()
        exposure_del = ExposureSnapshot.objects.filter(timestamp__lt=cutoff).delete()

        log.info(
            'TASK_DONE analytics.cleanup_old_snapshots spread=%s exposure=%s',
            spread_del[0], exposure_del[0],
        )
        return {'success': True, 'spread_deleted': spread_del[0], 'exposure_deleted': exposure_del[0]}

    except Exception as exc:
        delay = _RETRY[min(self.request.retries, 1)]
        log.error('TASK_ERROR analytics.cleanup_old_snapshots err=%s', exc)
        raise self.retry(exc=exc, countdown=delay)


# ─────────────────────────────────────────────────────────────────────────────
# Anomaly detection — cada 15 min
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True, acks_late=True, max_retries=2,
    name='analytics.detect_anomalies',
)
def detect_anomalies(self, branch_id: int = None):
    """
    Ejecuta todas las reglas de detección de anomalías financieras.

    Se puede llamar:
      · Sin args        → escanea todas las sucursales activas
      · branch_id=N     → solo esa sucursal

    Anomalías detectadas:
      CAPITAL_DROP       — caída de capital ≥ 3 % (WARNING) o ≥ 5 % (CRITICAL)
      MISSING_CASH       — discrepancia en caja ≥ Bs. 50 / Bs. 500
      NEGATIVE_BALANCE   — cualquier saldo negativo
      RATE_INVERTED      — buy ≥ sell (spread negativo o cero)
      RATE_STALE         — tasa sin actualizar en > 2 h (horario hábil)
      RATE_BCB_DEVIATION — desviación ≥ 15 % sobre BCB oficial
      SPREAD_BELOW_MIN   — spread < 0.30 %
      EXPOSURE_HIGH      — concentración divisa > 40 % / 60 % del capital
    """
    log.info('TASK_START analytics.detect_anomalies branch_id=%s', branch_id)
    try:
        from users.models import Branch
        from .services import AnomalyDetector

        if branch_id:
            try:
                branches = [Branch.objects.get(pk=branch_id)]
            except Branch.DoesNotExist:
                log.error('DETECT_ANOMALIES branch_id=%s not found', branch_id)
                return {'success': False, 'error': 'branch not found'}
        else:
            branches = list(Branch.objects.filter(is_active=True))

        total_anomalies = 0
        total_critical  = 0
        results_by_branch = []

        for branch in branches:
            anomalies = AnomalyDetector.run_all(branch=branch, persist=True)
            n_critical = sum(1 for a in anomalies if a['severity'] == 'CRITICAL')
            total_anomalies += len(anomalies)
            total_critical  += n_critical

            results_by_branch.append({
                'branch':   branch.code,
                'total':    len(anomalies),
                'critical': n_critical,
            })

            # Persistir en AlertLog global y emitir por WebSocket
            for a in anomalies:
                if a['severity'] in ('CRITICAL', 'WARNING'):
                    _emit_anomaly_alert(a, branch)
                    try:
                        from alerts.services import GlobalAlertService
                        GlobalAlertService.from_anomaly(anomaly=a, branch=branch)
                    except Exception as _ae:
                        log.debug('ANOMALY_ALERT_PERSIST_FAIL err=%s', _ae)

        log.info(
            'TASK_DONE analytics.detect_anomalies branches=%d '
            'total=%d critical=%d',
            len(branches), total_anomalies, total_critical,
        )
        return {
            'success':         True,
            'branches_scanned': len(branches),
            'total_anomalies': total_anomalies,
            'critical':        total_critical,
            'by_branch':       results_by_branch,
        }

    except Exception as exc:
        delay = _RETRY[min(self.request.retries, len(_RETRY) - 1)]
        log.error('TASK_ERROR analytics.detect_anomalies err=%s retry_in=%ds', exc, delay)
        raise self.retry(exc=exc, countdown=delay)


def _emit_anomaly_alert(anomaly: dict, branch) -> None:
    """
    Publica la anomalía por WebSocket al grupo alerts_branch_{id}.
    Fire-and-forget: los errores de WS nunca abortan el proceso principal.
    """
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if not layer:
            return

        group = f'alerts_branch_{branch.id}'
        async_to_sync(layer.group_send)(group, {
            'type':  'alert_message',
            'alert': {
                'severity':    anomaly['severity'],
                'rule':        anomaly['rule'],
                'message':     anomaly['description'],
                'currency':    anomaly.get('currency', ''),
                'value':       anomaly.get('value', ''),
                'threshold':   anomaly.get('threshold', ''),
                'source':      'anomaly_detector',
            },
        })
    except Exception as exc:
        log.debug('ANOMALY_ALERT_WS_SKIP err=%s', exc)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: emitir alerta de exposición por WebSocket
# ─────────────────────────────────────────────────────────────────────────────

def _emit_exposure_alert(snap) -> None:
    """Fire-and-forget: notifica por WebSocket sobre concentración de riesgo."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if not layer:
            return

        group = f'alerts_branch_{snap.branch_id}'
        async_to_sync(layer.group_send)(group, {
            'type':  'alert_message',
            'alert': {
                'severity':     snap.alert_level,
                'message':      (
                    f"Concentración {snap.alert_level} en {snap.currency_code}: "
                    f"{snap.pct_of_capital}% del capital "
                    f"(Bs. {snap.exposure_bob})"
                ),
                'currency_code': snap.currency_code,
                'pct':           str(snap.pct_of_capital),
                'exposure_bob':  str(snap.exposure_bob),
                'source':        'exposure_monitor',
            },
        })
    except Exception as exc:
        log.debug('EXPOSURE_ALERT_WS_SKIP err=%s', exc)
