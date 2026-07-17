import pandas as pd
import numpy as np
from prophet import Prophet
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.optimizers import Adam
import joblib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
import os
import logging

logger = logging.getLogger(__name__)

class ForexPredictionService:
    """Servicio principal para predicciones de divisas"""
    
    def __init__(self):
        self.models_path = os.path.join(settings.MEDIA_ROOT, 'ml_models')
        os.makedirs(self.models_path, exist_ok=True)
        
        self.models = {}
        self.scalers = {}
    
    def prepare_training_data(self, currency_pair, start_date=None, market='web'):
        """Prepara datos para entrenamiento (serie `market`: web/competencia/empresa)"""
        from .models import TrainingData

        # Obtener datos históricos
        query = TrainingData.objects.filter(currency_pair=currency_pair, market=market)
        
        if start_date:
            query = query.filter(date__gte=start_date)
        
        # Solo date + rate: el resto de columnas de TrainingData (volatility, ma_*,
        # campos macro) las deja NULL `update_training_data`, y como no todas se
        # recalculan en _engineer_features, el dropna posterior vaciaba el DataFrame.
        data = list(query.order_by('date').values('date', 'rate'))

        if len(data) < 100:
            raise ValueError("Datos insuficientes para entrenamiento")
        
        # Convertir a DataFrame
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)

        # `rate` viene como Decimal (dtype object) desde el ORM: los rolling/pct_change
        # sobre object producen NaN y el dropna posterior vacía el DataFrame (Prophet
        # fallaba con "less than 2 non-NaN rows"). Forzar float.
        df['rate'] = pd.to_numeric(df['rate'], errors='coerce').astype('float64')

        # Calcular características adicionales
        df = self._engineer_features(df)
        
        # Eliminar valores nulos
        df.dropna(inplace=True)
        
        return df
    
    def _engineer_features(self, df):
        """Ingeniería de características"""
        # Características temporales
        df['day_of_week'] = df.index.dayofweek
        df['day_of_month'] = df.index.day
        df['month'] = df.index.month
        df['quarter'] = df.index.quarter
        
        # Medias móviles
        df['ma_7'] = df['rate'].rolling(window=7).mean()
        df['ma_30'] = df['rate'].rolling(window=30).mean()
        df['ma_90'] = df['rate'].rolling(window=90).mean()
        
        # Volatilidad
        df['volatility_7'] = df['rate'].rolling(window=7).std()
        df['volatility_30'] = df['rate'].rolling(window=30).std()
        
        # Cambios porcentuales
        df['pct_change_1'] = df['rate'].pct_change(1)
        df['pct_change_7'] = df['rate'].pct_change(7)
        df['pct_change_30'] = df['rate'].pct_change(30)
        
        # RSI (Relative Strength Index)
        df['rsi'] = self._calculate_rsi(df['rate'])
        
        # Bandas de Bollinger
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = self._calculate_bollinger_bands(df['rate'])
        
        return df
    
    def _calculate_rsi(self, prices, period=14):
        """Calcula el RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_bollinger_bands(self, prices, window=20, num_std=2):
        """Calcula las Bandas de Bollinger"""
        rolling_mean = prices.rolling(window).mean()
        rolling_std = prices.rolling(window).std()
        
        upper_band = rolling_mean + (rolling_std * num_std)
        lower_band = rolling_mean - (rolling_std * num_std)
        
        return upper_band, rolling_mean, lower_band
    
    def train_prophet_model(self, currency_pair, market='web'):
        """Entrena modelo Prophet para la serie `market`"""
        logger.info(f"Entrenando Prophet para {currency_pair} [{market}]")

        # Preparar datos
        df = self.prepare_training_data(currency_pair, market=market)
        
        # Formato Prophet — `ds` debe ser tz-naive (TrainingData.date es tz-aware)
        ds = pd.to_datetime(df.index)
        if getattr(ds, 'tz', None) is not None:
            ds = ds.tz_localize(None)
        prophet_df = pd.DataFrame({
            'ds': ds,
            'y': df['rate']
        })
        
        # Agregar regresores si están disponibles
        if 'international_rate' in df.columns:
            prophet_df['international_rate'] = df['international_rate'].values
        if 'oil_price' in df.columns:
            prophet_df['oil_price'] = df['oil_price'].values
        
        # Crear y entrenar modelo
        model = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05,
            seasonality_prior_scale=10.0,
            interval_width=0.95
        )
        
        # Agregar regresores
        if 'international_rate' in prophet_df.columns:
            model.add_regressor('international_rate')
        if 'oil_price' in prophet_df.columns:
            model.add_regressor('oil_price')
        
        # Entrenar
        model.fit(prophet_df)
        
        # Guardar modelo (sanitizar '/' del par + sufijo de market)
        from .market_keys import fname_suffix
        pair_safe = currency_pair.replace('/', '_') + fname_suffix(market)
        model_path = os.path.join(self.models_path, f'prophet_{pair_safe}.pkl')
        joblib.dump(model, model_path)

        # Evaluar modelo
        metrics = self._evaluate_prophet(model, prophet_df)

        # Registrar en base de datos
        from .models import PredictionModel

        model_record, created = PredictionModel.objects.update_or_create(
            model_type='PROPHET',
            currency_pair=currency_pair,
            market=market,
            defaults={
                'name': f'Prophet {currency_pair} [{market}]',
                'parameters': {
                    'changepoint_prior_scale': 0.05,
                    'seasonality_prior_scale': 10.0,
                    'interval_width': 0.95
                },
                'metrics': metrics,
                'model_file': model_path,
                'last_trained': timezone.now()
            }
        )
        
        return model, metrics
    
    def _evaluate_prophet(self, model, df):
        """Evalúa modelo Prophet"""
        # Hacer predicciones en datos de prueba
        train_size = int(len(df) * 0.8)
        train_df = df[:train_size]
        test_df = df[train_size:]
        
        # Re-entrenar con datos de entrenamiento
        model_eval = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True
        )
        model_eval.fit(train_df)
        
        # Predecir
        future = model_eval.make_future_dataframe(periods=len(test_df))
        forecast = model_eval.predict(future)
        
        # Calcular métricas
        predictions = forecast['yhat'][-len(test_df):].values
        actuals = test_df['y'].values
        
        mae = mean_absolute_error(actuals, predictions)
        mse = mean_squared_error(actuals, predictions)
        rmse = np.sqrt(mse)
        mape = np.mean(np.abs((actuals - predictions) / actuals)) * 100
        
        return {
            'mae': float(mae),
            'mse': float(mse),
            'rmse': float(rmse),
            'mape': float(mape)
        }
    
    def train_lstm_model(self, currency_pair, sequence_length=60, market='web'):
        """Entrena modelo LSTM para la serie `market`"""
        logger.info(f"Entrenando LSTM para {currency_pair} [{market}]")
        from .market_keys import fname_suffix
        msuffix = fname_suffix(market)

        # Preparar datos
        df = self.prepare_training_data(currency_pair, market=market)
        
        # Características para LSTM
        features = ['rate', 'ma_7', 'ma_30', 'volatility_7', 'rsi']
        feature_data = df[features].values
        
        # Normalizar datos
        from sklearn.preprocessing import MinMaxScaler
        scaler = MinMaxScaler()
        scaled_data = scaler.fit_transform(feature_data)
        
        # Guardar scaler (sanitizar '/' del par + sufijo market)
        pair_safe = currency_pair.replace('/', '_') + msuffix
        scaler_path = os.path.join(self.models_path, f'scaler_lstm_{pair_safe}.pkl')
        joblib.dump(scaler, scaler_path)
        self.scalers[f'lstm_{currency_pair}'] = scaler
        
        # Crear secuencias
        X, y = self._create_sequences(scaled_data, sequence_length)
        
        # Dividir en entrenamiento y prueba
        train_size = int(len(X) * 0.8)
        X_train, X_test = X[:train_size], X[train_size:]
        y_train, y_test = y[:train_size], y[train_size:]
        
        # Construir modelo LSTM
        model = Sequential([
            LSTM(100, return_sequences=True, input_shape=(sequence_length, len(features))),
            Dropout(0.2),
            LSTM(100, return_sequences=True),
            Dropout(0.2),
            LSTM(50, return_sequences=False),
            Dropout(0.2),
            Dense(25),
            Dense(1)
        ])
        
        # Compilar modelo
        model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss='mean_squared_error',
            metrics=['mae']
        )
        
        # Entrenar
        history = model.fit(
            X_train, y_train,
            epochs=50,
            batch_size=32,
            validation_data=(X_test, y_test),
            verbose=1,
            callbacks=[
                tf.keras.callbacks.EarlyStopping(patience=10),
                tf.keras.callbacks.ReduceLROnPlateau(patience=5)
            ]
        )
        
        # Guardar modelo (sanitizar '/' del par + sufijo market)
        pair_safe = currency_pair.replace('/', '_') + msuffix
        model_path = os.path.join(self.models_path, f'lstm_{pair_safe}.h5')
        model.save(model_path)

        # Evaluar
        metrics = self._evaluate_lstm(model, X_test, y_test, scaler)

        # Registrar en base de datos
        from .models import PredictionModel

        model_record, created = PredictionModel.objects.update_or_create(
            model_type='LSTM',
            currency_pair=currency_pair,
            market=market,
            defaults={
                'name': f'LSTM {currency_pair} [{market}]',
                'parameters': {
                    'sequence_length': sequence_length,
                    'features': features,
                    'layers': [100, 100, 50, 25, 1],
                    'epochs': 50,
                    'batch_size': 32
                },
                'metrics': metrics,
                'model_file': model_path,
                'last_trained': timezone.now()
            }
        )
        
        return model, metrics
   
    def _create_sequences(self, data, sequence_length):
       """Crea secuencias para LSTM"""
       X, y = [], []
       
       for i in range(sequence_length, len(data)):
           X.append(data[i-sequence_length:i])
           y.append(data[i, 0])  # Predecir la tasa (primera columna)
       
       return np.array(X), np.array(y)
   
    def _evaluate_lstm(self, model, X_test, y_test, scaler):
       """Evalúa modelo LSTM"""
       predictions = model.predict(X_test)
       
       # Desnormalizar predicciones
       predictions_full = np.zeros((len(predictions), scaler.n_features_in_))
       predictions_full[:, 0] = predictions.flatten()
       predictions_denorm = scaler.inverse_transform(predictions_full)[:, 0]
       
       # Desnormalizar valores reales
       y_test_full = np.zeros((len(y_test), scaler.n_features_in_))
       y_test_full[:, 0] = y_test
       y_test_denorm = scaler.inverse_transform(y_test_full)[:, 0]
       
       # Calcular métricas
       mae = mean_absolute_error(y_test_denorm, predictions_denorm)
       mse = mean_squared_error(y_test_denorm, predictions_denorm)
       rmse = np.sqrt(mse)
       mape = np.mean(np.abs((y_test_denorm - predictions_denorm) / y_test_denorm)) * 100
       
       return {
           'mae': float(mae),
           'mse': float(mse),
           'rmse': float(rmse),
           'mape': float(mape)
       }
   
    def train_ensemble_model(self, currency_pair, market='web'):
       """Entrena modelo ensemble combinando Prophet y LSTM (serie `market`)"""
       logger.info(f"Entrenando modelo Ensemble para {currency_pair} [{market}]")

       # Entrenar modelos individuales si no existen
       prophet_model, prophet_metrics = self.train_prophet_model(currency_pair, market=market)
       lstm_model, lstm_metrics = self.train_lstm_model(currency_pair, market=market)
       
       # Calcular pesos basados en métricas
       prophet_weight = 1 / (prophet_metrics['mape'] + 1)
       lstm_weight = 1 / (lstm_metrics['mape'] + 1)
       
       # Normalizar pesos
       total_weight = prophet_weight + lstm_weight
       prophet_weight /= total_weight
       lstm_weight /= total_weight
       
       # Registrar modelo ensemble
       from .models import PredictionModel
       
       model_record, created = PredictionModel.objects.update_or_create(
           model_type='ENSEMBLE',
           currency_pair=currency_pair,
           market=market,
           defaults={
               'name': f'Ensemble {currency_pair} [{market}]',
               'parameters': {
                   'prophet_weight': float(prophet_weight),
                   'lstm_weight': float(lstm_weight),
                   'models': ['PROPHET', 'LSTM']
               },
               'metrics': {
                   'prophet_metrics': prophet_metrics,
                   'lstm_metrics': lstm_metrics,
                   'weights': {
                       'prophet': float(prophet_weight),
                       'lstm': float(lstm_weight)
                   }
               },
               'last_trained': timezone.now()
           }
       )
       
       return model_record
   
    def predict_rates(self, currency_pair, horizon=24, market='web'):
       """Genera predicciones para las próximas 'horizon' horas (serie `market`)"""
       from .models import PredictionModel, Prediction
       from rates.models import RateConfiguration
       
       predictions = []
       
       # Obtener configuración de márgenes
       rate_config = RateConfiguration.objects.filter(
           currency_from__code=currency_pair.split('/')[0],
           currency_to__code=currency_pair.split('/')[1],
           is_active=True
       ).first()
       
       # Obtener modelos activos de la serie solicitada
       models = PredictionModel.objects.filter(
           currency_pair=currency_pair,
           market=market,
           is_active=True
       )

       for model in models:
           if model.model_type == 'PROPHET':
               model_predictions = self._predict_prophet(model, horizon)
           elif model.model_type == 'LSTM':
               model_predictions = self._predict_lstm(model, horizon)
           elif model.model_type == 'ENSEMBLE':
               model_predictions = self._predict_ensemble(model, horizon)
           else:
               continue
           
           # Aplicar márgenes comerciales
           for pred in model_predictions:
               # Calcular tasas de compra y venta
               if rate_config:
                   hour = pred['prediction_date'].hour
                   if 6 <= hour < 12:
                       buy_margin = rate_config.buy_margin_morning
                       sell_margin = rate_config.sell_margin_morning
                   elif 12 <= hour < 18:
                       buy_margin = rate_config.buy_margin_afternoon
                       sell_margin = rate_config.sell_margin_afternoon
                   else:
                       buy_margin = rate_config.buy_margin_evening
                       sell_margin = rate_config.sell_margin_evening
               else:
                   buy_margin = Decimal('0.3')
                   sell_margin = Decimal('0.3')
               
               predicted_rate = Decimal(str(pred['rate']))
               buy_rate = predicted_rate * (Decimal('1') - buy_margin / Decimal('100'))
               sell_rate = predicted_rate * (Decimal('1') + sell_margin / Decimal('100'))
               
               # Crear predicción
               prediction = Prediction.objects.create(
                   model=model,
                   currency_pair=currency_pair,
                   prediction_date=pred['prediction_date'],
                   predicted_rate=predicted_rate,
                   predicted_buy_rate=buy_rate,
                   predicted_sell_rate=sell_rate,
                   confidence_lower=Decimal(str(pred.get('lower', predicted_rate * 0.98))),
                   confidence_upper=Decimal(str(pred.get('upper', predicted_rate * 1.02))),
                   confidence_score=pred.get('confidence', 0.8),
                   external_factors=pred.get('external_factors', {})
               )
               
               predictions.append(prediction)
       
       return predictions
   
    def _predict_naive_fallback(self, horizon: int,
                                currency_pair: str = 'USD/BOB',
                                market: str = 'web') -> list[dict]:
       """
       Predicción de último recurso basada en la última tasa paralela conocida.
       Retorna el mismo formato que los modelos ML reales.
       Confidence interval: ±0.5% de la tasa actual.

       A4 — se parametriza por `currency_pair`/`market`: antes consultaba SIEMPRE
       USD/BOB (`currency_from__code='USD'`), así que para EUR/BRL/ARS/… inyectaba
       la tasa del dólar como si fuera del par pedido. Los market_type se derivan
       de la serie con el mismo mapa que usa el resto del pipeline.
       """
       from rates.models import ExchangeRate
       from decimal import Decimal
       from .tasks import MARKET_SOURCE_MAP

       try:
           currency_from, currency_to = currency_pair.split('/')
       except ValueError:
           currency_from, currency_to = 'USD', 'BOB'
       market_types = MARKET_SOURCE_MAP.get(
           market, MARKET_SOURCE_MAP.get('web', ('paralelo_digital',)))

       rate = None
       try:
           latest = (
               ExchangeRate.objects
               .filter(
                   currency_from__code=currency_from,
                   currency_to__code=currency_to,
                   market_type__in=market_types,
               )
               .order_by('-valid_from')
               .first()
           )
           if latest:
               rate = (latest.buy_rate + latest.sell_rate) / 2
       except Exception as exc:
           logger.warning('naive_fallback could not get latest rate: %s', exc)

       if rate is None:
           # Sin NINGUNA tasa real en BD: mejor no predecir que inventar un
           # número (antes devolvía 9.80 hardcodeado como si fuera dato).
           logger.error('naive_fallback sin tasa real en BD — no se emite predicción')
           return []

       margin = rate * Decimal('0.005')
       predictions = []
       now = timezone.now()

       for i in range(horizon):
           prediction_dt = now + timedelta(hours=i + 1)
           predictions.append({
               'prediction_date': prediction_dt,
               'rate':            float(rate),
               'lower':           float(rate - margin),
               'upper':           float(rate + margin),
               'confidence':      0.60,
               'external_factors': {'model': 'NAIVE_FALLBACK', 'is_fallback': True},
           })

       return predictions

    def _predict_prophet(self, model_record, horizon):
       """Predicciones con Prophet"""
       # Defensive: verificar que el archivo del modelo existe
       if not model_record.model_file or not model_record.model_file.name:
           logger.warning(
               'Prophet model_file faltante para %s — usando fallback naive',
               model_record.currency_pair,
           )
           return self._predict_naive_fallback(horizon, model_record.currency_pair, getattr(model_record, 'market', 'web') or 'web')

       try:
           model_path = model_record.model_file.path
           if not os.path.exists(model_path):
               logger.warning(
                   'Prophet model file no encontrado en %s — usando fallback naive',
                   model_path,
               )
               return self._predict_naive_fallback(horizon, model_record.currency_pair, getattr(model_record, 'market', 'web') or 'web')

           # Artefacto cacheado por (ruta, mtime): se re-lee solo tras reentrenar.
           from predictions.artifact_cache import load_cached
           model = load_cached(model_path, joblib.load)

           # Crear dataframe futuro
           future = model.make_future_dataframe(periods=horizon, freq='H')

           # A4 — Regresores: make_future_dataframe SOLO crea la columna 'ds'; el
           # código previo hacía future['international_rate'].ffill() sobre una
           # columna INEXISTENTE → KeyError → Prophet SIEMPRE caía al fallback
           # naive. Además 'oil_price' nunca se rellenaba. Se construye cada
           # regresor que el modelo espera con el último valor conocido de la
           # serie (relleno causal/constante — no podemos pronosticar el exógeno).
           regressors = list(getattr(model, 'extra_regressors', {}) or {})
           if regressors:
               from .models import TrainingData
               mkt = getattr(model_record, 'market', 'web') or 'web'
               latest = (
                   TrainingData.objects
                   .filter(currency_pair=model_record.currency_pair, market=mkt)
                   .order_by('-date')
                   .values('international_rate', 'oil_price')
                   .first()
               ) or {}
               last_vals = {
                   'international_rate': latest.get('international_rate'),
                   'oil_price':          latest.get('oil_price'),
               }
               for reg in regressors:
                   val = last_vals.get(reg)
                   future[reg] = float(val) if val is not None else 0.0

           # Predecir
           forecast = model.predict(future)

           # Extraer predicciones
           predictions = []
           for i in range(len(forecast) - horizon, len(forecast)):
               predictions.append({
                   'prediction_date': forecast.iloc[i]['ds'],
                   'rate':            float(forecast.iloc[i]['yhat']),
                   'lower':           float(forecast.iloc[i]['yhat_lower']),
                   'upper':           float(forecast.iloc[i]['yhat_upper']),
                   'confidence':      0.95,
                   'external_factors': {},
               })

           return predictions

       except Exception as exc:
           logger.error(
               'Prophet load error para %s: %s — usando fallback naive',
               model_record.currency_pair, exc,
           )
           return self._predict_naive_fallback(horizon, model_record.currency_pair, getattr(model_record, 'market', 'web') or 'web')
   
    def _predict_lstm(self, model_record, horizon):
       """Predicciones con LSTM"""
       # Defensive: verificar que el archivo del modelo existe
       if not model_record.model_file or not model_record.model_file.name:
           logger.warning(
               'LSTM model_file faltante para %s — usando fallback naive',
               model_record.currency_pair,
           )
           return self._predict_naive_fallback(horizon, model_record.currency_pair, getattr(model_record, 'market', 'web') or 'web')

       model_path = model_record.model_file.path
       if not os.path.exists(model_path):
           logger.warning(
               'LSTM model file no encontrado en %s — usando fallback naive',
               model_path,
           )
           return self._predict_naive_fallback(horizon, model_record.currency_pair, getattr(model_record, 'market', 'web') or 'web')

       try:
           model = tf.keras.models.load_model(model_path)
       except Exception as exc:
           logger.error('LSTM load error para %s: %s — usando fallback naive',
                        model_record.currency_pair, exc)
           return self._predict_naive_fallback(horizon, model_record.currency_pair, getattr(model_record, 'market', 'web') or 'web')

       scaler_path = model_path.replace('lstm_', 'scaler_lstm_').replace('.h5', '.pkl')
       if not os.path.exists(scaler_path):
           logger.warning('LSTM scaler no encontrado en %s — usando fallback naive', scaler_path)
           return self._predict_naive_fallback(horizon, model_record.currency_pair, getattr(model_record, 'market', 'web') or 'web')

       try:
           scaler = joblib.load(scaler_path)
       except Exception as exc:
           logger.error('LSTM scaler load error: %s — usando fallback naive', exc)
           return self._predict_naive_fallback(horizon, model_record.currency_pair, getattr(model_record, 'market', 'web') or 'web')

       try:
           # Obtener datos recientes
           from .models import TrainingData

           sequence_length = model_record.parameters['sequence_length']
           recent_data = TrainingData.objects.filter(
               currency_pair=model_record.currency_pair,
               market='web',
           ).order_by('-date')[:sequence_length]

           df = pd.DataFrame(list(recent_data.values()))
           df['date'] = pd.to_datetime(df['date'])
           df.set_index('date', inplace=True)
           df = df.sort_index()
           df = self._engineer_features(df)

           features = model_record.parameters['features']
           feature_data = df[features].values
           scaled_data = scaler.transform(feature_data)

           predictions = []
           current_sequence = scaled_data[-sequence_length:]

           for i in range(horizon):
               pred = model.predict(current_sequence.reshape(1, sequence_length, -1))
               pred_full = np.zeros((1, scaler.n_features_in_))
               pred_full[0, 0] = pred[0, 0]
               pred_denorm = scaler.inverse_transform(pred_full)[0, 0]
               prediction_date = df.index[-1] + timedelta(hours=i + 1)
               predictions.append({
                   'prediction_date': prediction_date,
                   'rate':            float(pred_denorm),
                   'lower':           float(pred_denorm * 0.98),
                   'upper':           float(pred_denorm * 1.02),
                   'confidence':      0.85,
                   'external_factors': {},
               })
               new_row = current_sequence[-1].copy()
               new_row[0] = pred[0, 0]
               current_sequence = np.vstack([current_sequence[1:], new_row])

           return predictions

       except Exception as exc:
           logger.error('LSTM predict error para %s: %s — usando fallback naive',
                        model_record.currency_pair, exc)
           return self._predict_naive_fallback(horizon, model_record.currency_pair, getattr(model_record, 'market', 'web') or 'web')
   
    def _predict_ensemble(self, model_record, horizon):
       """Predicciones con modelo ensemble"""
       from .models import PredictionModel
       # Obtener predicciones de modelos individuales (misma serie de mercado)
       prophet_model = PredictionModel.objects.get(
           model_type='PROPHET',
           currency_pair=model_record.currency_pair,
           market=model_record.market,
       )
       lstm_model = PredictionModel.objects.get(
           model_type='LSTM',
           currency_pair=model_record.currency_pair,
           market=model_record.market,
       )
       
       prophet_predictions = self._predict_prophet(prophet_model, horizon)
       lstm_predictions = self._predict_lstm(lstm_model, horizon)
       
       # Obtener pesos
       prophet_weight = model_record.parameters['prophet_weight']
       lstm_weight = model_record.parameters['lstm_weight']
       
       # Combinar predicciones
       ensemble_predictions = []
       
       for i in range(horizon):
           prophet_pred = prophet_predictions[i]
           lstm_pred = lstm_predictions[i]
           
           # Promediar ponderado
           ensemble_rate = (
               prophet_pred['rate'] * prophet_weight +
               lstm_pred['rate'] * lstm_weight
           )
           
           ensemble_predictions.append({
               'prediction_date': prophet_pred['prediction_date'],
               'rate': float(ensemble_rate),
               'lower': float(min(prophet_pred['lower'], lstm_pred['lower'])),
               'upper': float(max(prophet_pred['upper'], lstm_pred['upper'])),
               'confidence': (prophet_pred['confidence'] + lstm_pred['confidence']) / 2,
               'external_factors': {
                   'prophet_rate': prophet_pred['rate'],
                   'lstm_rate': lstm_pred['rate']
               }
           })
       
       return ensemble_predictions