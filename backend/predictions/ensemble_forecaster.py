"""
EnsembleForecaster — combinación dinámica de modelos base con Ridge meta-learner.

Estrategia de pesos:
  1. Se calculan pesos basados en MAPE de predicciones reales de los últimos N días.
  2. Si no hay historial de errores, se usan las métricas de entrenamiento (fallback).
  3. Los pesos se guardan en EnsembleWeightHistory para auditoría.
  4. El meta-learner (Ridge) se entrena periódicamente sobre predicciones históricas.

El ensemble combina: PROPHET · BILSTM · XGBOOST · ARIMA
"""
import math
import numpy as np
import pandas as pd
import joblib
import os
from datetime import datetime
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

BASE_MODELS = ['PROPHET', 'BILSTM', 'XGBOOST', 'ARIMA']
WEIGHT_WINDOW_DAYS = 30   # ventana para calcular MAPE reciente


class EnsembleForecaster:
    """Ensemble con pesos dinámicos y meta-learner opcional."""

    def __init__(self, models_path: str):
        self.models_path = models_path

    # ── Pesos dinámicos ────────────────────────────────────────────────────────

    def compute_weights(self, currency_pair: str, window_days: int = WEIGHT_WINDOW_DAYS, market: str = 'web') -> dict:
        """
        Calcula pesos inversamente proporcionales al MAPE de predicciones reales
        de los últimos `window_days` días. Fallback a métricas de entrenamiento.
        """
        from predictions.models import Prediction
        from django.db.models import Avg

        cutoff  = timezone.now() - pd.Timedelta(days=window_days)
        weights = {}

        for model_type in BASE_MODELS:
            result = (
                Prediction.objects
                .filter(
                    currency_pair=currency_pair,
                    model__model_type=model_type,
                    model__market=market,
                    actual_rate__isnull=False,
                    created_at__gte=cutoff,
                )
                .aggregate(avg_mape=Avg('error_percentage'))
            )
            mape = result['avg_mape']

            if mape and mape > 0:
                weights[model_type] = 1.0 / mape
            else:
                weights[model_type] = self._fallback_weight(currency_pair, model_type, market)

        # Normalizar
        total = sum(weights.values()) or 1.0
        normalized = {k: round(v / total, 4) for k, v in weights.items()}
        logger.info("ensemble.weights pair=%s weights=%s", currency_pair, normalized)
        return normalized

    def _fallback_weight(self, currency_pair: str, model_type: str, market: str = 'web') -> float:
        """Usa MAPE de entrenamiento como proxy cuando no hay historial real."""
        from predictions.models import PredictionModel
        try:
            pm   = PredictionModel.objects.get(model_type=model_type, currency_pair=currency_pair, market=market)
            mape = pm.metrics.get('mape', 5.0)
            return 1.0 / max(float(mape), 0.01)
        except Exception:
            # Sin modelo entrenado (p.ej. ARIMA cuando pmdarima/scipy no están):
            # peso 0 para que NO contamine el ensemble. Antes devolvía 1.0, que al
            # ser ~5× el 1/MAPE de los modelos buenos hacía dominar al fantasma.
            return 0.0

    def save_weight_snapshot(self, currency_pair: str, weights: dict, market: str = 'web'):
        """Persiste snapshot de pesos para análisis histórico."""
        try:
            from predictions.models import EnsembleWeightHistory
            EnsembleWeightHistory.objects.create(
                currency_pair=currency_pair,
                market=market,
                weights=weights,
            )
        except Exception as exc:
            logger.warning("ensemble.save_weights_failed: %s", exc)

    # ── Combinación de predicciones ────────────────────────────────────────────

    def combine(
        self,
        base_preds: dict,   # {model_type: [{'rate':..,'lower':..,'upper':..,...}]}
        weights: dict,
        horizon: int,
    ) -> list:
        """
        Promedio ponderado de las predicciones base.

        CI (pre-conformal): banda SIMÉTRICA alrededor del punto ensemble, de ancho
        igual al promedio PONDERADO de los anchos de los modelos que contribuyen.
        Antes se tomaba la unión (min lower, max upper) de CIs heterogéneos, lo que
        inflaba el intervalo cuando un modelo con banda plana o muy ancha (p.ej.
        Prophet-naive o XGBoost sin CI real) estiraba los extremos → CI mal calibrado
        justo cuando la conformalización se salta por pocos residuos. El ancho
        ponderado ignora a los modelos de peso ~0 y no se deja arrastrar por outliers.
        """
        predictions = []

        for h in range(horizon):
            rates, w_sum, width_w_sum = [], 0.0, 0.0

            for model_type, preds in base_preds.items():
                if h >= len(preds):
                    continue
                w = weights.get(model_type, 0.0)
                if w <= 0:
                    continue
                rates.append(preds[h]['rate']  * w)
                width_w_sum += w * (preds[h]['upper'] - preds[h]['lower'])
                w_sum += w

            if not rates:
                continue

            ensemble_rate = sum(rates) / (w_sum or 1.0)
            # Semi-ancho = mitad del ancho promedio ponderado de las bandas base.
            half_width    = (width_w_sum / (w_sum or 1.0)) / 2.0

            # Fecha de referencia desde el primer modelo disponible
            ref_list = next(iter(base_preds.values()), [])
            pred_ts  = ref_list[h]['prediction_date'] if h < len(ref_list) else None

            predictions.append({
                'prediction_date': pred_ts,
                'rate':            ensemble_rate,
                'lower':           ensemble_rate - half_width,
                'upper':           ensemble_rate + half_width,
                'confidence':      0.95,
                'external_factors': {
                    'model':      'ENSEMBLE',
                    'weights':    {k: round(v, 4) for k, v in weights.items()},
                    'components': {
                        mt: round(ps[h]['rate'], 4)
                        for mt, ps in base_preds.items()
                        if h < len(ps)
                    },
                },
            })

        return predictions

    # ── Calibración conformal de intervalos ───────────────────────────────────

    def conformalize(
        self,
        predictions: list,
        currency_pair: str,
        alpha: float = 0.05,
        lookback_days: int = 90,
        market: str = 'web',
    ) -> list:
        """
        Reemplaza los CIs heurísticos (unión de CIs base) por intervalos split
        conformal con cobertura garantizada 1−alpha, calibrados con los residuos
        reales (actual − predicho) de los últimos `lookback_days` días.

        Prefiere residuos del propio ENSEMBLE; si son pocos, agrega los de todos
        los modelos. Sin residuos suficientes devuelve las predicciones intactas.
        """
        from predictions.models import Prediction
        from predictions.conformal import MIN_CALIBRATION_SAMPLES, calibrate_predictions

        cutoff = timezone.now() - pd.Timedelta(days=lookback_days)
        base_qs = Prediction.objects.filter(
            currency_pair=currency_pair,
            model__market=market,
            actual_rate__isnull=False,
            created_at__gte=cutoff,
        )
        rows = list(
            base_qs.filter(model__model_type='ENSEMBLE')
            .values_list('actual_rate', 'predicted_rate')
        )
        if len(rows) < MIN_CALIBRATION_SAMPLES:
            rows = list(base_qs.values_list('actual_rate', 'predicted_rate'))

        residuals = [float(actual) - float(pred) for actual, pred in rows]

        # Escala del ancho por horizonte: los residuos vienen de predicciones a
        # 24 h (ENSEMBLE), así que el cuantil conformal cubre el error a 24 h.
        # Bajo un supuesto de random-walk el error de pronóstico crece ~ sqrt(h);
        # escalamos cada paso por sqrt(h/24) para que 168 h (7 d) reciba un
        # intervalo MÁS ANCHO que 24 h y no quede sub-cubierto.
        scales = self._horizon_scales(predictions, reference_hours=24.0)
        calibrated = calibrate_predictions(predictions, residuals, alpha=alpha,
                                           horizon_scale=scales)
        if calibrated is not predictions:
            logger.info(
                "conformal.applied pair=%s n_residuals=%d alpha=%.3f",
                currency_pair, len(residuals), alpha,
            )
        return calibrated

    @staticmethod
    def _horizon_scales(predictions: list, reference_hours: float = 24.0) -> list:
        """Factor de ensanchado sqrt(h / reference_hours) por predicción.

        ``h`` = horas hacia adelante de cada paso, derivadas de ``prediction_date``
        respecto a ahora. Si la fecha no es interpretable se cae al índice del paso
        (paso horario: 1 h, 2 h, …). Se acota a ≥ 1 h para no encoger por debajo del
        horizonte de calibración.
        """
        now = timezone.now()
        scales = []
        for i, pred in enumerate(predictions):
            hours_ahead = None
            ts = pred.get('prediction_date')
            dt = None
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts)
                except ValueError:
                    dt = None
            elif hasattr(ts, 'timestamp'):     # datetime / pandas.Timestamp
                dt = ts
            if dt is not None:
                try:
                    hours_ahead = (dt - now).total_seconds() / 3600.0
                except (TypeError, ValueError):
                    hours_ahead = None
            if hours_ahead is None or hours_ahead <= 0:
                hours_ahead = float(i + 1)     # fallback: paso horario
            hours_ahead = max(hours_ahead, 1.0)
            scales.append(math.sqrt(hours_ahead / reference_hours))
        return scales

    # ── Meta-learner (Ridge stacking) ─────────────────────────────────────────

    def train_meta_learner(self, currency_pair: str, lookback_days: int = 90, market: str = 'web') -> dict:
        """
        Entrena un Ridge Regression sobre las predicciones históricas de los modelos base.
        Requiere que predictions.actual_rate esté poblado.
        """
        from sklearn.linear_model import Ridge
        from sklearn.metrics import mean_absolute_error
        from predictions.models import Prediction

        cutoff = timezone.now() - pd.Timedelta(days=lookback_days)
        rows   = []

        for model_type in BASE_MODELS:
            qs = (
                Prediction.objects
                .filter(
                    currency_pair=currency_pair,
                    model__model_type=model_type,
                    model__market=market,
                    actual_rate__isnull=False,
                    created_at__gte=cutoff,
                )
                .values('prediction_date', 'predicted_rate', 'actual_rate')
            )
            for r in qs:
                rows.append({
                    'date':  r['prediction_date'],
                    'model': model_type,
                    'pred':  float(r['predicted_rate']),
                    'actual': float(r['actual_rate']),
                })

        if not rows:
            raise ValueError(f"Sin datos suficientes para meta-learner de {currency_pair}")

        df = pd.DataFrame(rows)

        # Pivotar: filas = timestamp, columnas = predicción por modelo
        pivot = df.pivot_table(index='date', columns='model', values='pred', aggfunc='mean')
        actuals = df.groupby('date')['actual'].mean()

        aligned = pivot.join(actuals).dropna()
        if len(aligned) < 20:
            raise ValueError("Insuficientes timestamps comunes entre modelos para meta-learner")

        X = aligned[BASE_MODELS].values
        y = aligned['actual'].values

        split   = int(len(X) * 0.8)
        ridge   = Ridge(alpha=1.0)
        ridge.fit(X[:split], y[:split])
        y_pred  = ridge.predict(X[split:])
        mae     = mean_absolute_error(y[split:], y_pred)
        mape    = float(np.mean(np.abs((y[split:] - y_pred) / np.where(y[split:] != 0, y[split:], 1))) * 100)

        from predictions.market_keys import fname_suffix
        pair_safe     = currency_pair.replace('/', '_') + fname_suffix(market)
        meta_path     = os.path.join(self.models_path, f'meta_ridge_{pair_safe}.pkl')
        joblib.dump({'model': ridge, 'features': BASE_MODELS}, meta_path)

        logger.info("meta_learner pair=%s mae=%.4f mape=%.4f%%", currency_pair, mae, mape)
        return {'mae': float(mae), 'mape': mape, 'model_path': meta_path}

    def predict_with_meta(
        self,
        base_preds: dict,
        currency_pair: str,
        market: str = 'web',
    ) -> list:
        """
        Usa el meta-learner Ridge si está disponible; si no, fallback a weighted average.
        """
        from predictions.market_keys import fname_suffix
        pair_safe = currency_pair.replace('/', '_') + fname_suffix(market)
        meta_path = os.path.join(self.models_path, f'meta_ridge_{pair_safe}.pkl')

        if not os.path.exists(meta_path):
            raise FileNotFoundError("Meta-learner no entrenado")

        artifact = joblib.load(meta_path)
        ridge    = artifact['model']
        features = artifact['features']

        horizon     = min(len(v) for v in base_preds.values() if v)
        predictions = []

        for h in range(horizon):
            feat_vec = np.array([[
                base_preds[mt][h]['rate'] if mt in base_preds and h < len(base_preds[mt]) else 0.0
                for mt in features
            ]])
            rate_pred = float(ridge.predict(feat_vec)[0])

            lowers = [base_preds[mt][h]['lower'] for mt in features if mt in base_preds and h < len(base_preds[mt])]
            uppers = [base_preds[mt][h]['upper'] for mt in features if mt in base_preds and h < len(base_preds[mt])]

            ref_list = next(iter(base_preds.values()), [])
            pred_ts  = ref_list[h]['prediction_date'] if h < len(ref_list) else None

            predictions.append({
                'prediction_date': pred_ts,
                'rate':            rate_pred,
                'lower':           min(lowers) if lowers else rate_pred * 0.98,
                'upper':           max(uppers) if uppers else rate_pred * 1.02,
                'confidence':      0.95,
                'external_factors': {
                    'model': 'ENSEMBLE_RIDGE',
                    'components': {
                        mt: round(base_preds[mt][h]['rate'], 4)
                        for mt in features
                        if mt in base_preds and h < len(base_preds[mt])
                    },
                },
            })

        return predictions
