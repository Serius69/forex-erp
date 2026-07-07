# Kapitalya ERP — Modelos de Machine Learning

Sistema de predicción de tasas de cambio que combina tres enfoques complementarios: modelos estadísticos de series de tiempo, redes neuronales y ensambles ponderados.

---

## Resumen del sistema ML

```
TrainingData (BD)
    │
    ▼
ForexPredictionService
    ├── Prophet Model  ──┐
    ├── LSTM Model     ──┼──► Ensemble (ponderado por MAPE)
    └── ARIMA (futuro)  ─┘
    │
    ▼
Prediction objects (BD)
    │
    ▼
API /predictions/predictions/current/
    │
    ▼
Frontend PredictionsChart + Mobile DashboardScreen
```

---

## Datos de entrenamiento

**Modelo:** `TrainingData`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `currency_pair` | str | Par de divisas (ej: `USD/BOB`) |
| `date` | datetime | Fecha/hora del dato |
| `rate` | Decimal | Tasa de cambio oficial |
| `volume` | Decimal | Volumen negociado (opcional) |
| `international_rate` | Decimal | Tasa internacional (ej: cotización global USD) |
| `interest_rate` | Decimal | Tasa de interés del BCB |
| `inflation_rate` | Decimal | IPC / inflación |
| `oil_price` | Decimal | Precio del petróleo (relevante para BOB) |
| `ma_7`, `ma_30` | Decimal | Medias móviles pre-calculadas |
| `volatility` | float | Volatilidad histórica |
| `source` | str | Fuente del dato (default: `BCB`) |

**Mínimo para entrenamiento:** 100 registros por par de divisas.

---

## Ingeniería de características

Calculadas automáticamente en `_engineer_features(df)` antes de entrenar:

```python
# Temporales
day_of_week, day_of_month, month, quarter

# Medias móviles
ma_7, ma_30, ma_90 = rolling(7), rolling(30), rolling(90)

# Volatilidad
volatility_7, volatility_30 = std(7), std(30)

# Cambios porcentuales
pct_change_1, pct_change_7, pct_change_30

# RSI (Relative Strength Index, 14 períodos)
delta = prices.diff()
gain  = delta.where(delta > 0, 0).rolling(14).mean()
loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
rsi   = 100 - (100 / (1 + gain/loss))

# Bandas de Bollinger (20 períodos, 2σ)
bb_middle = rolling_mean(20)
bb_upper  = bb_middle + 2 * rolling_std(20)
bb_lower  = bb_middle - 2 * rolling_std(20)
```

---

## Modelo 1: Prophet (Facebook/Meta)

**Uso:** Predicción estacional de tasas. Captura tendencias semanales y estacionalidad diaria.

**Configuración:**
```python
model = Prophet(
    daily_seasonality    = True,
    weekly_seasonality   = True,
    yearly_seasonality   = True,
    changepoint_prior_scale  = 0.05,   # Flexibilidad de tendencia
    seasonality_prior_scale  = 10.0,
    interval_width           = 0.95    # Intervalo de confianza 95%
)

# Regresores externos (si están disponibles en TrainingData)
model.add_regressor('international_rate')
model.add_regressor('oil_price')
```

**Formato de entrada:**
```python
prophet_df = pd.DataFrame({
    'ds': dates,    # datetime
    'y':  rates,    # float — tasa de cambio
})
```

**Archivo:** `media/ml_models/prophet_{currency_pair}.pkl` (joblib)

**Ventajas:**
- Maneja datos faltantes automáticamente
- Detecta cambios de tendencia (changepoints)
- Intervalos de confianza nativos

**Limitaciones:**
- Asume estacionalidad estable (puede fallar en shocks externos)
- Lento para reentrenar en datasets grandes

---

## Modelo 2: LSTM (Long Short-Term Memory)

**Uso:** Captura dependencias temporales complejas y no lineales en series de tiempo.

**Arquitectura:**
```python
model = Sequential([
    LSTM(100, return_sequences=True, input_shape=(60, 5)),  # 60 pasos, 5 features
    Dropout(0.2),
    LSTM(100, return_sequences=True),
    Dropout(0.2),
    LSTM(50, return_sequences=False),
    Dropout(0.2),
    Dense(25),
    Dense(1)   # Predicción de la próxima tasa
])

model.compile(
    optimizer = Adam(learning_rate=0.001),
    loss      = 'mean_squared_error',
    metrics   = ['mae']
)
```

**Features de entrada** (5 variables):
```python
features = ['rate', 'ma_7', 'ma_30', 'volatility_7', 'rsi']
```

**Entrenamiento:**
```python
# Secuencias de 60 pasos temporales → predice el siguiente
X.shape = (n_samples, 60, 5)
y.shape = (n_samples, 1)

# Train/Test split: 80/20
# Callbacks: EarlyStopping(patience=10), ReduceLROnPlateau(patience=5)
# Epochs: 50, Batch: 32
```

**Normalización:** MinMaxScaler guardado en `scaler_lstm_{pair}.pkl`

**Archivos:**
- `media/ml_models/lstm_{currency_pair}.h5` — Modelo Keras
- `media/ml_models/scaler_lstm_{currency_pair}.pkl` — Scaler

**Predicción iterativa:**
```python
# Para predecir 24 horas:
for i in range(24):
    pred = model.predict(current_sequence)  # shape: (1, 60, 5)
    predictions.append(pred)
    # Actualiza la secuencia desplazando 1 paso
    current_sequence = np.vstack([current_sequence[1:], new_row])
```

---

## Modelo 3: Ensemble (Prophet + LSTM)

**Uso:** Combina ambos modelos ponderados inversamente por su MAPE.

**Cálculo de pesos:**
```python
prophet_weight = 1 / (prophet_mape + 1)
lstm_weight    = 1 / (lstm_mape    + 1)

# Normalizar a suma = 1
total = prophet_weight + lstm_weight
prophet_weight /= total
lstm_weight    /= total

# Predicción combinada
ensemble_rate = prophet_rate * prophet_weight + lstm_rate * lstm_weight
```

Un modelo con menor MAPE recibe mayor peso automáticamente.

**Intervalos de confianza:**
```python
lower = min(prophet_lower, lstm_lower)
upper = max(prophet_upper, lstm_upper)
```

---

## Aplicación de márgenes comerciales

Al predecir, se aplican los márgenes de `RateConfiguration` según la hora:

```python
if 6 <= hour < 12:
    buy_margin, sell_margin = rate_config.buy_margin_morning, rate_config.sell_margin_morning
elif 12 <= hour < 18:
    buy_margin, sell_margin = rate_config.buy_margin_afternoon, rate_config.sell_margin_afternoon
else:
    buy_margin, sell_margin = rate_config.buy_margin_evening, rate_config.sell_margin_evening

predicted_buy_rate  = predicted_rate * (1 - buy_margin  / 100)
predicted_sell_rate = predicted_rate * (1 + sell_margin / 100)
```

---

## Métricas de evaluación

| Métrica | Descripción | Bueno |
|---------|-------------|-------|
| **MAE** | Error absoluto medio | < 0.05 BOB |
| **MSE** | Error cuadrático medio | Referencia |
| **RMSE** | Raíz del MSE | < 0.08 BOB |
| **MAPE** | Error porcentual absoluto medio | < 1% |

**Cálculo:**
```python
mae  = mean_absolute_error(actuals, predictions)
rmse = sqrt(mean_squared_error(actuals, predictions))
mape = mean(abs((actuals - predictions) / actuals)) * 100
```

**Evaluación por hold-out:** 20% de datos reservados para test (no participan en entrenamiento).

---

## Ciclo de vida de los modelos

### Entrenamiento (Celery Beat)
```python
# predictions/tasks.py
@app.task
def train_models():
    service = ForexPredictionService()
    for pair in ['USD/BOB', 'EUR/BOB', 'ARG/BOB']:
        service.train_ensemble_model(pair)
    # → Actualiza PredictionModel.last_trained + metrics
```

**Frecuencia:** Diaria (noche, horario de baja actividad)

### Predicción (Celery Beat)
```python
@app.task
def update_predictions():
    service = ForexPredictionService()
    for pair in active_pairs:
        service.predict_rates(pair, horizon=24)
    # → Crea Prediction objects para las próximas 24h
```

**Frecuencia:** Cada hora

### Evaluación posterior
```python
# Cuando llega el dato real
prediction.actual_rate = real_rate
prediction.calculate_error()  # Calcula y guarda error_percentage (MAPE)
```

---

## Gestión de modelos

### Registro en BD (`PredictionModel`)
```json
{
  "name": "Prophet USD/BOB",
  "model_type": "PROPHET",
  "currency_pair": "USD/BOB",
  "parameters": {
    "changepoint_prior_scale": 0.05,
    "seasonality_prior_scale": 10.0,
    "interval_width": 0.95
  },
  "metrics": {
    "mae": 0.0412,
    "rmse": 0.0689,
    "mape": 0.58
  },
  "is_active": true,
  "last_trained": "2026-04-07T03:00:00"
}
```

### Activar/desactivar modelo
```python
model = PredictionModel.objects.get(model_type='LSTM', currency_pair='USD/BOB')
model.is_active = False
model.save()
# → El sistema usará solo Prophet hasta que se reactive
```

---

## Requisitos de dependencias

```txt
prophet==1.1.5
tensorflow==2.13.x
scikit-learn==1.3.x
pandas==2.0.x
numpy==1.24.x
joblib==1.3.x
```

> **Nota de producción:** TensorFlow requiere ~2GB de RAM. En entornos con recursos limitados, considerar usar solo Prophet (más ligero) y deshabilitar el modelo LSTM vía `is_active=False`.
