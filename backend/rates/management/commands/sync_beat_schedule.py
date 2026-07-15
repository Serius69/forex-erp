"""
Sincroniza el schedule de Celery Beat en BD (django_celery_beat) con la
definición canónica de este archivo.

Contexto: el scheduler efectivo es DatabaseScheduler (ver core/celery.py);
el CELERY_BEAT_SCHEDULE de settings es config muerta. La siembra original
(analytics/migrations/0007) dejó registrada la tarea INEXISTENTE
'predictions.generate_daily_forecast' — resultado: el pipeline ML entero
(reentrenamiento, cache de forecasts, evaluación, backtest, tuning) NUNCA
corría solo. Este comando es idempotente y re-ejecutable:

    python manage.py sync_beat_schedule            # aplica
    python manage.py sync_beat_schedule --dry-run  # muestra el diff

Solo gestiona las entradas listadas aquí (+ las muertas conocidas); no toca
entradas creadas a mano fuera de esta lista.
"""
from django.core.management.base import BaseCommand

TZ = 'America/La_Paz'

# Entradas obsoletas que hay que eliminar si existen (tareas inexistentes).
STALE_NAMES = [
    'predictions-daily-forecast',   # → predictions.generate_daily_forecast (no existe)
]

# name → definición. interval en segundos O crontab dict.
CANONICAL = {
    # ── Pipeline ML de predicciones (antes NUNCA agendado) ──────────────────
    'predictions-train-daily': {
        'task':    'predictions.train_all_prediction_models',
        'crontab': {'hour': 2, 'minute': 0},
        'queue':   'low',
        'desc':    'Reentrena todos los modelos (3 mercados) cada madrugada',
    },
    'predictions-cache-hourly': {
        'task':     'predictions.cache_forecast_hourly',
        'interval': 60 * 60,
        'queue':    'low',
        'desc':     'Persiste forecasts por horizonte para servir sin latencia',
    },
    'predictions-refresh-weights': {
        'task':     'predictions.refresh_ensemble_weights',
        'interval': 4 * 60 * 60,
        'queue':    'low',
        'desc':     'Recalcula pesos del ensemble según MAPE reciente',
    },
    'predictions-evaluate-daily': {
        'task':    'predictions.evaluate_predictions',
        'crontab': {'hour': 3, 'minute': 0},
        'queue':   'low',
        'desc':    'Rellena actual_rate de predicciones vencidas y recalcula métricas',
    },
    'predictions-weekly-backtest': {
        'task':    'predictions.weekly_backtest_report',
        'crontab': {'hour': 4, 'minute': 0, 'day_of_week': 0},   # domingo
        'queue':   'low',
        'desc':    'Backtest semanal con alertas por MAPE degradado',
    },
    'predictions-weekly-tuning': {
        'task':    'predictions.weekly_hyperparameter_tuning',
        'crontab': {'hour': 5, 'minute': 0, 'day_of_week': 0},   # domingo
        'queue':   'low',
        'desc':    'Optuna semanal sobre XGBoost/BiLSTM',
    },
    # ── Tasa OFICIAL BCB (dolarapi → scrape BCB), base de la brecha ──────────
    'rates-official-daily': {
        'task':    'rates.update_exchange_rates',
        'crontab': {'hour': 8, 'minute': 5},
        'queue':   'default',
        'desc':    'Tasa oficial BCB diaria (dolarapi oficial → scrape BCB)',
    },
    # ── Series físicas + higiene de tasas (antes solo comandos manuales) ────
    'rates-derive-empresa-daily': {
        'task':    'rates.derive_empresa_rates_daily',
        'crontab': {'hour': 1, 'minute': 30},
        'queue':   'default',
        'desc':    'Deriva tasa efectiva empresa desde transacciones del día',
    },
    'rates-normalize-active': {
        'task':    'rates.normalize_active_rates',
        'crontab': {'hour': 4, 'minute': 30},
        'queue':   'default',
        'desc':    'Red de seguridad: una sola tasa vigente por grupo',
    },
    'rates-cleanup-old': {
        'task':    'rates.cleanup_old_rates',
        'crontab': {'hour': 3, 'minute': 30},
        'queue':   'low',
        'desc':    'Archiva raws >90 días (S3 si está configurado)',
    },
    # ── ETL Google Sheet operativo (transacciones reales de la hoja viva) ────
    'transactions-sheet-sync': {
        'task':     'transactions.sync_sheet_transactions',
        'interval': 30 * 60,
        'queue':    'default',
        'desc':     'Sincroniza tx nuevas del Sheet 2026 (idempotente por seq)',
    },
    # ── Indicadores macro Bolivia ────────────────────────────────────────────
    'macro-daily-indicators': {
        'task':    'macro.fetch_daily_indicators',
        'crontab': {'hour': 8, 'minute': 30},   # tras la tasa oficial de las 08:05
        'queue':   'default',
        'desc':    'USD internacional (er-api) + brecha oficial↔paralelo',
    },
    'macro-worldbank-weekly': {
        'task':    'macro.fetch_world_bank_indicators',
        'crontab': {'hour': 6, 'minute': 0, 'day_of_week': 1},   # lunes
        'queue':   'low',
        'desc':    'Series anuales World Bank Bolivia (upsert idempotente)',
    },
    'macro-news-4h': {
        'task':     'macro.fetch_news',
        'interval': 4 * 60 * 60,
        'queue':    'default',
        'desc':     'Noticias mercado cambiario (RSS) + índice de sentimiento',
    },
    # ── Kickstart del loop continuo (se re-encola solo, pero tras un reinicio
    #    de Redis/worker nadie lo relanzaba; el Redis lock deduplica) ─────────
    'rates-continuous-kickstart': {
        'task':     'rates.continuous_fx_extraction',
        'interval': 15 * 60,
        'queue':    'critical',
        'desc':     'Relanza el loop continuo si murió (lock evita duplicados)',
    },
}


class Command(BaseCommand):
    help = 'Sincroniza el schedule de Celery Beat (BD) con la definición canónica.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Solo reporta qué cambiaría.')

    def handle(self, *args, **opts):
        import json

        from django_celery_beat.models import (
            CrontabSchedule, IntervalSchedule, PeriodicTask,
        )

        dry = opts['dry_run']
        changed = 0

        # 1. Eliminar entradas muertas conocidas
        for name in STALE_NAMES:
            qs = PeriodicTask.objects.filter(name=name)
            if qs.exists():
                self.stdout.write(self.style.WARNING(f'ELIMINAR  {name} (tarea inexistente)'))
                if not dry:
                    qs.delete()
                changed += 1

        # 2. Upsert de las canónicas
        for name, spec in CANONICAL.items():
            if 'crontab' in spec:
                cron_kwargs = {'minute': '*', 'hour': '*', 'day_of_week': '*',
                               'day_of_month': '*', 'month_of_year': '*',
                               'timezone': TZ}
                cron_kwargs.update({k: str(v) for k, v in spec['crontab'].items()})
                if not dry:
                    schedule, _ = CrontabSchedule.objects.get_or_create(**cron_kwargs)
                sched_fields = {'crontab': schedule, 'interval': None} if not dry else {}
                sched_repr = 'cron ' + ' '.join(
                    f'{k}={v}' for k, v in spec['crontab'].items())
            else:
                if not dry:
                    schedule, _ = IntervalSchedule.objects.get_or_create(
                        every=spec['interval'], period=IntervalSchedule.SECONDS)
                sched_fields = {'interval': schedule, 'crontab': None} if not dry else {}
                sched_repr = f"cada {spec['interval']}s"

            defaults = {
                'task':        spec['task'],
                'queue':       spec.get('queue'),
                'enabled':     True,
                'description': spec.get('desc', ''),
                **sched_fields,
            }

            existing = PeriodicTask.objects.filter(name=name).first()
            if existing is None:
                self.stdout.write(self.style.SUCCESS(
                    f'CREAR     {name} → {spec["task"]}  [{sched_repr}]'))
                if not dry:
                    PeriodicTask.objects.create(name=name, **defaults)
                changed += 1
            else:
                dirty = (existing.task != spec['task']
                         or existing.queue != spec.get('queue')
                         or not existing.enabled)
                if not dry and not dirty:
                    # comparar schedule efectivo
                    dirty = (existing.crontab_id != (defaults.get('crontab').id
                                                     if defaults.get('crontab') else None)
                             or existing.interval_id != (defaults.get('interval').id
                                                         if defaults.get('interval') else None))
                if dirty:
                    self.stdout.write(f'ACTUALIZAR {name} → {spec["task"]}  [{sched_repr}]')
                    if not dry:
                        for k, v in defaults.items():
                            setattr(existing, k, v)
                        existing.save()
                    changed += 1
                else:
                    self.stdout.write(f'OK        {name}')

        # 3. Avisar al DatabaseScheduler que hay cambios
        if changed and not dry:
            try:
                from django_celery_beat.models import PeriodicTasks
                PeriodicTasks.update_changed()
            except Exception:
                pass

        verdict = 'sin cambios' if changed == 0 else f'{changed} cambios'
        self.stdout.write(self.style.SUCCESS(
            f'{"[dry-run] " if dry else ""}Sync completado: {verdict}.'))
