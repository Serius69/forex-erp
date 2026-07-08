# Forex ERP (Kapitalya) — Instrucciones para Claude Code

ERP integral para casas de cambio bolivianas: tasas FX en tiempo real (fuentes P2P),
transacciones con antifraude, inventario WAC, tarjetas prepago FIFO, capital/P&L,
predicciones ML ensemble y cumplimiento ASFI. Multi-tenant SaaS.

> Fuente de verdad del producto: `readme.md` y `docs/` (API, ARCHITECTURE, BACKEND,
> FRONTEND, MOBILE, ML_MODELS, ROADMAP). Este archivo es solo el índice para Claude.

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | Django 4.2 + DRF, Channels (WS), Celery + Beat |
| Datos | PostgreSQL 15 · Redis 7 (cache/broker) · RabbitMQ |
| Frontend web | React 18 + TS + Vite 5 + MUI 5 + Redux Toolkit |
| Mobile | React Native 0.73 (CLI, no Expo) — Android (iOS parcial) |
| ML | Prophet + BiLSTM + XGBoost + ARIMA + Ridge ensemble |
| Infra | Docker Compose + Nginx |

## Puertos

| Servicio | Puerto |
|----------|--------|
| Backend Django (gunicorn, en contenedor) | 8007 |
| Nginx host — frontend + API (`/api`) | 9091 → 80 |
| Nginx host — backend directo | 9092 → 8007 |
| Frontend web (Vite dev) | 5173 |
| WebSocket (Channels) | `/ws` vía 8007 |
| **Metro bundler (React Native)** | **8081** (por defecto RN; sin colisión con el ecosistema 8100+) |

La app móvil apunta al backend vía `src/config.ts` (`API_BASE_URL`).
Emulador Android usa `10.0.2.2` como `localhost` del host:
`runserver` directo → `http://10.0.2.2:8007/api`; `docker compose up` → puerto `9092`.

## Estructura

```
forex-erp/
├── backend/                     # Django: users, rates, transactions, inventory,
│                                #   predictions, reports, capital, tarjetas,
│                                #   alerts, analytics, tenants
├── frontend-web/                # React + Vite + Redux (SPA)
├── frontend/                    # (variante/legacy)
├── frontend-mobile/ForexERPMobile/   # App React Native (submódulo git anidado)
│   ├── App.tsx  index.js  metro.config.js  jest.config.js  jest.setup.js
│   └── src/
│       ├── config.ts            # API_BASE_URL + METRO_PORT
│       ├── navigation/AppNavigator.tsx   # Stack (Login/Main) + BottomTab (6)
│       ├── screens/             # Login, Dashboard, Transaction, Inventory,
│       │                        #   Tarjetas, Reports, Alerts
│       ├── hooks/               # useAuth (JWT+PIN+AsyncStorage), useOfflineSync
│       ├── services/            # api.ts (fetch+refresh), offlineQueue.ts
│       └── types/index.ts
├── docs/                        # documentación de producto
├── nginx/                       # config del reverse proxy
└── docker-compose.yml           # + .prod.yml / .tailscale.yml
```

> `frontend-mobile/ForexERPMobile` es un repo git anidado (gitlink, remoto propio).
> Sus archivos NO se versionan desde el repo raíz; commitear dentro del subrepo.

## Cómo correr (dev)

### Backend + web (Docker)
```bash
docker compose up -d
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py seed_data   # datos demo
# API: http://localhost:9092/api   ·   web+API vía nginx: http://localhost:9091
```

### Backend sin Docker
```bash
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate && python manage.py runserver 0.0.0.0:8007
celery -A core worker -l info      # otra terminal
celery -A core beat -l info        # otra terminal
```

### Frontend web
```bash
cd frontend-web && npm install && npm run dev   # http://localhost:5173 (proxy /api → 8007)
```

### App móvil (React Native)
```bash
cd frontend-mobile/ForexERPMobile
npm install --legacy-peer-deps
npm start                 # Metro en 8081
npm run android           # emulador/dispositivo Android
npx tsc --noEmit          # typecheck (verde)
npm test                  # jest (verde)
# Ajustar host/puerto de la API del backend en src/config.ts
```

## Pendientes

### Backend / Web — cerrados en sesión 2026-07-07
- ✅ WebSocket producción: `CHANNEL_REDIS_URL` (Redis DB 3) cableado en
  `docker-compose.yml` y `k8s/private/forex-erp/deployment-{backend,channels,celery}.yaml`
  (el código ya hacía fallback a InMemory sin la variable).
- ✅ `django_celery_beat`: data migration `analytics/0007_populate_celery_beat_schedules`
  espeja el beat_schedule EFECTIVO (OJO: `CELERY_BEAT_SCHEDULE` de settings pisa al de
  `core/celery.py`, que es config muerta — candidato a limpieza).
- ✅ Tests backend: 152 en verde (`pytest -m 'not ml and not slow and not integration'`
  dentro del contenedor). Nuevos: capital (25+6), tarjetas FIFO (15), profit_margin (7),
  beat (4). Fix preexistentes: `--cov-omit` inválido en pytest.ini → `.coveragerc`;
  slug autogenerado en `Company.save()`; `source='TEST'` en fixtures.
- ✅ `Transaction.profit_margin`: spread real (snapshot paralelo → medio spread vigente
  → fallback 0.3%). Puede ser negativo (operación a pérdida).
- ✅ Web: selector global de sucursal ADMIN (`BranchScopeContext` + Select en sidebar),
  cableado a capital/ganancias/dashboard; backend valida `?branch_id=` contra la empresa
  (`_resolve_branch_scope`); fix `branch_id: 1` hardcodeado en ReportsMain (libro diario).
  Capital/Ganancias/export/WS ya estaban integrados de sesiones previas.
- ✅ `httpx==0.27.0` agregado a requirements (el scraper lo importaba sin declararlo);
  fix mid sesgado al máximo en `dolar_blue_bolivia.py` cuando CSS ya dio buy+sell.

### Backend / Web — cerrados en sesión 2026-07-07 (parte 2)
- ✅ RTE automático + push WS: `reports/services/rte_service.py` + señal
  `transaction_rte_check` — efectivo ≥ USD 1,000 equiv (conversión por tasa
  paralela si la divisa no es USD) crea `CashTransactionReport` y emite alerta
  vía `GlobalAlertService` (AlertLog + WS `alert_log` + email; PEP → severidad
  HIGH). Antes el modelo existía pero nada lo poblaba.
- ✅ Export CSV (ROADMAP v1.2): RTE mensual (`/reports/asfi/rte/download-csv/` y
  action del ViewSet) y Libro Diario (`daily-log/<id>/download-csv/`), UTF-8 con
  BOM; `GeneratedReport` acepta formato CSV (migración `reports/0004`); botón CSV
  en la card RTE de ReportsMain (web).
- ✅ `deducir_bob` con backtracking (`_find_exact_combo`): resuelve cambios exactos
  donde el greedy fallaba (p.ej. 50 Bs con 10×4+20×2), manteniendo la prioridad
  caja_chica→sueltos→fuertes.
- ✅ `_serialize_resultado` recursivo: el early-return sin divisa BOB ya no deja
  Decimals anidados (JSON-safe).
- ✅ P&L excluye ventas de tarjetas ANULADAS (`resumen_financiero` y precio
  promedio de tarjetas en `calcular_capital`).
- ✅ `numero_venta`: la colisión concurrente se absorbe con savepoint + retry
  (el `select_for_update` sobre aggregate no bloqueaba nada).
- ✅ Tests: 167 en verde (15 nuevos: `reports/tests/test_rte_service.py`,
  `capital/tests/test_fixes.py`, `tarjetas/tests/test_numero_venta.py`).

### Backend / Web — cerrados en sesión 2026-07-07 (parte 3)
- ✅ Rate limiting extendido (último ítem backend de ROADMAP v1.2): `@rate_limit`
  en login del ViewSet, verify-pin y confirm-two-factor (10/min — anti fuerza
  bruta de PIN/2FA), customers/search (30/min), tarjetas vender/lote/anular,
  capital generar/update-cash, rates update/calculate/refresh, y generación y
  descarga de reportes ASFI/gerenciales (10-20/min; openpyxl/reportlab son caros).
- ✅ Fix multi-tenant en `/customers/search/`: ahora filtra por la empresa del
  usuario (antes devolvía clientes de otras empresas y podía dar 500 por
  MultipleObjectsReturned al existir el mismo documento en dos empresas).
- ✅ Tests: 172 en verde (5 nuevos en `transactions/tests/test_rate_limits.py`).

### Backend / Web — pendientes
- Aplicar en el cluster los deployments con `CHANNEL_REDIS_URL` (kubectl desde Windows)
  y reconstruir imagen backend (nuevo requirement httpx + migración reports/0004).
- **Builds verificados 2026-07-08 (Linux)**: `Dockerfile` y `Dockerfile.prod` backend,
  `Dockerfile.prod` web (77 MB) y bundle JS release de la mobile compilan en verde.
  torch+cu128 se sacó de `requirements.txt` (nada lo importa; inflaba la imagen de
  5.5 a 15.7 GB) → ahora vive en `requirements-gpu.txt` para experimentos locales
  GPU. Imagen prod resultante: **4.64 GB**, smoke test `manage.py check` sin issues.
- **Fix crítico pre-rebuild**: el `.dockerignore` del 2026-07-07 excluía `snapshots/`
  creyéndola datos de runtime, pero es una app Django de INSTALLED_APPS — toda imagen
  construida con él entraba en crashloop (`ModuleNotFoundError: snapshots`). Corregido;
  detectado por smoke test dentro de la imagen, no por pytest (que corre sobre el
  código montado, no sobre la imagen).
- Gotcha build web en Linux: si `node_modules` vino de Windows, falta el binario
  nativo de rollup → `npm install @rollup/rollup-linux-x64-gnu --no-save`.

### Mobile (ver `docs/MOBILE.md`)
- **Hecho**: modo offline con cola + sincronización (`offlineQueue` + `useOfflineSync`);
  captura de PIN de operación en login; `src/config.ts` para la URL/puerto del backend;
  fix de `payload` fuera de scope en `TransactionScreen`; setup de Jest (mocks nativos).
- **Hecho (2026-07-07)**: timeout de red 15 s (`fetchWithTimeout` + AbortController);
  refresh JWT single-flight; componentes compartidos `LoadingView`/`ErrorBanner`/`EmptyState`
  (Reports y Alerts ya no tragan errores en silencio); promedio ponderado real en
  reportes (`src/utils/reportAggregation.ts`); 16 tests jest (api, offlineQueue,
  reportAggregation) + `tsc --noEmit` en verde.
- **Hecho (2026-07-07 parte 2)**: sync offline por reconexión real con
  `@react-native-community/netinfo` (listener en `useOfflineSync`, mock oficial
  en jest.setup); 18 tests + `tsc --noEmit` en verde. OJO: requiere rebuild
  nativo (`npm run android`) para que el autolinking incluya NetInfo.
- **Pendiente (requiere cuentas/nativo)**: notificaciones push Firebase (FCM);
  biometría para el PIN supervisor; soporte iOS completo (certificados + pods).

## Sesión 2026-07-07 (claude/audit-modernize)

Rama `claude/audit-modernize-2026-07-07` (repo git inicializado en esta sesión; sin remoto).

### Limpieza Celery (config muerta)
- Eliminado el `app.conf.beat_schedule = {...}` de `backend/core/celery.py` (~185 líneas
  muertas): verificado EMPÍRICAMENTE en el contenedor `kapitalya_backend` que el schedule
  efectivo son las 18 claves de `CELERY_BEAT_SCHEDULE` (`core/settings/base.py`) y ninguna
  de las de `celery.py`. Queda nota en el archivo. Fuente de verdad única: settings →
  DatabaseScheduler (django_celery_beat), sembrado por `analytics/0007`.
- Re-verificado post-limpieza: mismo schedule efectivo (18 entradas), señales de logging intactas.

### Apps huérfanas (análisis, NO se borró nada)
Hallazgo clave: los 10 directorios huérfanos del backend NO tienen NINGÚN `.py` fuente —
solo bytecode residual en `__pycache__` (gitignorado) y subdirs vacíos. Son cascarones de
apps cuyo código se eliminó en algún refactor. Git ni siquiera los versiona (dirs vacíos).
La auditoría contaba "24 apps" = 13 en INSTALLED_APPS + `core` + estos 10 (el "11" de
referencias posteriores probablemente incluye `core` o redondeo).

| App | Contenido real | Recomendación | Razón |
|---|---|---|---|
| `api` | solo bytecode (v1/v2 urls/views/serializers) | Eliminar | versionado de API abandonado; sin fuente ni registro |
| `audit` | bytecode + migrations aplicadas | Eliminar código; revisar tablas DB | fuente borrada; puede quedar tabla auditlog con datos |
| `compliance` | bytecode + migrations aplicadas | Eliminar código; revisar tablas DB | reglas/blacklist retiradas; posible tabla con datos |
| `hub_auth` | bytecode (middleware, tokens) | Eliminar | auth de hub del ecosistema; cero referencias |
| `imports` | bytecode (sheets_extract) | Eliminar | rol cubierto por `data_migration.auto_sync_sheets` |
| `legal` | bytecode CRUD | Eliminar | sin fuente ni uso |
| `reconciliation` | bytecode + migrations + tests | Eliminar código; revisar tablas DB | conciliación retirada; sin fuente |
| `search` | bytecode (views, bolivian_names) | Eliminar | sin fuente ni endpoint registrado |
| `shared` | bytecode (idempotency) | Eliminar | idempotencia vive en `core.middleware.IdempotencyMiddleware` |
| `webhooks` | bytecode + migrations + tests | Eliminar código; revisar tablas DB | entrega de webhooks retirada; sin fuente |

Verificado: ninguna está en `INSTALLED_APPS` ni es importada por `core` ni por las 13 apps
activas. "Eliminar" = borrar los cascarones del disco; para las 4 con migrations, revisar
antes `django_migrations` y sus tablas en la DB de producción (posibles datos históricos).

### Docker (consolidación)
- **BUG real corregido** en `docker-compose.prod.yml` y `docker-compose.tailscale.yml`:
  `daphne -b 0.0.0.0 -p 8007core.asgi:application` (faltaba el espacio) — el backend de
  producción no habría arrancado.
- **`.dockerignore` creados** (no existían): `backend/.dockerignore` (CRÍTICO: `COPY . .`
  horneaba `backend/.env` con secretos en la imagen; también excluye venv, __pycache__,
  media, logs, ml-models) y `frontend-web/.dockerignore` (node_modules, dist; los `.env*`
  de Vite NO se excluyen a propósito: el build lee `.env.production` y las VITE_ son públicas).
- `docker-compose.prod.yml`: healthcheck celery `$HOSTNAME` → `$$HOSTNAME` (antes lo
  interpolaba compose en el host y el ping fallaba siempre).
- `docker-compose.yml` (dev): healthcheck agregado al servicio backend (curl /health/).
- `version: '3.9'` obsoleto eliminado de los 3 composes (silencia warning de compose v2).
- `backend/Dockerfile.dev`: instalaba deps de MySQL (residuo de otro proyecto) → libpq;
  nota añadida: ningún compose lo referencia (el dev real usa `Dockerfile` + bind mount).
- Validado `docker compose config -q` en los 3 composes (prod/tailscale requieren
  `POSTGRES_PASSWORD` por el guard `:?` — correcto fail-fast).
- Documentado, NO cambiado (dudoso): defaults débiles `FLOWER_PASSWORD:-kapitalya2024` y
  `REDIS_PASSWORD:-kapitalya_redis[_2024]` en prod/tailscale — convertirlos a `:?` requerido
  rompería despliegues que dependan del default; decidir con el operador. `backend/Dockerfile`
  (base/dev) corre como root sin healthcheck: aceptable para dev con bind mount; no se le
  añadió HEALTHCHECK porque los workers celery comparten esa imagen y marcarían unhealthy.
- `.gitignore`: añadidos `celerybeat-schedule*`, `*.pid`, `.ruff_cache/`, `.ipynb_checkpoints/`.

## Convenciones

- Idioma es-BO; zona `America/La_Paz`; moneda base BOB; regulador ASFI.
- Secretos siempre en `.env` / Secrets, nunca hardcodeados.
- JWT: access en memoria (TTL 15 min), refresh en httpOnly cookie.
- Mobile: estilo de código propio con alineación multi-espacio (Prettier del preset
  `@react-native` marca esos archivos preexistentes; no reformatear en masa).
