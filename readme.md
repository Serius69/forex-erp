# Kapitalya ERP

Sistema ERP integral para casas de cambio bolivianas. Gestión en tiempo real de tasas, transacciones, inventario, capital y cumplimiento regulatorio ASFI.

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Backend | Django 4.2 + Django REST Framework |
| Base de datos | PostgreSQL 15 |
| Broker de tareas | RabbitMQ (`amqp`) |
| Cache / result backend | Redis 7 (cache Django + Channels) · `django_celery_results` (result) |
| Tareas asíncronas | Celery + Celery Beat (`DatabaseScheduler`) |
| WebSocket | Django Channels |
| Frontend web | React 18 + TypeScript + Vite 5 + MUI 5 + Redux Toolkit |
| Mobile | React Native 0.73 (CLI, no Expo) — Android |
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
│  users │ rates │ transactions │ inventory │ predictions │ macro   │
│  reports │ capital │ tarjetas │ alerts │ analytics │ tenants      │
└──────┬────────────────────────────────────────┬─────────────────┘
       │                                        │
┌──────▼──────┐                    ┌────────────▼────────────┐
│ PostgreSQL  │                    │  Redis (cache/Channels)  │
│   (datos)   │                    │  RabbitMQ (broker Celery)│
└─────────────┘                    └─────────────────────────┘
```

---

## Apps Django

| App | Dominio |
|-----|---------|
| `users` | Usuarios, sucursales, roles, autenticación, 2FA |
| `rates` | Tasas de cambio en tiempo real, motor FX, spreads dinámicos |
| `transactions` | Compra/venta de divisas, clientes KYC, auditoría |
| `inventory` | Stock por sucursal, costeo WAC, transferencias |
| `predictions` | Pronósticos ML ensemble 5 modelos (3 series de mercado por par) |
| `macro` | Indicadores macroeconómicos Bolivia (World Bank, USD internacional) + noticias |
| `reports` | Cumplimiento ASFI: RTE (automático), ROUE, PEP, Libro Diario |
| `capital` | Posición de capital, P&L RT, gastos, ingresos extra, cuentas por pagar, caja chica |
| `tarjetas` | Tarjetas prepago con costeo FIFO |
| `alerts` | Sistema unificado de alertas cross-módulo |
| `analytics` | Analytics por sucursal + seed del schedule de Celery Beat (`0007`) |
| `snapshots` | Snapshots P&L, exposición, spread |
| `data_migration` | Importación/sincronización desde Google Sheets (auto-sync + backfill del sistema legado) |
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
| Frontend web + API (vía nginx) | http://localhost:9091 |
| API REST (backend directo) | http://localhost:9092/api |
| Admin Django | http://localhost:9092/admin |
| WebSocket | ws://localhost:9092/ws (o vía nginx :9091) |

> El backend escucha en 8007 **dentro** del contenedor; el compose solo publica
> 9091 (nginx) y 9092 (backend directo). En dev sin Docker: `runserver 0.0.0.0:8007`.

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
cd frontend-mobile/ForexERPMobile

npm install --legacy-peer-deps
npm start                # Metro bundler en 8081
npm run android          # emulador/dispositivo Android
```

> La URL del backend se configura en `src/config.ts` (`API_BASE_URL`). En emulador
> Android, `10.0.2.2` = localhost del host: `http://10.0.2.2:8007/api` con `runserver`
> directo, o puerto `9092` si el backend corre en Docker. Es un repo git anidado
> (gitlink): commitear dentro del subrepo. Ver `docs/MOBILE.md`.

---

## Módulos principales

### Motor de tasas FX (`rates/`)

El motor consume exclusivamente fuentes P2P en tiempo real:

| Fuente | Tipo |
|--------|------|
| Binance P2P (+ cross-rate multi-fiat) | Mercado peer-to-peer |
| Bitget P2P | Mercado peer-to-peer |
| Bybit P2P | Mercado peer-to-peer |
| OKX P2P | Mercado peer-to-peer |
| Airtm v2 | Quote API |
| Eldorado | Exchange online |
| Wallbit | Exchange online |
| SaldoAR | Exchange online |
| CriptoYa / DolarAPI / DólaresABolivianos | Agregadores |
| DolarBlue Bolivia | Referencia digital |

> El conjunto de fuentes es **configurable por base de datos** (`rates.ParallelSource`,
> tipos: `digital` / `P2P` / `EXCHANGE` / `AGREGADOR` / `WALLET`). La tabla es la foto
> de fetchers disponibles en `rates/fetchers/`; cuáles se consultan lo decide `_load_active_sources`.

**Algoritmo:** Media Winsorizada ponderada con recorte IQR de outliers. Degradación elegante con fallback histórico.

**Variantes de efectivo:** `USD_LOOSE` (−0.30 BOB), `USD_SMALL_BILLS` (−0.60 BOB), `PEN_COINS` (spread ampliado).

**Endpoints clave:**
```
GET /api/rates/fx-engine/                                          # Tasas paralelas RT
GET /api/rates/reference/                                          # Tasas de referencia (BCB/BCP históricas; BCB deprecado como fuente en vivo — ver DEPRECATED_BCB.md)
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

**3 series de mercado independientes por par** (`?market=`), cada una con su propio modelo:

| `market` | Fuente | Cobertura |
|----------|--------|-----------|
| `web` | Dólar blue digital (dolarbluebolivia) | solo USD/BOB (profunda) |
| `competencia` | CSV físico de mercado | 6 pares |
| `empresa` | Derivada de las transacciones reales de la casa | 6 pares (USD) |

> Default: `web` para USD/BOB, `competencia` para el resto. `market` inválido → 400.

**Endpoints:**
```
GET /api/predictions/forecast/USD-BOB/?horizon=24h&ci=true&market=web   # Pronóstico con IC
GET /api/predictions/health/                                            # Salud de modelos
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
    /api/capital/gastos/         # CRUD de gastos (categorías + medio de pago)
    /api/capital/ingresos/       # CRUD de ingresos extra (+ resumen/ por tipo)
    /api/capital/acreedores/     # Cuentas por pagar (+ resumen/ total adeudado); saldo por acreedor
    /api/capital/acreedores-movimientos/   # Ledger de cargos/abonos por acreedor
    /api/capital/caja-chica/     # Ledger de caja chica (+ saldo/ vigente)
```

**Cuentas por pagar (`Acreedor`) y caja chica (`MovimientoCajaChica`):** ledgers propios.
El saldo del acreedor se deriva de sus movimientos (CARGO − ABONO, anotado sin N+1); la
caja chica es apertura + ingresos − egresos. Ambos migrados del sistema legado en Sheets.

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

**Flujo JWT:**
- Access token: en memoria JS únicamente (nunca localStorage), TTL 15 min en producción
- Refresh token: **localStorage** (rotado en cada refresh, limpiado en logout). Moverlo a
  cookie httpOnly está pendiente — requiere cambio backend coordinado con la app móvil
  (estado verificado 2026-07-08)
- Login con email O username (`EmailOrUsernameBackend`)
- Bloqueo de cuenta: 5 intentos fallidos → bloqueo 15 minutos
- OAuth Google disponible en login y signup
- **Signup con aprobación:** el registro público NO auto-une como CASHIER; la cuenta
  queda `is_active=False` sin empresa y sin tokens (`pending_approval`) hasta que un
  ADMIN la apruebe (aplica a email y Google)

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
| `high` | Alertas, RTE, cache de pronósticos, tareas sensibles a latencia |
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
│   ├── predictions/        # ML ensemble, pipeline, monitoring (3 series de mercado)
│   ├── macro/              # Indicadores macro Bolivia + noticias (World Bank, USD int'l)
│   ├── reports/            # Reportes ASFI (RTE automático + export CSV)
│   ├── capital/            # Capital, posición, KPIs, gastos, ingresos extra
│   ├── tarjetas/           # Tarjetas prepago FIFO
│   ├── alerts/             # Alertas cross-módulo
│   ├── analytics/          # Analytics + seed beat schedule
│   ├── snapshots/          # Snapshots P&L/exposición/spread
│   ├── data_migration/     # Import/sync (Google Sheets)
│   ├── tenants/            # Multi-tenant SaaS
│   ├── scripts/            # seed_data, seed_kapitalya
│   └── requirements.txt    # (+ requirements-gpu.txt para torch local)
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
├── frontend-mobile/ForexERPMobile/   # App React Native (repo git anidado)
├── frontend/                         # variante/legacy del frontend web
├── nginx/                            # config del reverse proxy
├── docs/                             # API, ARCHITECTURE, BACKEND, BUSINESS_LOGIC,
│                                     #   DEPLOYMENT, FRONTEND, ML_MODELS, MOBILE, ROADMAP
├── docker-compose.yml
├── docker-compose.prod.yml
└── docker-compose.tailscale.yml
```

---

## Documentación adicional

| Documento | Contenido |
|-----------|-----------|
| [docs/API.md](docs/API.md) | Endpoints REST, payloads, ejemplos |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Arquitectura del sistema |
| [docs/BACKEND.md](docs/BACKEND.md) | Detalle de las apps Django |
| [docs/BUSINESS_LOGIC.md](docs/BUSINESS_LOGIC.md) | Reglas de negocio |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker, producción, nginx, SSL |
| [docs/FRONTEND.md](docs/FRONTEND.md) | React web, Redux, componentes clave |
| [docs/MOBILE.md](docs/MOBILE.md) | React Native, pantallas, navegación |
| [docs/ML_MODELS.md](docs/ML_MODELS.md) | Ensemble de predicción |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Roadmap del producto |

---

## Localización

- **Idioma:** español boliviano (es-BO) por defecto, inglés disponible (toggle en UI)
- **Zona horaria:** `America/La_Paz`
- **Moneda base:** BOB (Boliviano)
- **Regulador:** ASFI — Autoridad de Supervisión del Sistema Financiero, Bolivia

---

## Licencia

Propietario — Kapitalya © 2026. Todos los derechos reservados.
