# Kapitalya ERP — Backend

Backend Django REST Framework para casa de cambio boliviana. Timezone: `America/La_Paz`.

---

## Apps Django

### `users` — Autenticación y Usuarios

**Modelos:**

```python
Branch          # Sucursal física
User            # AbstractUser + rol + branch + PIN + 2FA
UserActivity    # Log de acciones por usuario
```

**Roles:**

| Rol | Permisos |
|-----|---------|
| `ADMIN` | Acceso total, todas las sucursales |
| `SUPERVISOR` | Aprueba transacciones grandes, su sucursal |
| `CASHIER` | Crea transacciones, ve su sucursal |

**Endpoints:**
- `POST /api/auth/login/` — Obtener JWT (`ForexTokenView`)
- `POST /api/auth/refresh/` — Renovar token
- `POST /api/auth/logout/` — Blacklist refresh token
- `GET/POST /api/users/` — CRUD usuarios (ADMIN)

**Funcionalidades especiales:**
- `User.set_pin()` / `check_pin()` — PIN hasheado para autorización supervisor
- `User.generate_two_factor_secret()` — Genera TOTP secret
- `User.verify_two_factor_token()` — Verifica token 6 dígitos

---

### `rates` — Tasas de Cambio

**Modelos:**

```python
Currency            # Divisa (USD, EUR, ARG, etc.)
ExchangeRate        # Tasa oficial + compra + venta + validez temporal
RateConfiguration   # Márgenes comerciales por par y por franja horaria
```

**Validaciones en `ExchangeRate.clean()`:**
- `buy_rate` ≤ `sell_rate`
- Desviación máxima del 10% respecto a tasa oficial

**Márgenes por franja horaria (`RateConfiguration`):**
```
Mañana  (06:00–11:59): buy_margin_morning,  sell_margin_morning
Tarde   (12:00–17:59): buy_margin_afternoon, sell_margin_afternoon
Noche   (18:00–05:59): buy_margin_evening,   sell_margin_evening
```

**WebSocket** (`rates/consumers.py`):
- Canal `ws://host/ws/rates/`
- Emite actualizaciones de tasas en tiempo real a todos los clientes conectados

**Endpoints:**
- `GET /api/rates/` — Tasas actuales
- `POST /api/rates/` — Crear nueva tasa (ADMIN/SUPERVISOR)
- `GET /api/rates/configurations/` — Configuraciones de margen

---

### `transactions` — Transacciones

**Modelos:**

```python
Customer            # Cliente con KYC básico (documento, PEP flag)
Transaction         # Operación de compra/venta de divisa
TransactionDocument # Documentos adjuntos (PDF, imagen)
```

**Tipos de transacción:**
- `BUY` — La casa compra divisa al cliente (cliente trae divisas, recibe BOB)
- `SELL` — La casa vende divisa al cliente (cliente trae BOB, recibe divisas)

**Numeración automática:** `{branch.code}{YYYYMMDD}{####}` — ej. `SC202404070001`

**Servicio `TransactionService`:**

```python
# Uso
service = TransactionService()
transaction, receipt_pdf = service.create_transaction(data, user)
```

Pasos internos (todos en `db.atomic()`):
1. `_get_or_create_customer()` — KYC cliente
2. `_validate_supervisor_pin()` — Si monto > USD 5,000 equiv.
3. `_validate_inventory()` — Verifica saldo disponible
4. `Transaction.save()` — Genera número único
5. `_update_inventory()` — `select_for_update()` para thread-safety
6. `_generate_receipt()` — PDF con QR code (ReportLab)

**Reversas:**
```python
# Solo en las últimas 24h
transaction.reverse(user=supervisor, reason="Error en monto")
# Crea transacción opuesta + marca original como REVERSED
```

**Endpoints:**
- `GET/POST /api/transactions/` — Listar/crear
- `GET /api/transactions/{id}/` — Detalle
- `POST /api/transactions/{id}/reverse/` — Revertir
- `GET/POST /api/customers/` — CRUD clientes

---

### `inventory` — Inventario de Divisas

**Modelos:**

```python
CurrencyInventory   # Stock por (divisa, sucursal). Unique_together.
InventoryMovement   # Auditoría de cada movimiento (IN/OUT/ADJUSTMENT/TRANSFER)
InventoryTransfer   # Transferencia entre sucursales
```

**Costo Promedio Ponderado (WAC):**
```python
# core/finance.py
def calculate_wac(existing_qty, existing_wac, new_qty, new_rate):
    total_qty = existing_qty + new_qty
    if total_qty == 0:
        return new_rate
    return (existing_qty * existing_wac + new_qty * new_rate) / total_qty
```

**Métodos principales:**
```python
inventory.add_currency(amount, rate, user)    # Compra → aumenta stock + recalcula WAC
inventory.remove_currency(amount, user)       # Venta → reduce stock (físico primero)
inventory.transfer_to_branch(target, amount)  # Transferencia inter-sucursal
inventory.adjust_inventory(phys, dig, user)   # Conteo físico + alerta si diff > 1%
```

**Alertas automáticas:**
- `LOW_STOCK` — Cuando `total_balance ≤ reorder_point`
- `SIGNIFICANT_ADJUSTMENT` — Diferencia > 1% en conteo físico

**Endpoints:**
- `GET /api/inventory/` — Stock actual por divisa/sucursal
- `GET /api/inventory/movements/` — Historial de movimientos
- `POST /api/inventory/transfers/` — Crear transferencia
- `POST /api/inventory/adjust/` — Ajuste por conteo

---

### `predictions` — Predicciones ML

**Modelos:**

```python
PredictionModel   # Registro del modelo (tipo, par, métricas, archivo)
Prediction        # Predicción individual (rate + intervalos confianza)
TrainingData      # Datos históricos + indicadores técnicos
```

**Servicio `ForexPredictionService`:**

```python
service = ForexPredictionService()

# Entrenamiento
model, metrics = service.train_prophet_model('USD/BOB')
model, metrics = service.train_lstm_model('USD/BOB', sequence_length=60)
ensemble = service.train_ensemble_model('USD/BOB')

# Predicción
predictions = service.predict_rates('USD/BOB', horizon=24)
# → Lista de Prediction objects para las próximas 24 horas
```

**Indicadores técnicos calculados en `_engineer_features()`:**
- MA 7, 30, 90 días
- Volatilidad rolling 7 y 30 días
- RSI (14 períodos)
- Bandas de Bollinger (20 períodos, 2 desviaciones)
- Cambios porcentuales 1/7/30 días

**Métricas de evaluación:** MAE, MSE, RMSE, MAPE

**Tarea Celery:** Reentrenamiento y predicciones periódicas

---

### `reports` — Reportes y Cumplimiento ASFI

**Modelos:**

```python
CashTransactionReport      # RTE — Registro de transacciones en efectivo ≥ USD 1,000
SuspiciousActivityReport   # ROUE — Operaciones inusuales o sospechosas
PEPRegistry                # PEP — Personas Expuestas Políticamente
DailyOperationLog          # Libro Diario — ASFI Art. 14
GeneratedReport            # Índice de todos los reportes generados
```

**Servicios:**
- `reports/services/asfi_service.py` — Generación de reportes ASFI (RTE, ROUE, PEP, Libro Diario)
- `reports/services/management_service.py` — P&G, rentabilidad, flujo de caja, ranking clientes

**Endpoints:**
- `GET /api/reports/` — Historial de reportes
- `POST /api/reports/generate/` — Generar reporte (PDF/Excel)
- `GET /api/reports/rte/` — Listado RTE
- `GET /api/reports/roue/` — Listado ROUE
- `GET /api/reports/pep/` — Registro PEP

---

### `capital` — Capital y Gastos

**Modelos:**

```python
Gasto            # Gasto operativo categorizado (alquiler, sueldos, etc.)
CapitalSnapshot  # Foto del capital total en un momento dado
```

**Servicio `CapitalService`:**
```python
# Capital en tiempo real
resultado = CapitalService.calcular_capital(branch=None)
# → {efectivo_bob, qr_bob, divisas_bob, tarjetas_bob, pasivos_bob, total_bob}

# Persistir snapshot
snap = CapitalService.guardar_snapshot(branch, user, tipo='CIERRE',
                                       efectivo_bob=50000, qr_bob=10000)
```

**Servicio `GananciaService`:**
```python
# Ganancia por divisa en un período
ganancias = GananciaService.ganancia_por_divisa(date_from, date_to, branch)

# Resumen financiero completo
resumen = GananciaService.resumen_financiero(date_from, date_to, branch)
# → {ganancias_divisas, ganancias_tarjetas, gastos, ganancia_bruta, ganancia_neta}
```

---

### `tarjetas` — Tarjetas Prepago

**Modelos:**

```python
TipoTarjeta       # Catálogo: Tigo 5 BOB, Viva 10 BOB, etc.
LoteCompra        # Lote de compra con precio costo. FIFO por fecha.
VentaTarjeta      # Registro de venta. Calcula costo FIFO al momento.
DetalleVentaLote  # Auditoría FIFO: qué unidades de qué lote se consumieron.
```

**Costeo FIFO:**
```python
# Al vender N tarjetas de tipo X:
# 1. Obtener lotes activos ordenados por fecha (más antiguo primero)
# 2. Consumir unidades hasta completar la cantidad
# 3. Registrar DetalleVentaLote por cada lote tocado
# 4. Calcular costo_fifo_bob y ganancia_bob = total_bob - costo_fifo_bob
```

---

## Core / Shared

### `core/finance.py`
```python
quantize_amount(val)              # Redondea a 2dp (Decimal)
quantize_rate(val)                # Redondea a 4dp (Decimal)
calculate_wac(qty, wac, new_qty, new_rate)  # Costo Promedio Ponderado
```

### `core/middleware.py`
- `IdempotencyMiddleware` — Cachea respuestas de POST por `X-Idempotency-Key`
- `SecurityHeadersMiddleware` — Headers de seguridad HTTP

### `core/exceptions.py`
- `custom_exception_handler` — Normaliza errores DRF a `{error, detail, code}`

### `core/celery.py`
```python
# Tareas programadas (django_celery_beat)
# - Actualización de tasas BCB
# - Generación de predicciones
# - Backup de base de datos
# - Cierre automático del libro diario
```

---

## Tareas Celery

| Tarea | Frecuencia | Descripción |
|-------|-----------|-------------|
| `rates.tasks.fetch_bcb_rates` | Cada hora | Obtiene tasas oficiales del BCB |
| `predictions.tasks.run_predictions` | Cada hora | Genera predicciones 24h |
| `predictions.tasks.train_models` | Diario (noche) | Reentrenamiento de modelos ML |
| `reports.tasks.generate_daily_log` | Diario (23:59) | Cierre del libro diario ASFI |
| `core.tasks.backup_database` | Diario | Backup PostgreSQL |

---

## Configuración por entorno

| Variable | Dev | Prod |
|----------|-----|------|
| `DEBUG` | `True` | `False` |
| `DB_HOST` | `127.0.0.1` | `postgres` (Docker) |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | `redis://redis:6379/0` |
| `CHANNEL_LAYERS` | InMemory | Redis |

Ver [DEPLOYMENT.md](DEPLOYMENT.md) para configuración completa.
