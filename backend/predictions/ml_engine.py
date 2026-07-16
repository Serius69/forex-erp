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

# Mínimo de predicciones evaluadas para juzgar la calibración de intervalos.
MIN_INTERVAL_EVAL_SAMPLES = 20


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

    def train_all(self, currency_pair: str, include: list = None, market: str = 'web') -> dict:
        """
        Entrena los modelos especificados en `include` (default: todos)
        sobre la serie `market` ('web' | 'competencia' | 'empresa').
        Retorna dict {model: metrics | error}.
        """
        models_to_train = include or self.ALL_MODELS
        results         = {}

        df = self.pipeline.build(currency_pair, market=market)

        for model_name in models_to_train:
            try:
                results[model_name] = self._train_one(model_name, currency_pair, df, market)
            except Exception as exc:
                logger.error("engine.train_failed pair=%s model=%s market=%s error=%s", currency_pair, model_name, market, exc)
                results[model_name] = {'status': 'error', 'error': str(exc)}

        # Invalidar caché después de reentrenar
        self._invalidate_cache(currency_pair, market)
        return results

    def _train_one(self, model_name: str, currency_pair: str, df: pd.DataFrame, market: str = 'web') -> dict:
        if model_name == 'xgboost':
            return self.xgboost.train(currency_pair, df, market=market)
        elif model_name == 'arima':
            return self.arima.train(currency_pair, df, market=market)
        elif model_name == 'bilstm':
            return self.bilstm.train(currency_pair, df, market=market)
        elif model_name == 'prophet':
            # Delega al servicio legacy (ya tiene su propio entrenamiento)
            from predictions.ml_service import ForexPredictionService
            svc = ForexPredictionService()
            _, metrics = svc.train_prophet_model(currency_pair, market=market)
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
        market: str = 'web',
        df: 'pd.DataFrame | None' = None,
    ) -> dict:
        """
        Genera pronóstico completo para el endpoint mejorado.

        Retorna:
          predicted_rate, confidence_interval, model_weights,
          feature_importance, backtesting_metrics, data_freshness,
          horizon_hours, predictions (lista completa horaria)
        """
        horizon_hours = _HORIZON_HOURS.get(horizon_key, 24)
        cache_key     = f'ml_forecast:{currency_pair}:{market}:{horizon_key}'

        if use_cache:
            cached = cache.get(cache_key)
            if cached:
                logger.debug("cache.hit key=%s", cache_key)
                return cached

        # El df de features es idéntico para (par, market) e independiente del
        # horizonte; permitir pasarlo evita reconstruir el pipeline (3 años × 40+
        # features) una vez por horizonte en cache_all_horizons.
        if df is None:
            df = self.pipeline.build(currency_pair, market=market)

        # ── Obtener predicciones de cada modelo base ──
        base_preds = self._collect_base_predictions(currency_pair, df, horizon_hours, market)

        # ── Calcular pesos dinámicos ──
        weights = self.ensemble.compute_weights(currency_pair, market=market)

        # ── Combinar (ensemble o meta-learner si existe) ──
        try:
            ensemble_preds = self.ensemble.predict_with_meta(base_preds, currency_pair, market=market)
        except FileNotFoundError:
            ensemble_preds = self.ensemble.combine(base_preds, weights, horizon_hours)

        if not ensemble_preds:
            raise RuntimeError(f"No se pudieron generar predicciones para {currency_pair}")

        # ── Calibración conformal: CIs con cobertura real, no nominal ──
        try:
            ensemble_preds = self.ensemble.conformalize(ensemble_preds, currency_pair, market=market)
        except Exception as exc:
            logger.warning("conformal.skip pair=%s: %s", currency_pair, exc)

        # ── Métricas de backtesting ──
        bt_metrics = self._backtesting_metrics(currency_pair, days=30, market=market)

        # ── Feature importance del XGBoost (más explicable) ──
        feat_importance = self._get_feature_importance(currency_pair, market)

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
                'level': next_pred.get('confidence', 0.95),
                'method': (next_pred.get('external_factors') or {}).get('interval_method', 'heuristic_union'),
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

    def _collect_base_predictions(self, currency_pair: str, df: pd.DataFrame, horizon: int, market: str = 'web') -> dict:
        base_preds = {}

        # XGBoost
        try:
            base_preds['XGBOOST'] = self.xgboost.predict(currency_pair, df, horizon, market=market)
        except Exception as exc:
            logger.warning("engine.base_pred_failed model=XGBOOST: %s", exc)

        # ARIMA
        try:
            base_preds['ARIMA'] = self.arima.predict(currency_pair, horizon, market=market)
        except Exception as exc:
            logger.warning("engine.base_pred_failed model=ARIMA: %s", exc)

        # BiLSTM
        try:
            base_preds['BILSTM'] = self.bilstm.predict(currency_pair, df, horizon, market=market)
        except Exception as exc:
            logger.warning("engine.base_pred_failed model=BILSTM: %s", exc)

        # Prophet (legacy service)
        try:
            from predictions.models import PredictionModel
            pm = PredictionModel.objects.get(model_type='PROPHET', currency_pair=currency_pair, market=market)
            from predictions.ml_service import ForexPredictionService
            svc  = ForexPredictionService()
            base_preds['PROPHET'] = svc._predict_prophet(pm, horizon)
        except Exception as exc:
            logger.warning("engine.base_pred_failed model=PROPHET: %s", exc)

        if not base_preds:
            raise RuntimeError("Ningún modelo base pudo generar predicciones")

        return base_preds

    # ── Métricas de backtesting ────────────────────────────────────────────────

    def _backtesting_metrics(self, currency_pair: str, days: int = 30, market: str = 'web') -> dict:
        """MAE, RMSE, MAPE promediados sobre las últimas `days` predicciones reales."""
        from predictions.models import Prediction
        from django.db.models import Avg, Min, Max

        cutoff = timezone.now() - timedelta(days=days)
        qs     = Prediction.objects.filter(
            currency_pair=currency_pair,
            model__market=market,
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

    # ── Calibración de intervalos conformales ─────────────────────────────────

    def _interval_calibration(self, currency_pair: str, days: int = 30) -> dict:
        """Valida la CALIDAD de los intervalos conformales sobre las predicciones
        reales de los últimos `days` días.

        Cierra el ciclo de la calibración conformal (S36): comprueba que el 95 %
        prometido se cumple de verdad (cobertura empírica ≥ nominal) y que los
        intervalos no son inútilmente anchos (Winkler score). El MAPE mide el
        punto; esto mide la *incertidumbre*.
        """
        from predictions.models import Prediction
        from predictions.conformal import interval_calibration_report

        cutoff = timezone.now() - timedelta(days=days)
        rows = list(
            Prediction.objects
            .filter(
                currency_pair=currency_pair,
                actual_rate__isnull=False,
                created_at__gte=cutoff,
            )
            .values_list('actual_rate', 'confidence_lower',
                         'confidence_upper', 'confidence_score')
        )
        # Descartar filas con intervalo degenerado o ausente (lower >= upper).
        clean = [
            r for r in rows
            if r[1] is not None and r[2] is not None and float(r[1]) < float(r[2])
        ]
        if len(clean) < MIN_INTERVAL_EVAL_SAMPLES:
            return {'available': False, 'period_days': days, 'count': len(clean)}

        y_true = [float(r[0]) for r in clean]
        lower  = [float(r[1]) for r in clean]
        upper  = [float(r[2]) for r in clean]
        # Nivel nominal = confidence_score promedio (persistido como 0.95).
        scores  = [float(r[3]) for r in clean if r[3]]
        nominal = sum(scores) / len(scores) if scores else 0.95
        nominal = min(max(nominal, 0.5), 0.999)

        report = interval_calibration_report(y_true, lower, upper, nominal=nominal)
        report['available']   = True
        report['period_days'] = days
        return report

    # ── Feature importance ────────────────────────────────────────────────────

    def _get_feature_importance(self, currency_pair: str, market: str = 'web') -> dict:
        """Extrae top-10 features de la última versión del modelo XGBoost."""
        try:
            from predictions.models import PredictionModel
            pm = PredictionModel.objects.get(model_type='XGBOOST', currency_pair=currency_pair, market=market)
            return pm.metrics.get('top_features', {})
        except Exception:
            return {}

    # ── Caché ─────────────────────────────────────────────────────────────────

    def _invalidate_cache(self, currency_pair: str, market: str = 'web'):
        for key in _HORIZON_HOURS:
            cache.delete(f'ml_forecast:{currency_pair}:{market}:{key}')

    def cache_all_horizons(self, currency_pair: str, market: str = 'web'):
        """Pre-calcula y cachea todos los horizontes (llamado por tarea horaria)."""
        # Construir el pipeline UNA vez y reusarlo en los 4 horizontes (antes se
        # reconstruía por cada predict → O(4×build) sobre 3 años de datos).
        try:
            df = self.pipeline.build(currency_pair, market=market)
        except Exception as exc:
            logger.warning("cache.prewarm_build_failed pair=%s market=%s: %s", currency_pair, market, exc)
            df = None
        for key in _HORIZON_HOURS:
            try:
                self.predict(currency_pair, horizon_key=key, use_cache=False, market=market, df=df)
                logger.info("cache.prewarmed pair=%s market=%s horizon=%s", currency_pair, market, key)
            except Exception as exc:
                logger.warning("cache.prewarm_failed pair=%s market=%s horizon=%s: %s", currency_pair, market, key, exc)

    # ── Actualización de pesos ────────────────────────────────────────────────

    def refresh_ensemble_weights(self, currency_pair: str, market: str = 'web'):
        """Recalcula y persiste pesos del ensemble (llamado cada 4h)."""
        weights = self.ensemble.compute_weights(currency_pair, market=market)
        self.ensemble.save_weight_snapshot(currency_pair, weights, market=market)
        # RE-CACHEAR con los pesos nuevos, no solo invalidar: dejar la caché
        # vacía hacía que el endpoint sirviera el fallback 'inference' durante
        # hasta 1h (hasta el próximo cache_forecast_hourly) cada 4h. Si el
        # re-warm falla, caer al invalidate simple.
        try:
            self.cache_all_horizons(currency_pair, market=market)
        except Exception as exc:
            logger.warning("weights_refresh_recache_failed pair=%s market=%s: %s",
                           currency_pair, market, exc)
            self._invalidate_cache(currency_pair, market)
        logger.info("ensemble.weights_refreshed pair=%s market=%s", currency_pair, market)
        return weights

    # ── Backtesting semanal ────────────────────────────────────────────────────

    def run_weekly_backtest(self, currency_pair: str) -> dict:
        """
        Evalúa precisión de los últimos 30 días y alerta si MAPE supera umbrales.
        """
        metrics     = self._backtesting_metrics(currency_pair, days=30)
        mape        = metrics.get('mape_avg', 0)
        calibration = self._interval_calibration(currency_pair, days=30)

        report = {
            'currency_pair':       currency_pair,
            'metrics':             metrics,
            'interval_calibration': calibration,
            'alerts':              [],
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

        # Alerta de miscalibración: el intervalo conformal dejó de cubrir lo
        # prometido → recalibrar (residuos obsoletos o cambio de régimen).
        if calibration.get('available') and calibration.get('undercovered'):
            cov = calibration['coverage']
            nom = calibration['nominal']
            msg = (
                f"Intervalos {currency_pair} sub-cubren: cobertura empírica "
                f"{cov:.0%} < nominal {nom:.0%} (n={calibration['n']}) — recalibrar conformal"
            )
            report['alerts'].append(msg)
            logger.warning(
                "backtest.coverage_alert pair=%s coverage=%.4f nominal=%.4f n=%d",
                currency_pair, cov, nom, calibration['n'],
            )
            try:
                from core.tasks import _emit_system_alert
                _emit_system_alert('ml', msg, severity='MEDIUM')
            except Exception:
                pass

        return report
