"""
ForexMLEngine — orquestador de todos los modelos de pronóstico.

Responsabilidades:
  - Entrena cualquier subconjunto de modelos (Prophet, BiLSTM, XGBoost, ARIMA, Ensemble)
  - Genera predicciones multi-horizonte usando el ensemble o modelos individuales
  - Gestiona caché Redis para respuestas rápidas (< 200 ms)
  - Genera respuesta completa para el endpoint mejorado de la API

No reemplaza ForexPredictionService (compatibilidad hacia atrás);
lo complementa y es usado por las nuevas tareas Celery y vistas.
"""
import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from predictions.data_pipeline    import ForexDataPipeline
from predictions.xgboost_forecaster import XGBoostForecaster
from predictions.arima_forecaster   import ARIMAForecaster
from predictions.lstm_forecaster    import LSTMForecaster
from predictions.ensemble_forecaster import EnsembleForecaster

logger = logging.getLogger(__name__)

# TTL de caché Redis por horizonte (segundos)
_CACHE_TTL = {
    '1h':  3_600,
    '4h':  14_400,
    '24h': 86_400,
    '7d':  604_800,
}

# Mapeo horizonte-string → horas
_HORIZON_HOURS = {
    '1h':  1,
    '4h':  4,
    '24h': 24,
    '7d':  168,
}

# Umbral MAPE para alertas automáticas (porcentaje)
MAPE_ALERT_THRESHOLD = {
    '1h':  0.5,
    '24h': 1.5,
    '7d':  3.0,
}


class ForexMLEngine:
    """Motor ML principal — punto de entrada único para entrenar y predecir."""

    ALL_MODELS = ['prophet', 'bilstm', 'xgboost', 'arima']

    def __init__(self):
        self.models_path = os.path.join(settings.MEDIA_ROOT, 'ml_models')
        os.makedirs(self.models_path, exist_ok=True)

        self.pipeline  = ForexDataPipeline()
        self.xgboost   = XGBoostForecaster(self.models_path)
        self.arima     = ARIMAForecaster(self.models_path)
        self.bilstm    = LSTMForecaster(self.models_path)
        self.ensemble  = EnsembleForecaster(self.models_path)

    # ── Entrenamiento ──────────────────────────────────────────────────────────

    def train_all(self, currency_pair: str, include: list = None) -> dict:
        """
        Entrena los modelos especificados en `include` (default: todos).
        Retorna dict {model: metrics | error}.
        """
        models_to_train = include or self.ALL_MODELS
        results         = {}

        df = self.pipeline.build(currency_pair)

        for model_name in models_to_train:
            try:
                results[model_name] = self._train_one(model_name, currency_pair, df)
            except Exception as exc:
                logger.error("engine.train_failed pair=%s model=%s error=%s", currency_pair, model_name, exc)
                results[model_name] = {'status': 'error', 'error': str(exc)}

        # Invalidar caché después de reentrenar
        self._invalidate_cache(currency_pair)
        return results

    def _train_one(self, model_name: str, currency_pair: str, df: pd.DataFrame) -> dict:
        if model_name == 'xgboost':
            return self.xgboost.train(currency_pair, df)
        elif model_name == 'arima':
            return self.arima.train(currency_pair, df)
        elif model_name == 'bilstm':
            return self.bilstm.train(currency_pair, df)
        elif model_name == 'prophet':
            # Delega al servicio legacy (ya tiene su propio entrenamiento)
            from predictions.ml_service import ForexPredictionService
            svc = ForexPredictionService()
            _, metrics = svc.train_prophet_model(currency_pair)
            return metrics
        else:
            raise ValueError(f"Modelo desconocido: {model_name}")

    # ── Predicción ─────────────────────────────────────────────────────────────

    def predict(
        self,
        currency_pair: str,
        horizon_key: str = '24h',
        use_cache: bool  = True,
        force_ensemble: bool = False,
    ) -> dict:
        """
        Genera pronóstico completo para el endpoint mejorado.

        Retorna:
          predicted_rate, confidence_interval, model_weights,
          feature_importance, backtesting_metrics, data_freshness,
          horizon_hours, predictions (lista completa horaria)
        """
        horizon_hours = _HORIZON_HOURS.get(horizon_key, 24)
        cache_key     = f'ml_forecast:{currency_pair}:{horizon_key}'

        if use_cache:
            cached = cache.get(cache_key)
            if cached:
                logger.debug("cache.hit key=%s", cache_key)
                return cached

        df = self.pipeline.build(currency_pair)

        # ── Obtener predicciones de cada modelo base ──
        base_preds = self._collect_base_predictions(currency_pair, df, horizon_hours)

        # ── Calcular pesos dinámicos ──
        weights = self.ensemble.compute_weights(currency_pair)

        # ── Combinar (ensemble o meta-learner si existe) ──
        try:
            ensemble_preds = self.ensemble.predict_with_meta(base_preds, currency_pair)
        except FileNotFoundError:
            ensemble_preds = self.ensemble.combine(base_preds, weights, horizon_hours)

        if not ensemble_preds:
            raise RuntimeError(f"No se pudieron generar predicciones para {currency_pair}")

        # ── Métricas de backtesting ──
        bt_metrics = self._backtesting_metrics(currency_pair, days=30)

        # ── Feature importance del XGBoost (más explicable) ──
        feat_importance = self._get_feature_importance(currency_pair)

        # ── Construir respuesta ──
        next_pred = ensemble_preds[0]
        result = {
            'currency_pair':        currency_pair,
            'horizon':              horizon_key,
            'horizon_hours':        horizon_hours,
            'predicted_rate':       round(next_pred['rate'], 4),
            'confidence_interval':  {
                'lower': round(next_pred['lower'], 4),
                'upper': round(next_pred['upper'], 4),
                'level': 0.95,
            },
            'model_weights':        weights,
            'feature_importance':   feat_importance,
            'backtesting_metrics':  bt_metrics,
            'data_freshness':       df.index[-1].isoformat(),
            'predictions':          [
                {
                    'datetime': p['prediction_date'].isoformat() if hasattr(p['prediction_date'], 'isoformat') else str(p['prediction_date']),
                    'rate':     round(p['rate'],  4),
                    'lower':    round(p['lower'], 4),
                    'upper':    round(p['upper'], 4),
                    'components': p['external_factors'].get('components', {}),
                }
                for p in ensemble_preds
            ],
            'generated_at': timezone.now().isoformat(),
        }

        # ── Guardar en caché ──
        ttl = _CACHE_TTL.get(horizon_key, 86_400)
        cache.set(cache_key, result, timeout=ttl)

        return result

    def _collect_base_predictions(self, currency_pair: str, df: pd.DataFrame, horizon: int) -> dict:
        base_preds = {}

        # XGBoost
        try:
            base_preds['XGBOOST'] = self.xgboost.predict(currency_pair, df, horizon)
        except Exception as exc:
            logger.warning("engine.base_pred_failed model=XGBOOST: %s", exc)

        # ARIMA
        try:
            base_preds['ARIMA'] = self.arima.predict(currency_pair, horizon)
        except Exception as exc:
            logger.warning("engine.base_pred_failed model=ARIMA: %s", exc)

        # BiLSTM
        try:
            base_preds['BILSTM'] = self.bilstm.predict(currency_pair, df, horizon)
        except Exception as exc:
            logger.warning("engine.base_pred_failed model=BILSTM: %s", exc)

        # Prophet (legacy service)
        try:
            from predictions.models import PredictionModel
            pm = PredictionModel.objects.get(model_type='PROPHET', currency_pair=currency_pair)
            from predictions.ml_service import ForexPredictionService
            svc  = ForexPredictionService()
            base_preds['PROPHET'] = svc._predict_prophet(pm, horizon)
        except Exception as exc:
            logger.warning("engine.base_pred_failed model=PROPHET: %s", exc)

        if not base_preds:
            raise RuntimeError("Ningún modelo base pudo generar predicciones")

        return base_preds

    # ── Métricas de backtesting ────────────────────────────────────────────────

    def _backtesting_metrics(self, currency_pair: str, days: int = 30) -> dict:
        """MAE, RMSE, MAPE promediados sobre las últimas `days` predicciones reales."""
        from predictions.models import Prediction
        from django.db.models import Avg, Min, Max

        cutoff = timezone.now() - timedelta(days=days)
        qs     = Prediction.objects.filter(
            currency_pair=currency_pair,
            actual_rate__isnull=False,
            created_at__gte=cutoff,
        )

        if not qs.exists():
            return {'available': False, 'period_days': days}

        agg = qs.aggregate(
            avg_mape=Avg('error_percentage'),
            min_mape=Min('error_percentage'),
            max_mape=Max('error_percentage'),
        )

        errors  = list(qs.values_list('error_percentage', flat=True))
        rates_t = list(qs.values_list('actual_rate', flat=True))
        rates_p = list(qs.values_list('predicted_rate', flat=True))

        mae  = float(np.mean([abs(float(a) - float(p)) for a, p in zip(rates_t, rates_p)]))
        rmse = float(np.sqrt(np.mean([(float(a) - float(p)) ** 2 for a, p in zip(rates_t, rates_p)])))

        return {
            'available':    True,
            'period_days':  days,
            'count':        len(errors),
            'mae':          round(mae, 6),
            'rmse':         round(rmse, 6),
            'mape_avg':     round(float(agg['avg_mape'] or 0), 4),
            'mape_min':     round(float(agg['min_mape'] or 0), 4),
            'mape_max':     round(float(agg['max_mape'] or 0), 4),
        }

    # ── Feature importance ────────────────────────────────────────────────────

    def _get_feature_importance(self, currency_pair: str) -> dict:
        """Extrae top-10 features de la última versión del modelo XGBoost."""
        try:
            from predictions.models import PredictionModel
            pm = PredictionModel.objects.get(model_type='XGBOOST', currency_pair=currency_pair)
            return pm.metrics.get('top_features', {})
        except Exception:
            return {}

    # ── Caché ─────────────────────────────────────────────────────────────────

    def _invalidate_cache(self, currency_pair: str):
        for key in _HORIZON_HOURS:
            cache.delete(f'ml_forecast:{currency_pair}:{key}')

    def cache_all_horizons(self, currency_pair: str):
        """Pre-calcula y cachea todos los horizontes (llamado por tarea horaria)."""
        for key in _HORIZON_HOURS:
            try:
                self.predict(currency_pair, horizon_key=key, use_cache=False)
                logger.info("cache.prewarmed pair=%s horizon=%s", currency_pair, key)
            except Exception as exc:
                logger.warning("cache.prewarm_failed pair=%s horizon=%s: %s", currency_pair, key, exc)

    # ── Actualización de pesos ────────────────────────────────────────────────

    def refresh_ensemble_weights(self, currency_pair: str):
        """Recalcula y persiste pesos del ensemble (llamado cada 4h)."""
        weights = self.ensemble.compute_weights(currency_pair)
        self.ensemble.save_weight_snapshot(currency_pair, weights)
        self._invalidate_cache(currency_pair)
        logger.info("ensemble.weights_refreshed pair=%s", currency_pair)
        return weights

    # ── Backtesting semanal ────────────────────────────────────────────────────

    def run_weekly_backtest(self, currency_pair: str) -> dict:
        """
        Evalúa precisión de los últimos 30 días y alerta si MAPE supera umbrales.
        """
        metrics = self._backtesting_metrics(currency_pair, days=30)
        mape    = metrics.get('mape_avg', 0)

        report = {
            'currency_pair': currency_pair,
            'metrics':       metrics,
            'alerts':        [],
        }

        for horizon, threshold in MAPE_ALERT_THRESHOLD.items():
            if mape > threshold:
                msg = (
                    f"MAPE {mape:.2f}% supera umbral {threshold}% "
                    f"para {currency_pair} (horizonte {horizon})"
                )
                report['alerts'].append(msg)
                logger.warning("backtest.mape_alert pair=%s mape=%.4f threshold=%.4f", currency_pair, mape, threshold)
                try:
                    from core.tasks import _emit_system_alert
                    _emit_system_alert('ml', msg, severity='MEDIUM')
                except Exception:
                    pass

        return report
