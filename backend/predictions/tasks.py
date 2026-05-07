"""
Tareas Celery del módulo de predicciones.

Schedule (ver core/celery.py):
  02:00 diario  — train_all_prediction_models   (reentrenar todo)
  */4h          — refresh_ensemble_weights       (recalcular pesos dinámicos)
  horario       — cache_forecast_hourly          (pre-calentar caché Redis)
  domingo 03:00 — weekly_backtest_report         (backtesting + alertas)
  evaluación    — evaluate_predictions           (rellenar actual_rate)
"""
import logging
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone
from datetime import timedelta

from .models import PredictionModel, Prediction, TrainingData

logger = logging.getLogger(__name__)

CURRENCY_PAIRS = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'ARS/BOB', 'PEN/BOB']

# ── Compatibilidad con imports existentes en views.py ─────────────────────────
# views.py importa estas dos funciones directamente


@shared_task(name='predictions.train_prediction_models')
def train_prediction_models():
    """Tarea legacy — delega al nuevo engine + mantiene Prophet/LSTM del servicio original."""
    return train_all_prediction_models.apply().get()


@shared_task(name='predictions.generate_predictions')
def generate_predictions():
    """Tarea legacy — delega al engine para cache pre-calentado."""
    return cache_forecast_hourly.apply().get()


# ── Tarea 1: Reentrenamiento diario completo ──────────────────────────────────

@shared_task(
    name='predictions.train_all_prediction_models',
    bind=True,
    max_retries=2,
    acks_late=True,
    soft_time_limit=3600,
    time_limit=4200,
)
def train_all_prediction_models(self):
    """
    Diaria 02:00 — Reentrenar todos los modelos (Prophet, BiLSTM, XGBoost, ARIMA).
    Incluye actualización de datos de entrenamiento como primer paso.
    """
    logger.info("TASK_START name=train_all_prediction_models")

    try:
        from predictions.ml_engine import ForexMLEngine
        engine  = ForexMLEngine()
        results = {}

        for pair in CURRENCY_PAIRS:
            # 1. Sincronizar datos desde ExchangeRate → TrainingData
            try:
                update_training_data(pair)
            except Exception as exc:
                logger.warning("sync_data_failed pair=%s: %s", pair, exc)

            # 2. Entrenar modelos base nuevos (XGBoost, ARIMA, BiLSTM)
            try:
                extended = engine.train_all(pair, include=['xgboost', 'arima', 'bilstm'])
                results[pair] = {'new_models': extended}
            except Exception as exc:
                logger.error("train_extended_failed pair=%s: %s", pair, exc)
                results[pair] = {'new_models': {'error': str(exc)}}

            # 3. Entrenar modelos legacy (Prophet + LSTM original + Ensemble)
            try:
                from predictions.ml_service import ForexPredictionService
                svc = ForexPredictionService()
                _, pm = svc.train_prophet_model(pair)
                results[pair]['prophet'] = pm
                svc.train_ensemble_model(pair)
                results[pair]['ensemble'] = 'ok'
            except Exception as exc:
                logger.warning("train_legacy_failed pair=%s: %s", pair, exc)
                results[pair]['prophet'] = {'error': str(exc)}

        success = sum(1 for v in results.values() if 'error' not in str(v).lower())
        logger.info("TASK_SUCCESS name=train_all_prediction_models success=%d/%d", success, len(CURRENCY_PAIRS))
        return {'status': 'ok', 'results': results, 'success': success}

    except SoftTimeLimitExceeded:
        logger.error("TASK_TIMEOUT name=train_all_prediction_models")
        raise

    except Exception as exc:
        logger.error("TASK_FAILURE name=train_all_prediction_models error=%s", exc)
        try:
            raise self.retry(exc=exc, countdown=300)
        except self.MaxRetriesExceededError:
            from core.tasks import _emit_system_alert
            _emit_system_alert('ml', f'Reentrenamiento fallido: {exc}', severity='HIGH')
            return {'status': 'error', 'error': str(exc)}


# ── Tarea 2: Recalcular pesos del ensemble cada 4 horas ───────────────────────

@shared_task(
    name='predictions.refresh_ensemble_weights',
    bind=True,
    max_retries=1,
    acks_late=True,
    soft_time_limit=120,
    time_limit=180,
)
def refresh_ensemble_weights(self):
    """
    Cada 4 horas — recalcula pesos basados en MAPE reciente e invalida caché.
    """
    logger.info("TASK_START name=refresh_ensemble_weights")
    try:
        from predictions.ml_engine import ForexMLEngine
        engine  = ForexMLEngine()
        results = {}
        for pair in CURRENCY_PAIRS:
            try:
                weights = engine.refresh_ensemble_weights(pair)
                results[pair] = weights
            except Exception as exc:
                logger.warning("weights_refresh_failed pair=%s: %s", pair, exc)
                results[pair] = {'error': str(exc)}

        logger.info("TASK_SUCCESS name=refresh_ensemble_weights")
        return {'status': 'ok', 'weights': results}

    except Exception as exc:
        logger.error("TASK_FAILURE name=refresh_ensemble_weights error=%s", exc)
        return {'status': 'error', 'error': str(exc)}


# ── Tarea 3: Caché horario — pre-calcular y guardar en Redis ─────────────────

@shared_task(
    name='predictions.cache_forecast_hourly',
    bind=True,
    max_retries=2,
    acks_late=True,
    soft_time_limit=300,
    time_limit=360,
)
def cache_forecast_hourly(self):
    """
    Cada hora — genera pronósticos para todos los horizontes y pares, guarda en Redis.
    Garantiza latencia < 200ms en la API al servir desde caché.
    """
    logger.info("TASK_START name=cache_forecast_hourly")
    try:
        from predictions.ml_engine import ForexMLEngine
        engine = ForexMLEngine()
        cached = 0

        for pair in CURRENCY_PAIRS:
            try:
                engine.cache_all_horizons(pair)
                cached += 1

                # También guardar predicciones en BD para historial
                _persist_ensemble_predictions(engine, pair)

            except Exception as exc:
                logger.warning("cache_hourly_failed pair=%s: %s", pair, exc)

        logger.info("TASK_SUCCESS name=cache_forecast_hourly cached=%d", cached)
        return {'status': 'ok', 'cached_pairs': cached}

    except SoftTimeLimitExceeded:
        logger.error("TASK_TIMEOUT name=cache_forecast_hourly")
        raise


def _persist_ensemble_predictions(engine, pair: str):
    """Guarda las predicciones de las próximas 24h en la BD (para auditoría)."""
    try:
        from predictions.models import PredictionModel, Prediction
        from rates.models import RateConfiguration

        pm = PredictionModel.objects.filter(
            model_type='ENSEMBLE', currency_pair=pair, is_active=True
        ).first()
        if not pm:
            return

        result  = engine.predict(pair, horizon_key='24h', use_cache=True)
        preds   = result.get('predictions', [])
        records = []
        rate_config = RateConfiguration.objects.filter(
            currency_from__code=pair.split('/')[0],
            currency_to__code=pair.split('/')[1],
            is_active=True,
        ).first()

        for p in preds:
            from decimal import Decimal
            rate = Decimal(str(p['rate']))
            margin = Decimal('0.3')
            if rate_config:
                margin = rate_config.buy_margin_morning  # simplificado
            buy  = rate * (Decimal('1') - margin / Decimal('100'))
            sell = rate * (Decimal('1') + margin / Decimal('100'))

            records.append(Prediction(
                model=pm,
                currency_pair=pair,
                prediction_date=p['datetime'],
                predicted_rate=rate,
                predicted_buy_rate=buy,
                predicted_sell_rate=sell,
                confidence_lower=Decimal(str(p['lower'])),
                confidence_upper=Decimal(str(p['upper'])),
                confidence_score=0.95,
                external_factors=p.get('components', {}),
            ))

        Prediction.objects.bulk_create(records, batch_size=500, ignore_conflicts=True)
    except Exception as exc:
        logger.warning("persist_ensemble_failed pair=%s: %s", pair, exc)


# ── Tarea 4: Backtesting semanal ──────────────────────────────────────────────

@shared_task(
    name='predictions.weekly_backtest_report',
    bind=True,
    max_retries=1,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def weekly_backtest_report(self):
    """
    Domingos 03:00 — backtesting completo de 30 días.
    Alerta si MAPE supera umbrales configurados.
    """
    logger.info("TASK_START name=weekly_backtest_report")
    try:
        from predictions.ml_engine import ForexMLEngine
        engine  = ForexMLEngine()
        reports = {}

        for pair in CURRENCY_PAIRS:
            try:
                report = engine.run_weekly_backtest(pair)
                reports[pair] = report
                logger.info(
                    "backtest pair=%s mape=%.4f%% alerts=%d",
                    pair,
                    report['metrics'].get('mape_avg', 0),
                    len(report.get('alerts', [])),
                )
            except Exception as exc:
                logger.warning("backtest_failed pair=%s: %s", pair, exc)
                reports[pair] = {'error': str(exc)}

        logger.info("TASK_SUCCESS name=weekly_backtest_report")
        return {'status': 'ok', 'reports': reports}

    except Exception as exc:
        logger.error("TASK_FAILURE name=weekly_backtest_report error=%s", exc)
        return {'status': 'error', 'error': str(exc)}


# ── Tarea 5: Evaluar predicciones pasadas ─────────────────────────────────────

@shared_task(name='predictions.evaluate_predictions')
def evaluate_predictions():
    """Rellena actual_rate en predicciones pasadas y recalcula error_percentage."""
    from rates.models import ExchangeRate

    evaluation_time = timezone.now() - timedelta(hours=24)
    predictions     = Prediction.objects.filter(
        created_at__gte=evaluation_time - timedelta(hours=1),
        created_at__lt=evaluation_time  + timedelta(hours=1),
        actual_rate__isnull=True,
    )
    evaluated = 0
    for prediction in predictions:
        currency_from, currency_to = prediction.currency_pair.split('/')
        actual = ExchangeRate.objects.filter(
            currency_from__code=currency_from,
            currency_to__code=currency_to,
            valid_from__lte=prediction.prediction_date,
            valid_until__gte=prediction.prediction_date,
        ).first()
        if actual:
            # Usar tasa paralela (mid) como referencia real — BCB ya no es fuente activa
            prediction.actual_rate = (actual.buy_rate + actual.sell_rate) / 2
            prediction.calculate_error()
            evaluated += 1

    _update_model_metrics()
    logger.info("evaluate_predictions evaluated=%d", evaluated)
    return {'predictions_evaluated': evaluated}


# ── Tarea 6: Sincronizar datos de entrenamiento ───────────────────────────────

@shared_task(name='predictions.update_training_data')
def update_training_data(currency_pair: str):
    """Sincroniza ExchangeRate → TrainingData (upsert)."""
    from rates.models import ExchangeRate

    currency_from, currency_to = currency_pair.split('/')
    rates = ExchangeRate.objects.filter(
        currency_from__code=currency_from,
        currency_to__code=currency_to,
        market_type__in=('paralelo_digital', 'paralelo_fisico_empresa', 'parallel', 'digital'),
    ).order_by('-valid_from')[:2000]

    updated = 0
    for rate in rates:
        # Usar mid de mercado paralelo como dato de entrenamiento
        mid_rate = (rate.buy_rate + rate.sell_rate) / 2
        _, created = TrainingData.objects.update_or_create(
            currency_pair=currency_pair,
            date=rate.valid_from,
            defaults={'rate': mid_rate, 'source': rate.source},
        )
        if created:
            updated += 1

    logger.info("update_training_data pair=%s updated=%d", currency_pair, updated)
    return {'pair': currency_pair, 'updated': updated}


# ── Tarea 7: Tuning semanal de hiperparámetros ────────────────────────────────

@shared_task(
    name='predictions.weekly_hyperparameter_tuning',
    bind=True,
    max_retries=0,
    acks_late=True,
    soft_time_limit=7200,   # 2h — tuning es costoso
    time_limit=7800,
)
def weekly_hyperparameter_tuning(self):
    """Sábados 04:00 — optimización bayesiana de XGBoost y Prophet con Optuna."""
    logger.info("TASK_START name=weekly_hyperparameter_tuning")
    try:
        from django.conf import settings
        from predictions.hyperparameter_tuning import run_weekly_tuning
        import os
        models_path = os.path.join(settings.MEDIA_ROOT, 'ml_models')
        results     = run_weekly_tuning(CURRENCY_PAIRS, models_path, n_trials=40)
        logger.info("TASK_SUCCESS name=weekly_hyperparameter_tuning")
        return {'status': 'ok', 'results': results}
    except SoftTimeLimitExceeded:
        logger.error("TASK_TIMEOUT name=weekly_hyperparameter_tuning")
        return {'status': 'timeout'}
    except Exception as exc:
        logger.error("TASK_FAILURE name=weekly_hyperparameter_tuning error=%s", exc)
        return {'status': 'error', 'error': str(exc)}


# ── Tarea manual: entrenamiento inicial ───────────────────────────────────────

@shared_task(name='predictions.train_initial_models')
def train_initial_models():
    """
    Entrena modelos solo si hay >= 100 snapshots por par.
    Ejecutar manualmente:
      python manage.py shell -c "from predictions.tasks import train_initial_models; train_initial_models()"
    """
    results = {}
    for pair in CURRENCY_PAIRS:
        count = TrainingData.objects.filter(currency_pair=pair).count()
        if count < 100:
            logger.info('train_initial_models skip pair=%s count=%d < 100', pair, count)
            results[pair] = {'skipped': True, 'reason': f'solo {count} snapshots (min 100)'}
            continue
        try:
            from predictions.ml_service import ForexPredictionService
            svc = ForexPredictionService()
            _, metrics = svc.train_prophet_model(pair)
            results[pair] = {'trained': True, 'metrics': metrics}
            logger.info('train_initial_models pair=%s ok mape=%.4f', pair, metrics.get('mape', 0))
        except Exception as exc:
            logger.error('train_initial_models pair=%s error=%s', pair, exc)
            results[pair] = {'trained': False, 'error': str(exc)}
    return results


# ── Helpers ────────────────────────────────────────────────────────────────────

def _update_model_metrics():
    """Actualiza recent_mape en cada PredictionModel activo."""
    for model in PredictionModel.objects.filter(is_active=True):
        recent = Prediction.objects.filter(
            model=model,
            actual_rate__isnull=False,
            created_at__gte=timezone.now() - timedelta(days=30),
        )
        if not recent.exists():
            continue
        errors = [
            float(abs(p.actual_rate - p.predicted_rate) / p.actual_rate * 100)
            for p in recent
            if p.actual_rate and p.predicted_rate and p.actual_rate != 0
        ]
        if errors:
            model.metrics['recent_mape']        = round(sum(errors) / len(errors), 4)
            model.metrics['recent_predictions'] = len(errors)
            model.metrics['last_evaluation']    = timezone.now().isoformat()
            model.save(update_fields=['metrics'])
