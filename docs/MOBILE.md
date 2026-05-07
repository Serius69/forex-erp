# Kapitalya ERP — Mobile (React Native)

App React Native para cajeros en campo. Funcionalidad optimizada para operación rápida desde smartphone.

---

## Estructura de directorios

```
frontend-mobile/ForexERPMobile/
├── index.js                       # Punto de entrada React Native
├── App.tsx                        # Root con NavigationContainer + AuthProvider
├── src/
│   ├── navigation/
│   │   └── AppNavigator.tsx       # Stack + BottomTab navigator
│   ├── screens/
│   │   ├── LoginScreen.tsx        # Autenticación JWT
│   │   ├── DashboardScreen.tsx    # KPIs + tasas + resumen del día
│   │   ├── TransactionScreen.tsx  # Alta de transacción (BUY/SELL)
│   │   ├── InventoryScreen.tsx    # Stock de divisas por sucursal
│   │   ├── TarjetasScreen.tsx     # Inventario + venta de tarjetas prepago
│   │   ├── ReportsScreen.tsx      # Resumen diario por divisa
│   │   └── AlertsScreen.tsx       # Alertas de stock y sistema
│   ├── hooks/
│   │   └── useAuth.tsx            # Hook de autenticación + AsyncStorage
│   ├── services/
│   │   └── api.ts                 # Cliente fetch con JWT + refresh automático
│   └── types/
│       └── index.ts               # Tipos TypeScript compartidos
```

---

## Navegación

```
Stack Navigator (AppNavigator)
├── Login  (si !isAuthenticated)
└── Main   (si isAuthenticated)
    └── BottomTab Navigator
        ├── Dashboard   📊
        ├── Transaction 💱
        ├── Inventory   🏦
        ├── Tarjetas    💳
        ├── Reports     📈
        └── Alerts      🔔
```

**`useAuth` hook:**
```typescript
const { isAuthenticated, isLoading, user, login, logout } = useAuth();
// - Persiste tokens en AsyncStorage
// - Carga user al iniciar app desde /users/me/
// - Expone logout() que limpia AsyncStorage
```

---

## Pantallas

### `LoginScreen`
- Input username + password
- Llama `authApi.login()` → guarda `access_token` + `refresh_token` en AsyncStorage
- Navega a `Main` automáticamente al autenticar

### `DashboardScreen`
- Tasas actuales (USD, EUR, ARG, BRL) en tarjetas de color
- Predicción próxima hora (Prophet)
- Resumen del día: operaciones, volumen, ganancia estimada
- Acceso rápido a nueva transacción
- Polling cada 60 segundos (sin WebSocket en mobile por simplicidad)

### `TransactionScreen`
- Selector BUY / SELL
- Selector de divisa
- Campo de monto con cálculo automático en tiempo real
- Búsqueda de cliente por documento
- Campo PIN (para transacciones que requieren supervisor)
- Confirmación y submit

### `InventoryScreen`
- Lista de divisas con stock actual
- Semáforo visual: verde (OK) / amarillo (bajo) / rojo (crítico)
- Valor en BOB al TC de venta

### `TarjetasScreen`
- Inventario por tipo de tarjeta (operadora + denominación)
- Stock disponible y precio de venta promedio
- Modal de venta rápida: cantidad + precio + medio de pago

### `ReportsScreen`
- Resumen del día agrupado por divisa
- Total compras / ventas / ganancia estimada
- Selector de fecha

### `AlertsScreen`
- Alertas de bajo stock
- Botón "marcar como leída" → `POST /api/inventory/alerts/{id}/resolve/`

---

## Servicio API (`src/services/api.ts`)

```typescript
// Función base con renovación automática de token
async function request<T>(endpoint, options?, requirePin?): Promise<T>

// Módulos disponibles:
authApi.login(credentials)          // POST /auth/login/
authApi.logout()                    // Limpia AsyncStorage
authApi.getMe()                     // GET /users/me/

ratesApi.getCurrent()               // GET /rates/exchange-rates/current/

transactionsApi.create(payload, pin) // POST /transactions/
transactionsApi.getList(date?)       // GET /transactions/?date_from=...
transactionsApi.getDailySummary()    // GET /transactions/daily-summary/
transactionsApi.searchCustomer(doc)  // GET /customers/search/?document=...

inventoryApi.getAll()               // GET /inventory/stock/

alertsApi.getActive()               // GET /inventory/alerts/?is_resolved=false
alertsApi.markRead(id)              // POST /inventory/alerts/{id}/resolve/

tarjetasApi.getInventario()         // GET /tarjetas/tipos/inventario/
tarjetasApi.vender(tipoId, payload) // POST /tarjetas/tipos/{id}/vender/

capitalApi.getActual()              // GET /capital/actual/
reportsApi.getDaily(date?)          // GET /transactions/... + agrupación local
```

**Configuración de URL base:**
```typescript
// src/services/api.ts
const BASE_URL = 'http://10.0.2.2:8007/api'; // Android emulator
// Para dispositivo físico, cambiar a la IP local del servidor
// const BASE_URL = 'http://192.168.1.X:8007/api';
```

---

## Dependencias principales

```json
{
  "@react-navigation/native": "^6.x",
  "@react-navigation/native-stack": "^6.x",
  "@react-navigation/bottom-tabs": "^6.x",
  "@react-native-async-storage/async-storage": "^1.x"
}
```

---

## Configuración de desarrollo

```bash
# Instalar dependencias
cd frontend-mobile/ForexERPMobile
npm install

# Iniciar Metro bundler
npm start

# Correr en Android (con emulador activo)
npm run android

# Correr en iOS (solo macOS)
npm run ios
```

**Prerrequisitos:**
- Android Studio con emulador configurado (o dispositivo físico con USB debugging)
- Java 17+
- Backend Django corriendo en puerto 8007

---

## Funcionalidades pendientes (ver ROADMAP.md)

- Modo offline con sincronización posterior
- Notificaciones push (Firebase)
- Biometría para PIN supervisor
- Soporte iOS (actualmente solo Android)
