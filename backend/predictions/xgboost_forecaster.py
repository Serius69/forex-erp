"""
XGBoostForecaster — gradient boosting con lag features + indicadores técnicos.

Ventajas sobre LSTM/Prophet para series de divisas:
  - Captura no-linealidades sin necesidad de normalización
  - Lag features de 1h → 168h (una semana) dan contexto temporal robusto
  - Feature importance explicable para la API
  - Entrenamiento rápido (~30s) vs LSTM (~5min)
"""
import numpy as np
import pandas as pd
import joblib
import os
from sklearn.metrics import mean_absolute_error, mean_squared_error
import logging

logger = logging.getLogger(__name__)

# Features ordenados por importancia esperada
XGBOOST_FEATURES = [
    # Lags (más importantes para XGBoost en series temporales)
    'lag_1', 'lag_2', 'lag_3', 'lag_6', 'lag_12', 'lag_24', 'lag_48', 'lag_168',
    # Tendencia
    'ma_7', 'ma_14', 'ma_30', 'ma_90', 'ema_12', 'ema_26',
    # Momentum/MACD
    'macd', 'macd_signal', 'macd_hist',
    # Osciladores
    'rsi', 'bb_width', 'bb_pct',
    # Volatilidad / riesgo
    'atr_14', 'volatility_7', 'volatility_14', 'volatility_30',
    # Retornos
    'pct_change_1', 'pct_change_7', 'pct_change_30',
    # Calendario
    'hour', 'day_of_week', 'is_weekend', 'month', 'quarter',
    'is_london_session', 'is_new_york_session', 'is_overlap_session',
    # Macro
    'international_rate', 'oil_price', 'interest_rate', 'inflation_rate',
]

DEFAULT_PARAMS = {
    'n_estimators':      500,
    'max_depth':         6,
    'learning_rate':     0.05,
    'subsample':         0.8,
    'colsample_bytree':  0.8,
    'min_child_weight':  3,
    'gamma':             0.1,
    'reg_alpha':         0.1,
    'reg_lambda':        1.0,
    'tree_method':       'hist',
    'objective':         'reg:squarederror',
    'random_state':      42,
    'n_jobs':            -1,
}


class XGBoostForecaster:
    """Gradient boosting para pronóstico de tasas de cambio."""

    def __init__(self, models_path: str):
        self.models_path = models_path

    # ── Entrenamiento ──────────────────────────────────────────────────────────

    def train(self, currency_pair: str, df: pd.DataFrame, params: dict = None, market: str = 'web') -> dict:
        """
        Entrena XGBoost sobre el DataFrame del pipeline.
        Retorna métricas y registra el modelo en PredictionModel.
        """
        try:
            import xgboost as xgb
        except ImportError:
            raise ImportError("xgboost requerido: agregue xgboost==2.0.3 a requirements.txt")

        features = [f for f in XGBOOST_FEATURES if f in df.columns]
        data = df[features + ['rate']].dropna()

        X = data[features].values.astype(np.float32)
        y = data['rate'].values.astype(np.float32)

        # Split temporal (sin shuffle — es una serie de tiempo)
        split   = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        used_params = {**DEFAULT_PARAMS, **(params or {})}
        model = xgb.XGBRegressor(**used_params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        y_pred   = model.predict(X_test)
        metrics  = _compute_metrics(y_test, y_pred)
        metrics['features_used'] = len(features)

        # Top-10 features por importancia (para la API)
        importances = dict(zip(features, model.feature_importances_.tolist()))
        top10 = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:10]
        metrics['top_features'] = {k: round(v, 4) for k, v in top10}

        from predictions.market_keys import fname_suffix
        pair_safe  = currency_pair.replace('/', '_') + fname_suffix(market)
        model_path = os.path.join(self.models_path, f'xgboost_{pair_safe}.pkl')
        joblib.dump(
            {'model': model, 'features': features, 'params': used_params},
            model_path,
        )

        self._register(currency_pair, model_path, metrics, used_params, features, market)
        logger.info("XGBoost entrenado pair=%s mape=%.4f%%", currency_pair, metrics['mape'])
        return metrics

    # ── Predicción ─────────────────────────────────────────────────────────────

    def predict(self, currency_pair: str, df_recent: pd.DataFrame, horizon: int, market: str = 'web') -> list:
        """
        Predicción iterativa hora a hora.
        Actualiza lags y features de calendario en cada paso.
        """
        from predictions.market_keys import fname_suffix
        pair_safe  = currency_pair.replace('/', '_') + fname_suffix(market)
        model_path = os.path.join(self.models_path, f'xgboost_{pair_safe}.pkl')
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"XGBoost no entrenado para {currency_pair}")

        artifact = joblib.load(model_path)
        model    = artifact['model']
        features = artifact['features']

        df      = df_recent.copy()
        last_ts = df.index[-1]

        # ATR base para CI (proporcional a la incertidumbre del horizonte)
        atr_base = float(df['atr_14'].iloc[-1]) if 'atr_14' in df.columns else float(df['rate'].iloc[-1]) * 0.005

        predictions = []
        for h in range(1, horizon + 1):
            pred_ts = last_ts + pd.Timedelta(hours=h)
            row     = df.iloc[-1].copy()

            # Actualizar lags usando el histórico acumulado
            rates = df['rate'].values
            for lag in (1, 2, 3, 6, 12, 24, 48, 168):
                key = f'lag_{lag}'
                if key in features:
                    row[key] = rates[-lag] if lag <= len(rates) else rates[0]

            # Actualizar features de calendario
            row['hour']              = pred_ts.hour
            row['day_of_week']       = pred_ts.dayofweek
            row['is_weekend']        = int(pred_ts.dayofweek >= 5)
            row['month']             = pred_ts.month
            row['quarter']           = (pred_ts.month - 1) // 3 + 1
            row['is_london_session']   = int(8  <= pred_ts.hour < 16)
            row['is_new_york_session'] = int(13 <= pred_ts.hour < 22)
            row['is_overlap_session']  = int(13 <= pred_ts.hour < 16)

            feat_vec   = np.array([[row.get(f, 0.0) for f in features]], dtype=np.float32)
            rate_pred  = float(model.predict(feat_vec)[0])

            # CI: ±1.96σ donde σ crece con la raíz del horizonte (walk-forward noise)
            sigma = atr_base * np.sqrt(h)
            predictions.append({
                'prediction_date': pred_ts.to_pydatetime(),
                'rate':            rate_pred,
                'lower':           rate_pred - 1.96 * sigma,
                'upper':           rate_pred + 1.96 * sigma,
                'confidence':      max(0.50, 0.95 - h * 0.008),
                'external_factors': {
                    'model':        'XGBOOST',
                    'top_features': artifact.get('metrics', {}).get('top_features', {}),
                },
            })

            # Añadir fila predicha al DataFrame para que la próxima iteración tenga lags correctos
            new_row            = row.copy()
            new_row['rate']    = rate_pred
            new_row_df         = pd.DataFrame([new_row], index=[pred_ts])
            df = pd.concat([df, new_row_df])

        return predictions

    # ── Registro en BD ─────────────────────────────────────────────────────────

    def _register(self, currency_pair, model_path, metrics, params, features, market='web'):
        from predictions.models import PredictionModel
        from django.utils import timezone

        PredictionModel.objects.update_or_create(
            model_type='XGBOOST',
            currency_pair=currency_pair,
            market=market,
            defaults={
                'name':         f'XGBoost {currency_pair} [{market}]',
                'parameters':   {'params': params, 'features': features},
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
