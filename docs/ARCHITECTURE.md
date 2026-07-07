# Kapitalya ERP — Architecture

> Sistema ERP para casas de cambio (Bolivia). Gestiona transacciones de divisas, inventario, tarjetas prepago, capital, cumplimiento ASFI y predicciones ML.

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Backend API | Django 4.x + Django REST Framework |
| Auth | JWT (SimpleJWT) + 2FA (TOTP/pyotp) |
| Real-time | Django Channels + WebSocket |
| Base de datos | PostgreSQL (django.contrib.postgres) |
| Cache | Redis |
| Cola de tareas | Celery + Redis broker |
| ML | Prophet + TensorFlow/Keras LSTM + scikit-learn |
| Frontend web | React + Redux Toolkit + Vite |
| Frontend móvil | React Native |
| PDF/Reportes | ReportLab + openpyxl |
| Contenedores | Docker + Docker Compose |

---

## Diagrama de componentes

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENTES                                │
│   Browser (React)              App móvil (React Native)         │
└────────────┬───────────────────────────┬────────────────────────┘
             │ HTTPS/REST                │ HTTPS/REST
             │ WebSocket (ws://)         │
             ▼                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Django Backend                              │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  users   │  │  rates   │  │  trans-  │  │inventory │       │
│  │  Branch  │  │  Exchange│  │  actions │  │Currency  │       │
│  │  User    │  │  Rate    │  │  Txn     │  │Inventory │       │
│  │  2FA/PIN │  │  Config  │  │  Customer│  │Movement  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │predictions│  │ reports  │  │ capital  │  │tarjetas  │       │
│  │ Prophet  │  │ RTE/ROUE │  │ Gasto    │  │TipoTarj. │       │
│  │ LSTM     │  │ PEP      │  │ Capital  │  │Lote/Venta│       │
│  │ Ensemble │  │ DailyLog │  │ Snapshot │  │FIFO cost │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Core / Shared                         │  │
│  │  core.finance (quantize, WAC)   core.exceptions          │  │
│  │  core.middleware (idempotency)  core.celery (beat)        │  │
│  │  core.routing (ASGI/WS)         core.backup               │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────┬──────────────────────────┬───────────────────┬──────────┘
       │                          │                   │
       ▼                          ▼                   ▼
┌────────────┐          ┌──────────────┐    ┌──────────────────┐
│ PostgreSQL │          │    Redis     │    │   Celery Worker  │
│            │          │  (cache +    │    │  + Celery Beat   │
│  Datos     │          │   broker)    │    │  (tareas periód.)│
└────────────┘          └──────────────┘    └──────────────────┘
                                                      │
                                                      ▼
                                            ┌──────────────────┐
                                            │  ML Models       │
                                            │  /media/ml_models│
                                            │  prophet_*.pkl   │
                                            │  lstm_*.h5       │
                                            └──────────────────┘
```

---

## Flujo de datos principal

### Flujo: Transacción de cambio de divisa

```
Cajero (UI)
    │
    ├─► POST /api/transactions/
    │       │
    │       ▼
    │   TransactionViewSet.create()
    │       │
    │       ▼
    │   TransactionService.create_transaction()
    │       ├─ Validar cliente (get_or_create)
    │       ├─ Verificar PIN supervisor (si monto > límite)
    │       ├─ Validar inventario (CurrencyInventory)
    │       ├─ db.atomic() ──► Transaction.save()
    │       │                  CurrencyInventory.add/remove_currency()
    │       │                  InventoryMovement.create()
    │       └─ Generar PDF comprobante (ReportLab)
    │
    └─► WebSocket broadcast → Dashboard en tiempo real
```

### Flujo: Predicción ML

```
Celery Beat (cada hora)
    │
    ├─► tasks.update_predictions()
    │       │
    │       ▼
    │   ForexPredictionService.predict_rates(currency_pair, horizon=24)
    │       ├─ Cargar modelo Prophet (.pkl) o LSTM (.h5)
    │       ├─ Aplicar márgenes por hora del día (RateConfiguration)
    │       └─ Guardar Prediction objects en BD
    │
    └─► Frontend polling /api/predictions/ → PredictionsChart
```

---

## Dominios de negocio

| Dominio | App Django | Responsabilidad |
|---------|-----------|----------------|
| Autenticación | `users` | JWT, 2FA, PIN supervisor, sucursales |
| Tasas de cambio | `rates` | Tipos de cambio, configuración de márgenes, WebSocket live |
| Transacciones | `transactions` | Compra/venta divisas, clientes, comprobantes PDF |
| Inventario | `inventory` | Stock por sucursal, WAC, transferencias, alertas |
| Predicciones | `predictions` | Prophet + LSTM + Ensemble, métricas, datos históricos |
| Reportes | `reports` | RTE (ASFI), ROUE, PEP, Libro Diario, P&G |
| Capital | `capital` | Gastos operativos, snapshots de capital, P&G consolidado |
| Tarjetas | `tarjetas` | Inventario prepago (FIFO), ventas, ganancia por tarjeta |

---

## Relaciones entre apps

```
rates.Currency ◄──── transactions.Transaction ────► users.Branch
      │                       │                           │
      ▼                       ▼                           ▼
inventory.CurrencyInventory  reports.CashTransactionReport  capital.Gasto
      │
      ▼
inventory.InventoryMovement

tarjetas.TipoTarjeta ──► tarjetas.LoteCompra (FIFO)
                    ──► tarjetas.VentaTarjeta ──► tarjetas.DetalleVentaLote

capital.CapitalService ──► inventory (divisas) + tarjetas (valor) + capital.Gasto
```

---

## Seguridad y cumplimiento

- **JWT** con rotación de refresh tokens y blacklist
- **2FA** TOTP (Google Authenticator compatible)
- **PIN supervisor** para transacciones > 5,000 USD equiv.
- **RTE** automático para operaciones ≥ 1,000 USD equiv. (ASFI Bolivia)
- **ROUE** para operaciones sospechosas
- **PEP** registro y control de Personas Expuestas Políticamente
- **Idempotency middleware** para evitar transacciones duplicadas
- **Rate limiting** en endpoints críticos
- **CORS** configurado por entorno
