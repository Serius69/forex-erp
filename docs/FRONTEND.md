# Kapitalya ERP — Frontend Web

React + Redux Toolkit + Vite. Diseñado para operación en escritorio (resolución mínima 1280px).

---

## Estructura de directorios

```
frontend-web/src/
├── App.tsx                        # Router principal + providers
├── contexts/
│   ├── AuthContext.tsx             # Estado de autenticación global
│   └── WebSocketContext.tsx        # Conexión WS tasas en tiempo real
├── store/
│   ├── index.ts                    # Configuración Redux store
│   └── slices/
│       ├── dashboardSlice.ts       # KPIs del dashboard
│       ├── transactionsSlice.ts    # Lista y filtros de transacciones
│       ├── inventorySlice.ts       # Stock por divisa
│       ├── predictionsSlice.ts     # Predicciones ML
│       └── notificationsSlice.ts   # Alertas del sistema
├── components/
│   ├── auth/Login.tsx
│   ├── dashboard/
│   │   ├── Dashboard.tsx           # Pantalla principal
│   │   ├── ExchangeRatesCard.tsx   # Tasas actuales
│   │   ├── InventoryStatus.tsx     # Semáforo de stock
│   │   ├── PredictionsChart.tsx    # Gráfico Prophet/LSTM
│   │   ├── QuickActions.tsx        # Acciones rápidas
│   │   ├── RecentTransactions.tsx  # Últimas operaciones
│   │   └── TransactionChart.tsx    # Volumen diario
│   ├── transactions/
│   │   ├── Transactions.tsx        # Contenedor
│   │   ├── TransactionForm.tsx     # Alta de operación
│   │   ├── TransactionHistory.tsx  # Historial con filtros
│   │   ├── TransactionDetails.tsx  # Modal detalle + PDF
│   │   └── TransactionPending.tsx  # Operaciones pendientes
│   ├── inventory/
│   │   ├── Inventory.tsx
│   │   ├── InventoryStock.tsx      # Tabla por divisa/sucursal
│   │   ├── InventoryMovements.tsx  # Historial movimientos
│   │   └── InventoryTransfers.tsx  # Transferencias inter-sucursal
│   ├── predictions/
│   │   ├── Predictions.tsx
│   │   └── PredictionsChart.tsx    # Chart.js/Recharts con intervalos
│   ├── reports/
│   │   ├── Reports.tsx
│   │   ├── ReportsMain.tsx         # Generación de reportes
│   │   ├── ReportsHistory.tsx      # Listado histórico
│   │   └── ReportsScheduled.tsx    # Reportes programados
│   ├── capital/Capital.tsx         # Capital + snapshots + gastos
│   ├── ganancias/Ganancias.tsx     # P&G por divisa y período
│   ├── tarjetas/Tarjetas.tsx       # Inventario tarjetas + ventas
│   ├── rates/Rates.tsx             # Gestión de tasas
│   ├── customers/Customers.tsx     # CRUD clientes + KYC
│   ├── settings/Settings.tsx       # Configuración del sistema
│   ├── admin/UserAdmin.tsx         # Gestión de usuarios (ADMIN)
│   └── common/
│       ├── MainLayout.tsx          # Sidebar + header
│       ├── PrivateRoute.tsx        # Guard JWT
│       ├── ConfirmDialog.tsx       # Modal de confirmación
│       ├── PinDialog.tsx           # Ingreso PIN supervisor
│       ├── NotificationPanel.tsx   # Panel alertas/notificaciones
│       └── ResponsiveContainer.tsx # Layout adaptable
├── services/
│   └── api.ts                      # Cliente Axios + interceptores JWT
├── utils/
│   ├── finance.ts                  # Cálculos financieros frontend
│   └── formatters.ts               # Formateadores moneda/fecha
├── styles/
│   └── theme.ts                    # Paleta de colores y tokens MUI
└── types/
    └── index.ts                    # Tipos TypeScript compartidos
```

---

## Manejo de estado (Redux Toolkit)

```typescript
// store/index.ts
store = {
  dashboard:     dashboardReducer,   // KPIs, stats diarios
  transactions:  transactionsReducer, // lista, filtros, selección
  inventory:     inventoryReducer,    // stock, alertas
  predictions:   predictionsReducer,  // predicciones ML activas
  notifications: notificationsReducer // alertas sistema
}
```

Cada slice sigue el patrón `createAsyncThunk` para llamadas API:

```typescript
// Ejemplo: cargar transacciones
const fetchTransactions = createAsyncThunk(
  'transactions/fetchAll',
  async (filters) => {
    const { data } = await api.get('/transactions/', { params: filters });
    return data;
  }
);
```

---

## Autenticación (AuthContext)

```typescript
// contexts/AuthContext.tsx
const { user, login, logout, isAuthenticated } = useAuth();

// Login guarda tokens en localStorage
// Axios interceptor adjunta Bearer token automáticamente
// Refresh automático en 401 con cola de requests en espera
```

**Flujo de renovación de token:**
1. Request recibe 401
2. Si no está refrescando: solicita nuevo token con refresh_token
3. Si ya está refrescando: encola el request fallido
4. Al obtener nuevo token: reintenta todos los encolados

---

## WebSocket (Tasas en tiempo real)

```typescript
// contexts/WebSocketContext.tsx
const ws = new WebSocket('ws://localhost:8000/ws/rates/');
ws.onmessage = (event) => {
  const rates = JSON.parse(event.data);
  dispatch(updateRates(rates)); // Redux store
};
```

El componente `ExchangeRatesCard` se actualiza automáticamente cuando llegan nuevas tasas.

---

## Servicio API (`services/api.ts`)

```typescript
import { api } from './services/api';

// Todos los requests llevan JWT automáticamente
const response = await api.get('/transactions/');
const { data } = await api.post('/transactions/', payload);

// Idempotency-Key automático en POST /transactions/
// (previene duplicados por doble-click o reconexión)
```

**Función `parseRates()`:** Normaliza respuesta de tasas (acepta array o mapa) a formato estándar `{ USD: { buy, sell, official, spread } }`.

---

## Utilidades financieras (`utils/finance.ts`)

```typescript
// Formatear moneda boliviana
formatBOB(1234.5)          // → "Bs. 1.234,50"
formatCurrency(100, 'USD') // → "$ 100.00"
formatRate(6.9600)         // → "6.9600"
calcAmountTo(amount, rate, type) // BUY: amount * rate, SELL: amount / rate
```

---

## Componentes clave

### `TransactionForm`
- Formulario de alta de operación (BUY/SELL)
- Cálculo automático de `amount_to` al cambiar monto o tasa
- Búsqueda de cliente por número de documento
- PIN dialog si monto supera el límite supervisor
- Idempotency-Key en el header para evitar duplicados

### `PredictionsChart`
- Muestra predicciones Prophet + LSTM para las próximas 24h
- Intervalos de confianza como área sombreada
- Indicador de confianza por modelo

### `Capital` / `Ganancias`
- Capital: desglose efectivo + QR + divisas + tarjetas − pasivos
- Ganancias: P&G por divisa con spread promedio y margen %
- Gastos: CRUD gastos operativos por categoría

### `PinDialog`
- Modal para ingreso de PIN de supervisor
- Se activa desde `TransactionForm` cuando `requires_supervisor = true`
- Envía PIN hasheado al backend para validación

---

## Variables de entorno

```bash
# frontend-web/.env.local
REACT_APP_API_URL=http://localhost:8000/api
REACT_APP_WS_URL=ws://localhost:8000
```
