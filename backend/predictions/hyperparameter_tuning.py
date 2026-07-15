"""
HyperparameterTuner — optimización bayesiana de hiperparámetros con Optuna.

Modelos optimizados:
  - XGBoost: n_estimators, max_depth, learning_rate, subsample, colsample_bytree
  - BiLSTM: units_1, units_2, dropout, sequence_length, batch_size
  - Prophet: changepoint_prior_scale, seasonality_prior_scale

Diseño:
  - Cada búsqueda usa n_trials=50 (configurable)
  - Usa TimeSeriesSplit para no introducir look-ahead bias
  - Los mejores hiperparámetros se guardan en PredictionModel.parameters
  - La tarea Celery de tuning corre semanalmente con baja prioridad
  - Optuna suprime warnings de trials fallidos (errores esperados en búsqueda)
"""
import numpy as np
import pandas as pd
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


class HyperparameterTuner:
    """Optimización bayesiana de hiperparámetros para XGBoost, BiLSTM y Prophet."""

    def __init__(self, models_path: str, n_trials: int = 50):
        self.models_path = models_path
        self.n_trials    = n_trials

    # ── XGBoost ───────────────────────────────────────────────────────────────

    def tune_xgboost(self, currency_pair: str, df: pd.DataFrame, market: str = 'web') -> dict:
        """Optimiza XGBoost con Optuna. Retorna los mejores parámetros."""
        try:
            import optuna
            import xgboost as xgb
        except ImportError as exc:
            raise ImportError(f"Dependencias faltantes: {exc}")

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        from predictions.xgboost_forecaster import XGBOOST_FEATURES
        from sklearn.metrics import mean_absolute_percentage_error
        from sklearn.model_selection import TimeSeriesSplit

        features = [f for f in XGBOOST_FEATURES if f in df.columns]
        data     = df[features + ['rate']].dropna()
        X        = data[features].values.astype(np.float32)
        y        = data['rate'].values.astype(np.float32)

        tscv = TimeSeriesSplit(n_splits=5)

        def objective(trial):
            params = {
                'n_estimators':     trial.suggest_int('n_estimators', 100, 1000),
                'max_depth':        trial.suggest_int('max_depth', 3, 10),
                'learning_rate':    trial.suggest_float('learning_rate', 0.005, 0.3, log=True),
                'subsample':        trial.suggest_float('subsample', 0.5, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
                'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
                'gamma':            trial.suggest_float('gamma', 0, 1.0),
                'reg_alpha':        trial.suggest_float('reg_alpha', 0, 2.0),
                'reg_lambda':       trial.suggest_float('reg_lambda', 0, 2.0),
                'tree_method': 'hist',
                'objective':   'reg:squarederror',
                'random_state': 42,
                'n_jobs': 1,
            }
            mapes = []
            for train_idx, val_idx in tscv.split(X):
                model = xgb.XGBRegressor(**params)
                model.fit(X[train_idx], y[train_idx], verbose=False)
                y_pred = model.predict(X[val_idx])
                mape   = float(np.mean(np.abs((y[val_idx] - y_pred) / np.where(y[val_idx] != 0, y[val_idx], 1))) * 100)
                mapes.append(mape)
            return float(np.mean(mapes))

        study = optuna.create_study(direction='minimize', study_name=f'xgboost_{currency_pair}')
        study.optimize(objective, n_trials=self.n_trials, show_progress_bar=False, n_jobs=1)

        best_params = study.best_params
        best_mape   = round(study.best_value, 4)

        logger.info("tune_xgboost pair=%s best_mape=%.4f%% params=%s", currency_pair, best_mape, best_params)
        self._save_best_params(currency_pair, 'XGBOOST', best_params, best_mape, market=market)
        return {'best_params': best_params, 'best_mape': best_mape, 'n_trials': self.n_trials}

    # ── BiLSTM ────────────────────────────────────────────────────────────────

    def tune_bilstm(self, currency_pair: str, df: pd.DataFrame, market: str = 'web') -> dict:
        """Optimiza arquitectura BiLSTM con Optuna."""
        try:
            import optuna
            import tensorflow as tf
        except ImportError as exc:
            raise ImportError(f"Dependencias faltantes: {exc}")

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        from predictions.lstm_forecaster import LSTM_FEATURES, _make_sequences
        from sklearn.preprocessing import RobustScaler

        features = [f for f in LSTM_FEATURES if f in df.columns]
        data     = df[features].dropna().values
        scaler   = RobustScaler().fit(data)
        scaled   = scaler.transform(data)

        def objective(trial):
            seq_len  = trial.suggest_int('sequence_length', 24, 120, step=24)
            units_1  = trial.suggest_categorical('units_1', [64, 128, 256])
            units_2  = trial.suggest_categorical('units_2', [32, 64, 128])
            dropout  = trial.suggest_float('dropout', 0.1, 0.4)
            batch_sz = trial.suggest_categorical('batch_size', [32, 64, 128])

            X, y = _make_sequences(scaled, seq_len)
            if len(X) < 50:
                return 999.0

            split    = int(len(X) * 0.8)
            X_tr, X_val = X[:split], X[split:]
            y_tr, y_val = y[:split], y[split:]

            from tensorflow.keras.models import Model
            from tensorflow.keras.layers import (
                Input, Bidirectional, LSTM, Dense, Dropout,
                GlobalAveragePooling1D, LayerNormalization,
            )

            inp = Input(shape=(seq_len, len(features)))
            x   = Bidirectional(LSTM(units_1, return_sequences=True))(inp)
            x   = LayerNormalization()(x)
            x   = Dropout(dropout)(x)
            x   = Bidirectional(LSTM(units_2, return_sequences=False))(x)
            x   = Dropout(dropout)(x)
            x   = Dense(32, activation='relu')(x)
            out = Dense(1)(x)

            m = Model(inp, out)
            m.compile(optimizer='adam', loss='huber')
            m.fit(X_tr, y_tr, epochs=15, batch_size=batch_sz,
                  validation_data=(X_val, y_val), verbose=0,
                  callbacks=[tf.keras.callbacks.EarlyStopping(patience=5)])

            y_pred = m.predict(X_val, verbose=0).flatten()

            # Desnormalizar para calcular MAPE real
            from predictions.lstm_forecaster import _denorm
            y_pred_d = _denorm(y_pred, scaler, len(features))
            y_val_d  = _denorm(y_val, scaler, len(features))
            mape     = float(np.mean(np.abs((y_val_d - y_pred_d) / np.where(y_val_d != 0, y_val_d, 1))) * 100)

            tf.keras.backend.clear_session()
            return mape

        study = optuna.create_study(direction='minimize', study_name=f'bilstm_{currency_pair}')
        study.optimize(objective, n_trials=min(self.n_trials, 20), show_progress_bar=False)

        best_params = study.best_params
        best_mape   = round(study.best_value, 4)

        logger.info("tune_bilstm pair=%s best_mape=%.4f%% params=%s", currency_pair, best_mape, best_params)
        self._save_best_params(currency_pair, 'BILSTM', best_params, best_mape, market=market)
        return {'best_params': best_params, 'best_mape': best_mape, 'n_trials': min(self.n_trials, 20)}

    # ── Prophet ───────────────────────────────────────────────────────────────

    def tune_prophet(self, currency_pair: str, df: pd.DataFrame, market: str = 'web') -> dict:
        """Optimiza hiperparámetros de Prophet con búsqueda en grid (más rápido que Optuna para Prophet)."""
        try:
            from prophet import Prophet
        except ImportError as exc:
            raise ImportError(f"Prophet no disponible: {exc}")

        from sklearn.metrics import mean_absolute_percentage_error

        daily = df['rate'].resample('D').last().dropna()
        prophet_df = pd.DataFrame({'ds': daily.index.tz_localize(None), 'y': daily.values})

        split    = int(len(prophet_df) * 0.85)
        train_df = prophet_df.iloc[:split]
        test_df  = prophet_df.iloc[split:]

        # Grid de búsqueda (3×3×3 = 27 combinaciones)
        param_grid = [
            {'changepoint_prior_scale': cps, 'seasonality_prior_scale': sps, 'seasonality_mode': sm}
            for cps in [0.01, 0.05, 0.30]
            for sps in [1.0,  10.0, 20.0]
            for sm  in ['additive', 'multiplicative']
        ]

        best_mape, best_params = float('inf'), None

        for params in param_grid:
            try:
                m = Prophet(
                    changepoint_prior_scale=params['changepoint_prior_scale'],
                    seasonality_prior_scale=params['seasonality_prior_scale'],
                    seasonality_mode=params['seasonality_mode'],
                    daily_seasonality=True, weekly_seasonality=True,
                    yearly_seasonality=True, interval_width=0.95,
                )
                m.fit(train_df)
                future   = m.make_future_dataframe(periods=len(test_df), freq='D')
                forecast = m.predict(future)
                y_pred   = forecast['yhat'][-len(test_df):].values
                y_true   = test_df['y'].values
                mape     = float(np.mean(np.abs((y_true - y_pred) / np.where(y_true != 0, y_true, 1))) * 100)
                if mape < best_mape:
                    best_mape, best_params = mape, params
            except Exception:
                continue

        best_mape = round(best_mape, 4)
        logger.info("tune_prophet pair=%s best_mape=%.4f%% params=%s", currency_pair, best_mape, best_params)
        self._save_best_params(currency_pair, 'PROPHET', best_params or {}, best_mape, market=market)
        return {'best_params': best_params, 'best_mape': best_mape, 'trials': len(param_grid)}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _save_best_params(self, currency_pair: str, model_type: str, params: dict, best_mape: float, market: str = 'web'):
        """Actualiza PredictionModel.parameters con los mejores hiperparámetros encontrados."""
        from predictions.models import PredictionModel
        try:
            pm = PredictionModel.objects.get(model_type=model_type, currency_pair=currency_pair, market=market)
            pm.parameters['best_hyperparams'] = params
            pm.parameters['tuning_mape']      = best_mape
            pm.parameters['tuned_at']         = timezone.now().isoformat()
            pm.save(update_fields=['parameters'])
        except (PredictionModel.DoesNotExist, PredictionModel.MultipleObjectsReturned):
            pass   # El modelo se creará en el próximo entrenamiento


# ── Tarea Celery: tuning semanal ──────────────────────────────────────────────

def run_weekly_tuning(currency_pairs: list, models_path: str, n_trials: int = 30) -> dict:
    """
    Punto de entrada para la tarea Celery semanal de tuning.
    Ejecuta XGBoost y Prophet (no BiLSTM en producción — muy lento con Optuna)
    para las TRES series de mercado (antes solo se tuneaba 'web'; competencia y
    empresa quedaban sin optimizar). Series sin datos degradan limpio.
    """
    from predictions.data_pipeline import ForexDataPipeline
    from predictions.market_keys import VALID_MARKETS

    tuner    = HyperparameterTuner(models_path=models_path, n_trials=n_trials)
    pipeline = ForexDataPipeline()
    results  = {}

    for pair in currency_pairs:
        results[pair] = {}
        for market in VALID_MARKETS:
            try:
                df = pipeline.build(pair, market=market)
                xgb_result  = tuner.tune_xgboost(pair, df, market=market)
                prop_result = tuner.tune_prophet(pair, df, market=market)
                results[pair][market] = {'xgboost': xgb_result, 'prophet': prop_result}
                logger.info("tuning.complete pair=%s market=%s", pair, market)
            except Exception as exc:
                logger.warning("tuning.skipped pair=%s market=%s error=%s",
                               pair, market, exc)
                results[pair][market] = {'error': str(exc)}

    return results
