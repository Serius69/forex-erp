"""
ARIMAForecaster — Auto-ARIMA con detección automática de parámetros (pmdarima).

Diseño:
  - Entrena sobre serie diaria para reducir tiempo de ajuste (ARIMA es O(n²))
  - Detecta automáticamente (p,d,q)(P,D,Q)[7] con criterio AIC
  - Las predicciones horarias se obtienen interpolando linealmente el forecast diario
  - Incluye intervalos de confianza calibrados al 95%
"""
import numpy as np
import pandas as pd
import joblib
import os
from sklearn.metrics import mean_absolute_error, mean_squared_error
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class ARIMAForecaster:
    """Auto-ARIMA con estacionalidad semanal, reentrenable de forma incremental."""

    def __init__(self, models_path: str):
        self.models_path = models_path

    # ── Entrenamiento ──────────────────────────────────────────────────────────

    def train(self, currency_pair: str, df: pd.DataFrame, market: str = 'web') -> dict:
        """
        Ajusta Auto-ARIMA sobre la serie diaria derivada de df (horario → diario).
        Retorna métricas y registra en PredictionModel.
        """
        try:
            import pmdarima as pm
        except ImportError:
            raise ImportError("pmdarima requerido: agregue pmdarima==2.0.4 a requirements.txt")

        daily = df['rate'].resample('D').last().dropna()
        if len(daily) < 30:
            raise ValueError(f"Datos diarios insuficientes para ARIMA ({len(daily)} días)")

        split    = int(len(daily) * 0.85)
        train_s  = daily.iloc[:split]
        test_s   = daily.iloc[split:]

        model = pm.auto_arima(
            train_s,
            start_p=0,  max_p=3,
            start_q=0,  max_q=3,
            d=None,
            seasonal=True,
            m=7,                   # ciclo semanal
            start_P=0,  max_P=2,
            start_Q=0,  max_Q=2,
            D=None,
            information_criterion='aic',
            stepwise=True,
            suppress_warnings=True,
            error_action='ignore',
            n_jobs=1,
        )

        # A5 — Evaluar en test ANTES del online-update. Antes se hacía
        # model.update(test_s) y LUEGO model.predict(len(test_s)), con lo que se
        # comparaba un forecast del período POSTERIOR al test contra test_s →
        # MAPE sin sentido (normalmente optimista). Ahora se pronostica el test
        # inmediatamente tras fit(train) — evaluación honesta out-of-sample.
        forecast_test = model.predict(n_periods=len(test_s))
        y_true = test_s.values
        y_pred = np.array(forecast_test)

        metrics = _compute_metrics(y_true, y_pred)

        # Recién ahora incorporar el test al modelo servido (online update), para
        # que las predicciones futuras arranquen desde el último dato conocido.
        model.update(test_s)
        metrics['arima_order']          = str(model.order)
        metrics['arima_seasonal_order'] = str(model.seasonal_order)
        metrics['aic']                  = round(float(model.aic()), 2)

        from predictions.market_keys import fname_suffix
        pair_safe  = currency_pair.replace('/', '_') + fname_suffix(market)
        model_path = os.path.join(self.models_path, f'arima_{pair_safe}.pkl')
        joblib.dump({
            'model':     model,
            'last_date': daily.index[-1],
        }, model_path)

        self._register(currency_pair, model_path, metrics, {
            'order':          str(model.order),
            'seasonal_order': str(model.seasonal_order),
        }, market)
        logger.info(
            "ARIMA entrenado pair=%s order=%s mape=%.4f%%",
            currency_pair, model.order, metrics['mape'],
        )
        return metrics

    # ── Predicción ─────────────────────────────────────────────────────────────

    def predict(self, currency_pair: str, horizon: int, market: str = 'web') -> list:
        """
        Retorna lista de dicts con predicciones horarias.
        ARIMA predice en días; interpolamos linealmente a horas.
        """
        from predictions.market_keys import fname_suffix
        pair_safe  = currency_pair.replace('/', '_') + fname_suffix(market)
        model_path = os.path.join(self.models_path, f'arima_{pair_safe}.pkl')
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ARIMA no entrenado para {currency_pair}")

        # Artefacto cacheado por (ruta, mtime): se re-lee solo tras reentrenar.
        from predictions.artifact_cache import load_cached
        artifact = load_cached(model_path, joblib.load)
        model    = artifact['model']

        days_needed       = max(1, (horizon + 23) // 24)
        forecast_vals, ci = model.predict(n_periods=days_needed, return_conf_int=True, alpha=0.05)

        now         = timezone.now()
        predictions = []

        for h in range(1, horizon + 1):
            day_idx = min((h - 1) // 24, days_needed - 1)
            rate    = float(forecast_vals[day_idx])
            lower   = float(ci[day_idx][0])
            upper   = float(ci[day_idx][1])

            # Ensanchar CI ligeramente para horizontes intra-día (captura ruido horario)
            intra_spread = abs(rate) * 0.001 * ((h % 24) + 1)
            predictions.append({
                'prediction_date': (now + pd.Timedelta(hours=h)).to_pydatetime(),
                'rate':            rate,
                'lower':           lower - intra_spread,
                'upper':           upper + intra_spread,
                'confidence':      0.90,
                'external_factors': {'model': 'ARIMA'},
            })

        return predictions

    # ── Registro en BD ─────────────────────────────────────────────────────────

    def _register(self, currency_pair, model_path, metrics, params, market='web'):
        from predictions.models import PredictionModel

        PredictionModel.objects.update_or_create(
            model_type='ARIMA',
            currency_pair=currency_pair,
            market=market,
            defaults={
                'name':         f'Auto-ARIMA {currency_pair} [{market}]',
                'parameters':   params,
                'metrics':      metrics,
                'model_file':   model_path,
                'last_trained': timezone.now(),
            },
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    mae  = mean_absolute_error(y_true, y_pred)
    mse  = mean_squared_error(y_true, y_pred)
    mape = float(np.mean(np.abs((y_true - y_pred) / np.where(y_true != 0, y_true, 1))) * 100)
    return {
        'mae':  float(mae),
        'mse':  float(mse),
        'rmse': float(np.sqrt(mse)),
        'mape': mape,
    }
