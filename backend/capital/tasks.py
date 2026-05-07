# capital/tasks.py
"""
Tareas Celery para el módulo de capital.

Programadas en core/celery.py:
  - save_daily_snapshots_task    → cada día a las 23:45
  - refresh_capital_position_task → cada 30 s via Beat (o bajo demanda)
  - check_capital_alerts_task    → cada 15 min
"""
import logging

from celery import shared_task
from django.utils import timezone

log = logging.getLogger('capital.tasks')


@shared_task(
    bind=True,
    name='capital.save_daily_snapshots',
    max_retries=3,
    default_retry_delay=120,
    acks_late=True,
    reject_on_worker_lost=True,
)
def save_daily_snapshots_task(self):
    """
    Guarda el snapshot de posición de todas las sucursales activas.
    Ejecutar al cierre del día (23:45 vía Celery Beat).
    """
    try:
        from users.models import Branch
        from capital.position_service import CapitalPositionService

        svc      = CapitalPositionService()
        branches = Branch.objects.filter(is_active=True).values_list('id', flat=True)
        saved    = 0

        for branch_id in branches:
            try:
                svc.save_daily_snapshot(branch_id)
                saved += 1
            except Exception as exc:
                log.error('SNAPSHOT_BRANCH_ERR branch=%s err=%s', branch_id, exc)

        log.info('DAILY_SNAPSHOTS_DONE branches=%d saved=%d', len(branches), saved)
        return {'branches': len(list(branches)), 'saved': saved}
    except Exception as exc:
        log.error('DAILY_SNAPSHOTS_FAIL err=%s', exc, exc_info=True)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    name='capital.check_capital_alerts',
    max_retries=2,
    acks_late=True,
)
def check_capital_alerts_task(self):
    """
    Verifica alertas de capital para todas las sucursales y emite alertas
    al sistema de notificaciones (GlobalAlertService).
    Ejecutar cada 15 minutos vía Celery Beat.
    """
    try:
        from users.models import Branch
        from capital.position_service import CapitalPositionService
        from django.conf import settings

        svc      = CapitalPositionService()
        branches = Branch.objects.filter(is_active=True).values_list('id', flat=True)
        min_cap  = getattr(settings, 'CAPITAL_MIN_BOB', 50_000)
        total_alerts = 0

        for branch_id in branches:
            try:
                snap      = svc.get_real_time_position(branch_id)
                snap_dict = svc._serialize_snapshot(snap)
                net_par   = float(snap_dict.get('net_capital_par', 0))

                if net_par < min_cap:
                    from alerts.services import GlobalAlertService
                    from users.models import Branch as B
                    branch = B.objects.get(pk=branch_id)
                    GlobalAlertService.emit(
                        source='CAPITAL',
                        alert_type='CAPITAL_BAJO',
                        severity='HIGH',
                        title=f'Capital bajo en {branch}',
                        message=f'Capital neto Bs {net_par:,.2f} < mínimo Bs {min_cap:,.2f}',
                        data={'branch_id': branch_id, 'net_capital': str(net_par)},
                        branch=branch,
                    )
                    total_alerts += 1

                # Posiciones negativas
                for cur in snap_dict.get('currencies', []):
                    units = float(cur.get('net_units', 0))
                    if units < 0:
                        code = cur.get('currency_code', '?')
                        log.warning('NEGATIVE_POSITION branch=%s currency=%s units=%s', branch_id, code, units)
                        total_alerts += 1

            except Exception as exc:
                log.warning('CAPITAL_ALERT_BRANCH_ERR branch=%s err=%s', branch_id, exc)

        log.info('CAPITAL_ALERTS_CHECK done branches=%d alerts=%d', len(list(branches)), total_alerts)
        return {'alerts_generated': total_alerts}
    except Exception as exc:
        log.error('CAPITAL_ALERTS_FAIL err=%s', exc, exc_info=True)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    name='capital.update_unrealized_pnl',
    max_retries=2,
    acks_late=True,
)
def update_unrealized_pnl_task(self):
    """
    Recalcula el P&L no realizado de todas las posiciones a tasas actuales.
    Ejecutar cada hora via Celery Beat.
    """
    try:
        from capital.models import CurrencyPosition
        from rates.parallel_rate_service import ParallelRateService
        from rates.models import ExchangeRate

        svc      = ParallelRateService()
        updated  = 0

        for pos in CurrencyPosition.objects.select_related('currency', 'branch').iterator(chunk_size=100):
            code = pos.currency.code
            try:
                par_rate = svc.get_cached_rate(code)
                if not par_rate:
                    continue
                pos.update_unrealized_pnl(par_rate)
                pos.save(update_fields=[
                    'unrealized_pnl_parallel', 'unrealized_pnl_official',
                    'parallel_rate_used', 'official_rate_used',
                ])
                updated += 1
            except Exception as exc:
                log.warning('PNL_UPDATE_ERR branch=%s cur=%s err=%s', pos.branch_id, code, exc)

        log.info('UNREALIZED_PNL_UPDATED count=%d', updated)
        return {'updated': updated}
    except Exception as exc:
        log.error('UNREALIZED_PNL_FAIL err=%s', exc, exc_info=True)
        raise self.retry(exc=exc)
