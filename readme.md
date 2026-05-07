# Kapitalya ERP

Sistema ERP integral para casas de cambio bolivianas. Gestión en tiempo real de tasas, transacciones, inventario, capital y cumplimiento regulatorio ASFI.

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Backend | Django 4.2 + Django REST Framework |
| Base de datos | PostgreSQL 15 |
| Cache / Broker | Redis 7 |
| Tareas asíncronas | Celery + Celery Beat |
| WebSocket | Django Channels |
| Frontend web | React 18 + TypeScript + Vite 5 + MUI 5 + Redux Toolkit |
| Mobile | React Native |
| Machine Learning | Prophet + BiLSTM + XGBoost + ARIMA + Ridge Ensemble |
| Contenedores | Docker + Docker Compose |
| Proxy inverso | Nginx |

---

## Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────────────┐
│                        Clientes                                  │
│  Browser (React/Vite)    Mobile (React Native)    Admin Django   │
└───────────────┬─────────────────┬───────────────────────────────┘
                │ HTTP/WS         │ HTTP
                ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Nginx (reverse proxy)                          │
│           /api → gunicorn:8007   /ws → channels                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    Django REST API                                │
│  users │ rates │ transactions │ inventory │ predictions          │
│  reports │ capital │ tarjetas │ alerts │ analytics │ tenants     │
└──────┬────────────────────────────────────────┬─────────────────┘
       │                                        │
┌──────▼──────┐                        ┌────────▼────────┐
│ PostgreSQL  │                        │  Redis / Celery  │
│   (datos)   │                        │  (cache + tasks) │
└─────────────┘                        └─────────────────┘
```

---

## Apps Django

| App | Dominio |
|-----|---------|
| `users` | Usuarios, sucursales, roles, autenticación, 2FA |
| `rates` | Tasas de cambio en tiempo real, motor FX, spreads dinámicos |
| `transactions` | Compra/venta de divisas, clientes KYC, auditoría |
| `inventory` | Stock por sucursal, costeo WAC, transferencias |
| `predictions` | Pronósticos ML ensemble 5 modelos |
| `reports` | Cumplimiento ASFI: RTE, ROUE, PEP, Libro Diario |
| `capital` | Gastos, posición de capital, P&L en tiempo real |
| `tarjetas` | Tarjetas prepago con costeo FIFO |
| `alerts` | Sistema unificado de alertas cross-módulo |
| `analytics` | Snapshots P&L, exposición, spread |
| `tenants` | Multi-tenant SaaS: Company + Subscription |

---

## Inicio rápido

### Prerequisitos

- Docker y Docker Compose instalados
- Git

### 1. Clonar el repositorio

```bash
git clone <repo-url>
cd forex-erp
```

### 2. Configurar variables de entorno

```bash
cp backend/.env.example backend/.env
```

Editar `backend/.env` con tus credenciales:

```env
SECRET_KEY=your-secret-key-here
DB_PASSWORD=your-db-password
REDIS_URL=redis://redis:6379/0
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# OAuth Google (opcional)
GOOGLE_CLIENT_ID=your-google-client-id

# APIs de tasas paralelas (opcional pero recomendado)
ELDORADO_API_TOKEN=your-token
WALLBIT_API_KEY=your-key
```

### 3. Levantar con Docker

```bash
docker compose up -d

# Aplicar migraciones
docker compose exec backend python manage.py migrate

# Crear superusuario
docker compose exec backend python manage.py createsuperuser

# (Opcional) Cargar datos iniciales
docker compose exec backend python manage.py seed_data
```

### 4. Acceder al sistema

| Servicio | URL |
|---------|-----|
| API REST | http://localhost:8007/api |
| Admin Django | http://localhost:8007/admin |
| Frontend web | http://localhost:3000 |
| WebSocket | ws://localhost:8007/ws |

---

## Desarrollo local (sin Docker)

### Backend

```bash
cd backend

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

pip install -r requirements.txt

python manage.py migrate
python manage.py runserver 0.0.0.0:8007

# En otra terminal: worker Celery
celery -A core worker -l info

# En otra terminal: scheduler de tareas
celery -A core beat -l info
```

### Frontend web

```bash
cd frontend-web

npm install
npm run dev    # http://localhost:5173
```

> En desarrollo, Vite hace proxy de `/api` → `localhost:8007` y `/ws` → `ws://localhost:8007` automáticamente. No se necesita `VITE_API_BASE_URL`.

### App móvil

```bash
cd mobile

npm install
npx react-native run-android   # emulador Android (API: 10.0.2.2:8000)
```

---

## Módulos principales

### Motor de tasas FX (`rates/`)

El motor consume exclusivamente fuentes P2P en tiempo real:

| Fuente | Tipo |
|--------|------|
| Binance P2P | Mercado peer-to-peer |
| Bitget P2P | Mercado peer-to-peer |
| Bybit P2P | Mercado peer-to-peer |
| Airtm v2 | Quote API |
| Eldorado | Exchange online |
| Wallbit | Exchange online |
| SaldoAR | Exchange online |
| DolarBlue Bolivia | Referencia |

**Algoritmo:** Media Winsorizada ponderada con recorte IQR de outliers. Degradación elegante con fallback histórico.

**Variantes de efectivo:** `USD_LOOSE` (−0.30 BOB), `USD_SMALL_BILLS` (−0.60 BOB), `PEN_COINS` (spread ampliado).

**Endpoints clave:**
```
GET /api/rates/fx-engine/                                          # Tasas paralelas RT
GET /api/rates/reference/                                          # Tasas BCB/BCP
GET /api/rates/parallel-rate/?currency=USD                         # Tasa paralela (cache 60s)
GET /api/rates/dynamic-spread/?currency=USD&customer_tier=VIP      # Spread dinámico
GET /api/rates/profitability-analysis/?start=&end=                 # Análisis de rentabilidad
```

**Actualización automática (Celery Beat):**
- `rates.run_fx_engine` — cada 5 minutos
- `rates.fetch_reference_rates` — cada 30 minutos

### Transacciones y antifraude (`transactions/`)

Cada transacción pasa por el motor `FraudDetectionEngine` antes de ser aprobada:

| Regla | Descripción |
|-------|-------------|
| Velocity check | Límite de operaciones por cliente en ventana de tiempo |
| Amount anomaly | Montos fuera de 3σ del histórico del cajero |
| Rate sanity | Desviación excesiva respecto a tasa paralela |
| Duplicate detection | Ventana de 5 minutos |
| Blacklist / PEP | Lista negra y personas expuestas políticamente |
| High value | Escalado automático a aprobación supervisora |

**Resultado:** `APPROVE | REQUIRE_APPROVAL | BLOCK`

**Ciclo de vida:** DRAFT → PENDING_RATE → APPROVED → PROCESSING → COMPLETED / FAILED

**Auditoría inmutable:** cada cambio de estado genera un `TransactionAuditLog` con checksum SHA-256 verificable.

### Motor ML Ensemble (`predictions/`)

Stack de 5 modelos con pesos dinámicos recalculados cada 4 horas:

| Modelo | Especialidad |
|--------|-------------|
| Prophet | Tendencias y estacionalidad |
| BiLSTM + MultiHeadAttention | Patrones secuenciales cortos |
| XGBoost | Features técnicos y lag |
| ARIMA | Series estacionarias |
| Ridge meta-learner | Combinación óptima de predicciones |

**Objetivos de precisión:** MAPE < 0.5% a 1h, < 1.5% a 24h.

**Endpoints:**
```
GET /api/predictions/forecast/USD-BOB/?horizon=24h&ci=true   # Pronóstico con IC
GET /api/predictions/health/                                  # Salud de modelos
```

**Beat schedule ML:**
- 02:00 diario — reentrenamiento completo de todos los modelos
- Cada 4 horas — recálculo de pesos ensemble
- Cada hora (min 5) — calentamiento de cache Redis
- Domingos 03:00 — backtesting + alertas MAPE
- Sábados 04:00 — tuning de hiperparámetros con Optuna

### Capital y P&L (`capital/`)

Visibilidad financiera en tiempo real por sucursal.

**Fórmulas:**
```
Capital = efectivo_BOB + QR_BOB + Σ(stock_divisa × TC_venta)
        + Σ(stock_tarjetas × precio_venta_prom) - pasivos_BOB

Ganancia_divisas = Σingreso_BOB_ventas − Σcosto_BOB_compras  (por par, por período)

Ganancia_neta = ganancia_divisas + ganancia_tarjetas − total_gastos
```

**Endpoints:**
```
GET /api/capital/position/       # Posición RT (cache 30s, ?refresh=true para forzar)
GET /api/capital/pnl/            # P&L del período
GET /api/capital/history/        # Historial de snapshots diarios
GET /api/capital/alerts/         # Alertas activas de capital
GET /api/capital/metrics/kpis/   # KPIs cacheados en Redis
```

**KPIs disponibles:** ROE diario/anual, rotación de inventario, días de inventario, WACC divisas, break-even spread.

### Cumplimiento ASFI (`reports/`)

Reportes regulatorios bolivianos generados automáticamente:

| Reporte | Descripción |
|---------|-------------|
| RTE | Registro de Transacciones en Efectivo |
| ROUE | Reporte de Operaciones Inusuales/Especiales |
| PEP | Personas Expuestas Políticamente |
| DailyOperationLog | Libro Diario de Operaciones |

---

## Autenticación y seguridad

**Flujo JWT seguro:**
- Access token: en memoria JS únicamente (nunca localStorage), TTL 15 min en producción
- Refresh token: httpOnly cookie (path=/api/auth/), inaccesible desde JavaScript
- Login con email O username (`EmailOrUsernameBackend`)
- Bloqueo de cuenta: 5 intentos fallidos → bloqueo 15 minutos
- OAuth Google disponible en login y signup

**Roles del sistema:**

| Rol | Ruta por defecto |
|-----|-----------------|
| ADMIN | `/dashboard` |
| SUPERVISOR | `/analytics` |
| CASHIER | `/transactions` |

**Headers de seguridad:** CSP, X-Frame-Options, X-Content-Type-Options configurados en `SecurityHeadersMiddleware`.

---

## Multi-tenant SaaS (`tenants/`)

El sistema soporta múltiples empresas completamente aisladas:

- `Company` (slug, país, moneda base) — tenant raíz
- `Subscription` (plan: FREE / STARTER / GROWTH / ENTERPRISE)
- Todo dato filtrado por `company_id` a nivel de ViewSet
- `IsCompanyMember` bloquea acceso cross-tenant en la capa API
- CASHIER adicionalmente restringido a su propia sucursal

---

## Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | — |
| `DB_PASSWORD` | Contraseña PostgreSQL | — |
| `REDIS_URL` | URL de Redis | `redis://redis:6379/0` |
| `ALLOWED_HOSTS` | Hosts permitidos | `localhost` |
| `GOOGLE_CLIENT_ID` | OAuth Google | — |
| `ELDORADO_API_TOKEN` | API Eldorado | — |
| `WALLBIT_API_KEY` | API Wallbit | — |
| `CAPITAL_MIN_BOB` | Alerta capital mínimo | `50000` |
| `CAPITAL_MAX_CONCENTRATION` | Concentración máxima % | `60` |
| `CAPITAL_MIN_PNL_DAILY` | Alerta P&L mínimo diario | `-5000` |
| `PARALLEL_RATE_CACHE_TTL` | TTL cache tasa paralela (s) | `60` |
| `SPREAD_CACHE_TTL` | TTL cache spread (s) | `30` |
| `KPI_CACHE_TTL` | TTL cache KPIs (s) | `300` |

---

## Colas Celery

| Cola | Tareas |
|------|--------|
| `critical` | Tasas FX, capital RT, detección de fraude |
| `default` | Analytics, inventario |
| `low` | ML (entrenamiento), reportes, backups |

---

## Throttling de la API

| Throttle | Límite |
|---------|--------|
| `ForexBurstThrottle` | 60 req/min |
| `ForexSustainedThrottle` | 1000 req/hora |
| `ForexAuthThrottle` | 10 req/min |
| `ForexTransactionThrottle` | 30 req/min |
| `ForexAnalyticsThrottle` | 120 req/min |
| `ForexRatesThrottle` | 60 req/min |

---

## Estructura del proyecto

```
forex-erp/
├── backend/
│   ├── core/               # Settings, URLs, middleware, Celery, permisos base
│   ├── users/              # Auth, roles, sucursales
│   ├── rates/              # Motor FX, fetchers P2P, spreads
│   │   └── fetchers/       # binance_p2p, airtm_v2, eldorado, wallbit, saldoar...
│   ├── transactions/       # Transacciones, fraude, auditoría
│   ├── inventory/          # Stock, WAC, transferencias
│   ├── predictions/        # ML ensemble, pipeline, monitoring
│   ├── reports/            # Reportes ASFI
│   ├── capital/            # Capital, posición, KPIs
│   ├── tarjetas/           # Tarjetas prepago FIFO
│   ├── alerts/             # Alertas cross-módulo
│   ├── analytics/          # Snapshots y analytics
│   ├── tenants/            # Multi-tenant SaaS
│   ├── scripts/            # seed_data, seed_kapitalya
│   └── requirements.txt
├── frontend-web/
│   ├── src/
│   │   ├── components/     # UI compartida (KPICard, SkeletonLoader, RoleRoute...)
│   │   ├── contexts/       # AuthContext, WebSocketContext
│   │   ├── pages/          # Dashboard, Transactions, Rates, Analytics...
│   │   ├── services/       # api.ts, analyticsApi.ts
│   │   ├── store/          # Redux Toolkit + Zustand WebSocket store
│   │   └── i18n/           # es (default) + en translations
│   ├── index.html
│   └── vite.config.ts
├── docs/
│   ├── API.md
│   ├── DEPLOYMENT.md
│   ├── FRONTEND.md
│   └── MOBILE.md
├── docker-compose.yml
├── docker-compose.prod.yml
└── docker-compose.tailscale.yml
```

---

## Documentación adicional

| Documento | Contenido |
|-----------|-----------|
| [docs/API.md](docs/API.md) | Endpoints REST, payloads, ejemplos |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker, producción, nginx, SSL |
| [docs/FRONTEND.md](docs/FRONTEND.md) | React web, Redux, componentes clave |
| [docs/MOBILE.md](docs/MOBILE.md) | React Native, pantallas, navegación |

---

## Localización

- **Idioma:** español boliviano (es-BO) por defecto, inglés disponible (toggle en UI)
- **Zona horaria:** `America/La_Paz`
- **Moneda base:** BOB (Boliviano)
- **Regulador:** ASFI — Autoridad de Supervisión del Sistema Financiero, Bolivia

---

## Licencia

Propietario — Kapitalya © 2026. Todos los derechos reservados.
