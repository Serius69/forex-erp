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

        # A3 — construcción supervisada SIN fuga (target = rate[t+1]); ver
        # build_supervised para el razonamiento completo.
        X, y, _ = build_supervised(df, features)

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

        A3 — consistencia train/serve: en cada paso los indicadores técnicos
        (lags, ma/ema/macd/rsi/bb, volatilidad, retornos) se RECALCULAN de forma
        causal sobre la serie acumulada (histórico + filas ya predichas), en vez
        de congelar los de la última fila real. Como el modelo se entrenó con
        target = rate[t+1], predecir desde los features de t da rate[t+1].
        """
        from predictions.market_keys import fname_suffix
        from predictions.data_pipeline import ForexDataPipeline
        pair_safe  = currency_pair.replace('/', '_') + fname_suffix(market)
        model_path = os.path.join(self.models_path, f'xgboost_{pair_safe}.pkl')
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"XGBoost no entrenado para {currency_pair}")

        artifact = joblib.load(model_path)
        model    = artifact['model']
        features = artifact['features']

        pipe    = ForexDataPipeline()
        df      = df_recent.copy()
        last_ts = df.index[-1]

        # ATR base para CI (proporcional a la incertidumbre del horizonte)
        atr_base = float(df['atr_14'].iloc[-1]) if 'atr_14' in df.columns else float(df['rate'].iloc[-1]) * 0.005

        # Ventana de recálculo: cubre holgadamente el mayor lookback (lag_168 /
        # ma_90) para que los technicals de la última fila sean exactos, sin
        # recomputar sobre los 3 años completos en cada uno de los H pasos.
        TAIL = 320

        predictions = []
        for h in range(1, horizon + 1):
            pred_ts = last_ts + pd.Timedelta(hours=h)

            # La última fila del df YA trae technicals y calendario frescos para
            # su propio timestamp (recomputados al final de la iteración previa,
            # o por el pipeline.build en la primera).
            row      = df.iloc[-1]
            feat_vec = np.array([[float(row.get(f, 0.0) or 0.0) for f in features]], dtype=np.float32)
            rate_pred = float(model.predict(feat_vec)[0])

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

            # Añadir la fila predicha y RECALCULAR technicals + calendario de
            # forma causal sobre la cola, para que la próxima iteración lea
            # indicadores actualizados (no congelados).
            new_row_df = pd.DataFrame({'rate': [rate_pred]}, index=[pred_ts])
            df = pd.concat([df, new_row_df])
            # Arrastrar 'rate' + exógenas (macro/volume): _add_macro las ffill de
            # forma causal (la fila futura hereda el último valor conocido, no 0).
            carry = ['rate'] + [c for c in ('volume', 'international_rate',
                     'interest_rate', 'inflation_rate', 'oil_price') if c in df.columns]
            tail = df[carry].tail(TAIL).copy()
            tail = pipe._add_technical(tail)
            tail = pipe._add_calendar(tail, currency_pair)
            tail = pipe._add_macro(tail)
            # Volcar los features recomputados sobre las filas correspondientes.
            df.loc[tail.index, tail.columns] = tail

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

def build_supervised(df: pd.DataFrame, features: list):
    """Construye (X, y, data) para entrenamiento supervisado SIN data leakage.

    A3 — el target es rate[t+1], NO rate[t]. Los technicals del pipeline
    (ma_*/ema/macd/rsi/bb_pct/volatility/pct_change) usan ventanas rolling que
    TERMINAN en t (min_periods=1) → incluyen rate[t]. Si además y = rate[t] de la
    MISMA fila, el modelo aprende la identidad ma≈rate y el MAPE sale
    artificialmente bajo, sobre-ponderando a XGBoost en el ensemble. Desplazando
    el target a t+1, el modelo predice el FUTURO con información conocida en t
    (causal), consistente con la inferencia iterativa de `predict`.

    Devuelve (X, y, data) donde `data` es el DataFrame alineado (con 'target').
    Garantiza que ninguna columna de features es el target contemporáneo.
    """
    data = df[features + ['rate']].copy()
    data['target'] = data['rate'].shift(-1)          # y = rate[t+1]
    data = data.dropna(subset=features + ['target'])
    X = data[features].values.astype(np.float32)
    y = data['target'].values.astype(np.float32)
    return X, y, data


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
