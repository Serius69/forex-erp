"""
LSTMForecaster — LSTM bidireccional con mecanismo de atención (TensorFlow/Keras).

Mejoras sobre el LSTM legacy de ml_service.py:
  - Bidireccional: captura dependencias hacia adelante y hacia atrás
  - Atención: el modelo pondera qué pasos temporales son más relevantes
  - RobustScaler: menos sensible a outliers que MinMaxScaler
  - Huber loss: robusto a outliers en el target
  - 25 features vs 5 del modelo anterior
  - Secuencia de 72h (3 días) vs 60 pasos
  - Guarda en formato .keras (más estable que .h5)
"""
import numpy as np
import pandas as pd
import joblib
import os
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

LSTM_FEATURES = [
    'rate',
    'ma_7', 'ma_14', 'ma_30',
    'ema_12', 'ema_26',
    'macd', 'macd_hist',
    'rsi',
    'bb_width', 'bb_pct',
    'atr_14',
    'volatility_7', 'volatility_14',
    'pct_change_1', 'pct_change_7',
    'lag_1', 'lag_2', 'lag_3', 'lag_24',
    'hour', 'day_of_week', 'is_weekend',
    'international_rate', 'oil_price',
]

DEFAULT_SEQUENCE_LENGTH = 72   # 3 días de datos horarios


class LSTMForecaster:
    """BiLSTM con atención — mejor captura de patrones de mediano plazo."""

    def __init__(self, models_path: str):
        self.models_path = models_path

    # ── Entrenamiento ──────────────────────────────────────────────────────────

    def train(self, currency_pair: str, df: pd.DataFrame, params: dict = None) -> dict:
        """
        Entrena el modelo BiLSTM+Attention.
        Parámetros opcionales vía `params`: sequence_length, units_1, units_2, dropout.
        """
        import tensorflow as tf
        from tensorflow.keras.models import Model
        from tensorflow.keras.layers import (
            Input, Bidirectional, LSTM, Dense, Dropout,
            GlobalAveragePooling1D, LayerNormalization, MultiHeadAttention,
        )

        p = {
            'sequence_length': DEFAULT_SEQUENCE_LENGTH,
            'units_1':         128,
            'units_2':         64,
            'dropout':         0.20,
            'epochs':          100,
            'batch_size':      64,
            **(params or {}),
        }
        seq_len = p['sequence_length']

        features = [f for f in LSTM_FEATURES if f in df.columns]
        data     = df[features].dropna().values

        scaler = RobustScaler()
        scaled = scaler.fit_transform(data)

        X, y = _make_sequences(scaled, seq_len)

        split    = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        # ── Arquitectura: BiLSTM → LayerNorm → Multi-Head Attention → Dense ──
        inp = Input(shape=(seq_len, len(features)), name='input')

        x = Bidirectional(LSTM(p['units_1'], return_sequences=True), name='bilstm_1')(inp)
        x = LayerNormalization()(x)
        x = Dropout(p['dropout'])(x)

        x = Bidirectional(LSTM(p['units_2'], return_sequences=True), name='bilstm_2')(x)
        x = LayerNormalization()(x)
        x = Dropout(p['dropout'])(x)

        # Multi-head attention (4 cabezas, dimensión de clave = units_2*2)
        attn_dim = p['units_2'] * 2
        x = MultiHeadAttention(num_heads=4, key_dim=attn_dim // 4, name='attention')(x, x)
        x = GlobalAveragePooling1D()(x)

        x   = Dense(64, activation='relu')(x)
        x   = Dropout(p['dropout'] / 2)(x)
        x   = Dense(32, activation='relu')(x)
        out = Dense(1, name='output')(x)

        model = Model(inputs=inp, outputs=out)
        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
            loss='huber',
            metrics=['mae'],
        )

        callbacks = [
            tf.keras.callbacks.EarlyStopping(patience=15, restore_best_weights=True),
            tf.keras.callbacks.ReduceLROnPlateau(patience=7, factor=0.5, min_lr=1e-6),
        ]
        model.fit(
            X_train, y_train,
            epochs=p['epochs'],
            batch_size=p['batch_size'],
            validation_data=(X_test, y_test),
            callbacks=callbacks,
            verbose=0,
        )

        # ── Métricas ──
        y_pred_scaled = model.predict(X_test, verbose=0).flatten()
        y_pred  = _denorm(y_pred_scaled, scaler, len(features))
        y_true  = _denorm(y_test, scaler, len(features))
        metrics = _compute_metrics(y_true, y_pred)

        # ── Guardar ──
        pair_safe   = currency_pair.replace('/', '_')
        model_path  = os.path.join(self.models_path, f'bilstm_{pair_safe}.keras')
        scaler_path = os.path.join(self.models_path, f'scaler_bilstm_{pair_safe}.pkl')

        model.save(model_path)
        joblib.dump({'scaler': scaler, 'features': features, 'seq_len': seq_len}, scaler_path)

        self._register(currency_pair, model_path, metrics, {**p, 'features': features})
        logger.info("BiLSTM entrenado pair=%s mape=%.4f%%", currency_pair, metrics['mape'])
        return metrics

    # ── Predicción ─────────────────────────────────────────────────────────────

    def predict(self, currency_pair: str, df_recent: pd.DataFrame, horizon: int) -> list:
        """Predicción iterativa hora a hora con actualización de secuencia."""
        import tensorflow as tf

        pair_safe   = currency_pair.replace('/', '_')
        model_path  = os.path.join(self.models_path, f'bilstm_{pair_safe}.keras')
        scaler_path = os.path.join(self.models_path, f'scaler_bilstm_{pair_safe}.pkl')

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"BiLSTM no entrenado para {currency_pair}")

        model    = tf.keras.models.load_model(model_path)
        artifact = joblib.load(scaler_path)
        scaler   = artifact['scaler']
        features = artifact['features']
        seq_len  = artifact['seq_len']

        data    = df_recent[features].dropna().values
        scaled  = scaler.transform(data)
        cur_seq = scaled[-seq_len:].copy()

        # ATR para CI
        atr_idx  = features.index('atr_14') if 'atr_14' in features else None
        atr_base = float(scaler.inverse_transform(cur_seq[-1:])[0][atr_idx]) if atr_idx else float(df_recent['rate'].iloc[-1]) * 0.005

        now = timezone.now()
        predictions = []

        for h in range(1, horizon + 1):
            pred_scaled = float(model.predict(cur_seq.reshape(1, seq_len, len(features)), verbose=0)[0, 0])
            rate_pred   = _denorm(np.array([pred_scaled]), scaler, len(features))[0]

            sigma = atr_base * np.sqrt(h)
            predictions.append({
                'prediction_date': (now + pd.Timedelta(hours=h)).to_pydatetime(),
                'rate':            rate_pred,
                'lower':           rate_pred - 1.96 * sigma,
                'upper':           rate_pred + 1.96 * sigma,
                'confidence':      max(0.50, 0.90 - h * 0.005),
                'external_factors': {'model': 'BILSTM'},
            })

            # Hacer avanzar la secuencia con el valor predicho
            new_row    = cur_seq[-1].copy()
            new_row[0] = pred_scaled   # columna 0 = 'rate' en el scaler
            cur_seq    = np.vstack([cur_seq[1:], new_row])

        return predictions

    # ── Registro en BD ─────────────────────────────────────────────────────────

    def _register(self, currency_pair, model_path, metrics, params):
        from predictions.models import PredictionModel

        PredictionModel.objects.update_or_create(
            model_type='BILSTM',
            currency_pair=currency_pair,
            defaults={
                'name':         f'BiLSTM {currency_pair}',
                'parameters':   params,
                'metrics':      metrics,
                'model_file':   model_path,
                'last_trained': timezone.now(),
            },
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_sequences(data: np.ndarray, seq_len: int):
    X, y = [], []
    for i in range(seq_len, len(data)):
        X.append(data[i - seq_len:i])
        y.append(data[i, 0])   # columna 0 = rate
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


def _denorm(values: np.ndarray, scaler: RobustScaler, n_features: int) -> np.ndarray:
    """Desnormaliza solo la columna 0 (rate)."""
    full = np.zeros((len(values), n_features), dtype=np.float32)
    full[:, 0] = values.flatten()
    return scaler.inverse_transform(full)[:, 0]


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
