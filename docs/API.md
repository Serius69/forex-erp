# Kapitalya ERP — API Reference

Base URL: `http://localhost:8000/api`

Todos los endpoints (excepto auth) requieren header:
```
Authorization: Bearer <access_token>
```

Paginación por defecto: 25 registros. Parámetros: `?page=2&page_size=50`

---

## Autenticación

### POST `/auth/login/`
Obtener tokens JWT.

**Request:**
```json
{
  "username": "cajero01",
  "password": "contraseña"
}
```

**Response 200:**
```json
{
  "access": "eyJhbGc...",
  "refresh": "eyJhbGc...",
  "user": {
    "id": 1,
    "username": "cajero01",
    "full_name": "Juan Pérez",
    "role": "CASHIER",
    "branch": { "id": 1, "name": "Sucursal Central", "code": "SC" }
  }
}
```

### POST `/auth/refresh/`
```json
{ "refresh": "eyJhbGc..." }
// Response: { "access": "nuevo_token" }
```

### POST `/auth/logout/`
```json
{ "refresh": "eyJhbGc..." }
// Response 205: token invalidado
```

---

## Transacciones

### GET `/transactions/`
Lista paginada. Filtros disponibles:

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `date_from` | `YYYY-MM-DD` | Desde fecha |
| `date_to` | `YYYY-MM-DD` | Hasta fecha |
| `customer_id` | int | Filtrar por cliente |
| `status` | `COMPLETED\|PENDING\|CANCELLED\|REVERSED` | Estado |
| `transaction_type` | `BUY\|SELL` | Tipo |

**Response 200:**
```json
{
  "count": 150,
  "next": "http://localhost:8000/api/transactions/?page=2",
  "previous": null,
  "results": [
    {
      "id": 42,
      "transaction_number": "SC202404070001",
      "transaction_type": "BUY",
      "status": "COMPLETED",
      "customer": {
        "id": 5,
        "full_name": "María López",
        "document_number": "1234567",
        "document_type": "CI"
      },
      "currency_from": { "code": "USD", "symbol": "$" },
      "currency_to":   { "code": "BOB", "symbol": "Bs." },
      "amount_from": "500.0000",
      "amount_to": "3450.00",
      "exchange_rate": "6.9000",
      "payment_method": "CASH",
      "cashier": { "id": 2, "username": "cajero01" },
      "branch": { "id": 1, "name": "Sucursal Central" },
      "created_at": "2026-04-07T10:30:00-04:00"
    }
  ]
}
```

### POST `/transactions/`
Crear nueva transacción.

**Request:**
```json
{
  "transaction_type": "BUY",
  "customer": {
    "document_type": "CI",
    "document_number": "1234567",
    "full_name": "María López",
    "phone": "70000000"
  },
  "currency_from": 2,
  "currency_to": 1,
  "amount_from": "500.00",
  "amount_to": "3450.00",
  "exchange_rate": "6.9000",
  "payment_method": "CASH",
  "payment_reference": "",
  "notes": ""
}
```

**Headers opcionales:**
- `Idempotency-Key: uuid` — Previene transacciones duplicadas
- `X-Supervisor-PIN: 1234` — PIN para montos > USD 5,000

**Response 201:** Objeto `Transaction` completo.

**Errores comunes:**
- `400 Saldo insuficiente` — Inventario insuficiente para SELL
- `400 Requiere supervisor` — Monto supera límite sin PIN
- `400 PIN inválido` — PIN de supervisor incorrecto

### GET `/transactions/{id}/`
Detalle de transacción.

### POST `/transactions/{id}/reverse/`
Revertir transacción (solo últimas 24h). Requiere permiso `can_reverse_transaction`.

```json
{ "reason": "Error en el monto ingresado" }
```

**Response 200:**
```json
{ "success": true, "reversal": { ...transaction_object } }
```

### GET `/transactions/{id}/receipt/`
Descarga comprobante PDF.

### GET `/transactions/daily-summary/`
Resumen del día.

```
?date=2026-04-07
```

**Response:**
```json
{
  "date": "2026-04-07",
  "total_transactions": 45,
  "by_type": { "buy": 28, "sell": 17 },
  "by_currency": {
    "USD": {
      "buy":  { "count": 20, "volume": "15000.00" },
      "sell": { "count": 12, "volume": "8500.00" }
    }
  },
  "total_volume_bob": "163800.00",
  "by_payment_method": {
    "CASH": { "count": 35, "volume": 145000.0 },
    "QR":   { "count": 10, "volume": 18800.0 }
  }
}
```

---

## Clientes

### GET `/customers/`
Lista clientes. Filtros: `?search=nombre_o_documento&frequent_only=true`

### POST `/customers/`
```json
{
  "document_type": "CI",
  "document_number": "9876543",
  "full_name": "Carlos Mamani",
  "phone": "71234567",
  "email": "carlos@example.com",
  "nationality": "Boliviana",
  "is_pep": false
}
```

### GET `/customers/search/?document=1234567`
Búsqueda por número de documento.

### GET `/customers/{id}/transactions/`
Historial de transacciones del cliente (últimas 50).

### POST `/customers/{id}/mark-frequent/`
Marcar como cliente frecuente.

---

## Tasas de Cambio

### GET `/rates/exchange-rates/`
Lista tasas históricas.

### GET `/rates/exchange-rates/current/`
Tasas actuales vigentes.

**Response:**
```json
[
  {
    "id": 10,
    "currency_from": { "code": "USD", "name": "Dólar Americano", "symbol": "$" },
    "currency_to":   { "code": "BOB", "name": "Boliviano", "symbol": "Bs." },
    "official_rate": "6.9600",
    "buy_rate": "6.9000",
    "sell_rate": "7.0000",
    "spread": "0.1000",
    "spread_percentage": "1.44",
    "source": "BCB",
    "valid_from": "2026-04-07T08:00:00-04:00"
  }
]
```

### POST `/rates/exchange-rates/`
Crear nueva tasa (ADMIN/SUPERVISOR).

```json
{
  "currency_from": 2,
  "currency_to": 1,
  "official_rate": "6.9600",
  "buy_rate": "6.9000",
  "sell_rate": "7.0100",
  "source": "BCB",
  "valid_from": "2026-04-07T08:00:00"
}
```

**Validaciones:** `buy_rate ≤ sell_rate`, desviación máxima 10% de tasa oficial.

---

## Inventario

### GET `/inventory/`
Stock por divisa y sucursal.

**Response:**
```json
[
  {
    "id": 1,
    "currency": { "code": "USD", "name": "Dólar" },
    "branch": { "name": "Sucursal Central" },
    "physical_balance": "25000.0000",
    "digital_balance": "5000.0000",
    "total_balance": "30000.0000",
    "minimum_stock": "1000.00",
    "maximum_stock": "50000.00",
    "weighted_average_cost": "6.9100",
    "needs_replenishment": false,
    "is_overstocked": false,
    "stock_level_percentage": "60.00"
  }
]
```

### GET `/inventory/movements/`
Historial de movimientos. Filtros: `?currency=USD&date_from=2026-04-01`

### POST `/inventory/transfers/`
Transferencia entre sucursales.

```json
{
  "currency": 2,
  "target_branch": 2,
  "amount": "5000.00",
  "notes": "Reposición sucursal norte"
}
```

### POST `/inventory/adjust/`
Ajuste por conteo físico (ADMIN/SUPERVISOR).

```json
{
  "inventory_id": 1,
  "physical_count": "24800.00",
  "digital_count": "5000.00",
  "reason": "Conteo mensual"
}
```

---

## Predicciones ML

### GET `/predictions/predictions/`
Lista predicciones activas.

### GET `/predictions/predictions/current/?currency_pair=USD/BOB`
Predicciones actuales para las próximas 24h.

**Response:**
```json
{
  "currency_pair": "USD/BOB",
  "predictions": {
    "PROPHET": [
      {
        "prediction_date": "2026-04-07T11:00:00",
        "predicted_rate": "6.9612",
        "predicted_buy_rate": "6.9402",
        "predicted_sell_rate": "7.0100",
        "confidence_lower": "6.8900",
        "confidence_upper": "7.0300",
        "confidence_score": 0.95
      }
    ],
    "LSTM": [...]
  }
}
```

### POST `/predictions/train/?currency_pair=USD/BOB&model_type=PROPHET`
Disparar reentrenamiento (ADMIN).

---

## Capital

### GET `/capital/actual/`
Capital total actual en tiempo real.

**Response:**
```json
{
  "efectivo_bob": "50000.00",
  "qr_bob": "10000.00",
  "divisas_bob": "207000.00",
  "tarjetas_bob": "3500.00",
  "pasivos_bob": "0.00",
  "total_bob": "270500.00",
  "detalle_divisas": {
    "USD": { "stock": "30000.00", "tc_venta": "7.00", "valor_bob": "210000.00" },
    "EUR": { "stock": "0.00", "tc_venta": "7.60", "valor_bob": "0.00" }
  },
  "detalle_tarjetas": {
    "Tigo 5 BOB": { "stock": 200, "precio_venta_prom": "5.50", "valor_bob": "1100.00" }
  },
  "advertencias": [],
  "calculado_en": "2026-04-07T10:45:00-04:00"
}
```

### GET `/capital/ganancias/`
Ganancia por divisa en un período.

```
?date_from=2026-04-01&date_to=2026-04-07
```

**Response:**
```json
[
  {
    "divisa": "USD",
    "ops_compra": 45,
    "ops_venta": 32,
    "unidades_compradas": "25000.00",
    "unidades_vendidas": "18000.00",
    "costo_bob": "172500.00",
    "ingreso_bob": "126720.00",
    "ganancia_bob": "1620.00",
    "tc_compra_prom": "6.90",
    "tc_venta_prom": "7.04",
    "spread_prom": "0.14",
    "margen_pct": "0.94"
  }
]
```

### GET `/capital/resumen/`
Resumen financiero completo del período.

```
?date_from=2026-04-01&date_to=2026-04-07
```

### GET `/capital/gastos/`
Lista gastos operativos.

### POST `/capital/gastos/`
```json
{
  "fecha": "2026-04-07",
  "categoria": "ALQUILER",
  "descripcion": "Alquiler sucursal central abril",
  "monto_bob": "3500.00",
  "medio_pago": "TRANSFER",
  "proveedor": "Inmobiliaria XYZ",
  "nro_factura": "F-001234"
}
```

### GET `/capital/snapshots/`
Historial de snapshots de capital.

### POST `/capital/snapshots/`
Crear snapshot manual del capital.

```json
{
  "tipo": "CIERRE",
  "efectivo_bob": "50000.00",
  "qr_bob": "10000.00",
  "pasivos_bob": "0.00",
  "notas": "Cierre del día lunes"
}
```

---

## Tarjetas Prepago

### GET `/tarjetas/tipos/`
Tipos de tarjetas activos.

### GET `/tarjetas/tipos/inventario/`
Inventario con stock y costo promedio.

**Response:**
```json
[
  {
    "id": 1,
    "operadora": "TIGO",
    "nombre": "Tigo 5 BOB",
    "denominacion": "5.00",
    "stock_actual": 200,
    "costo_promedio": "4.20",
    "valor_inventario_bob": "840.00"
  }
]
```

### POST `/tarjetas/tipos/{id}/vender/`
Registrar venta de tarjetas (FIFO automático).

```json
{
  "cantidad": 10,
  "precio_venta": "5.50",
  "medio_pago": "CASH",
  "cliente_nombre": "Pedro Flores",
  "cliente_tel": "71234567"
}
```

**Response:**
```json
{
  "venta_id": 15,
  "numero_venta": "VT202404070001",
  "cantidad": 10,
  "total_bob": "55.00",
  "costo_fifo_bob": "42.00",
  "ganancia_bob": "13.00"
}
```

### GET `/tarjetas/lotes/`
Lotes de compra activos.

### POST `/tarjetas/lotes/`
Registrar nuevo lote de compra.

```json
{
  "tipo_tarjeta": 1,
  "proveedor": "Distribuidora Tigo",
  "cantidad_total": 500,
  "precio_costo": "4.20",
  "numero_factura": "F-5678",
  "fecha_compra": "2026-04-07"
}
```

---

## Reportes ASFI

### GET `/reports/rte/`
Listado RTE (transacciones en efectivo ≥ USD 1,000). Filtros: `?status=PENDING&date_from=...`

### GET `/reports/roue/`
Listado ROUE (operaciones sospechosas).

### POST `/reports/generate/`
Generar reporte (PDF o Excel).

```json
{
  "report_type": "PNL_MONTHLY",
  "format": "EXCEL",
  "date_from": "2026-04-01",
  "date_to": "2026-04-30"
}
```

**Tipos disponibles:** `RTE_MONTHLY`, `ROUE_REPORT`, `PEP_LIST`, `DAILY_LOG`, `PNL_DAILY`, `PNL_MONTHLY`, `PROFITABILITY`, `CASHFLOW`, `COMPARATIVE`, `CLIENT_RANKING`

---

## Dashboard

### GET `/dashboard/stats/`
KPIs generales del sistema.

**Response:**
```json
{
  "today_transactions": 45,
  "today_volume_bob": "163800.00",
  "today_profit_bob": "2340.00",
  "active_currencies": 4,
  "low_stock_alerts": 1,
  "pending_rte": 2
}
```

---

## WebSocket

### `ws://localhost:8000/ws/rates/`
Stream de tasas en tiempo real.

**Mensaje recibido:**
```json
{
  "type": "rate_update",
  "data": {
    "USD": { "buy": 6.9000, "sell": 7.0100, "official": 6.9600 },
    "EUR": { "buy": 7.4000, "sell": 7.6000, "official": 7.5200 }
  },
  "timestamp": "2026-04-07T10:30:00-04:00"
}
```

---

## Códigos de error estándar

```json
{
  "error": "Descripción del error",
  "detail": "Detalle adicional o lista de campos",
  "code": "ERROR_CODE"
}
```

| HTTP | Significado |
|------|-------------|
| 400 | Validación fallida / datos incorrectos |
| 401 | Token expirado o inválido |
| 403 | Sin permiso para la acción |
| 404 | Recurso no encontrado |
| 409 | Conflicto (ej: idempotency key duplicado) |
| 429 | Rate limit excedido |
| 500 | Error interno del servidor |
