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
│                                #   predictions, reports, capital, tarjetas, alerts,
│                                #   analytics, snapshots, data_migration, tenants
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
- **Deploy local hecho (2026-07-08)**: imágenes dev reconstruidas (httpx horneado),
  stack compose recreado, migraciones aplicadas (`tarjetas/0006-0007`,
  `inventory/0006`), smoke tests verdes (health/frontend/401/signup-pending/WS-403).
  Imágenes PROD construidas y tagueadas: `kapitalya/forex-erp-backend:v20260708`
  (4.64 GB, `manage.py check` OK) y `kapitalya/forex-erp-frontend:v20260708`
  (77 MB, non-root UID 101, nginx -t OK).
- **Pendiente SOLO Windows (sin acceso al cluster desde Linux)**:
  `docker save kapitalya/forex-erp-backend:v20260708 | ctr import` en workers 4/5
  (frontend: **v20260710**, en worker5), actualizar tag en deployment-backend/celery
  si aún apuntan a v20260605, y `kubectl apply -f infra/k8s/private/forex-erp/`
  (channels v20260708, frontend v20260710 + securityContext + CHANNEL_REDIS_URL).
  Las migraciones nuevas corren solas al arrancar el pod.
- **Incongruencias de datos en pantallas arregladas (2026-07-10/11)**: el usuario
  reportó datos faltantes/incongruentes en la web. Causas y fixes:
  1. `GananciaService.ganancia_por_divisa` esperaba SELL como BOB→divisa, pero el
     form web y TODOS los datos reales registran divisa→BOB (BUY y SELL) → Ganancias
     mostraba 0 ventas y pérdidas gigantes. Ahora agrega ambas orientaciones.
  2. `TransactionProfitLedger` tenía 0 filas (cargas históricas via bulk_create no
     pasan por `transactions/services.py` → ProfitEngine) → Analytics P&L vacío.
     Nuevo cmd `manage.py backfill_profit_ledger [--purge]`: simula WAC cronológico
     por (branch,divisa) y reconstruye `PnLDailySnapshot` (3779 filas, 327 días).
  3. `analytics_pnl` devolvía vacío para ADMIN sin branch → `PnLService.series_pnl/
     resumen_periodo` aceptan branch=None (agregado de todas las sucursales).
  4. `daily_summary.by_payment_method`: ordering default contaminaba el GROUP BY
     (1 grupo por fila) → `.order_by('payment_method')`.
  5. Latente: `currency_code` varchar(5) en 3 modelos de analytics no admitía
     USD_SMALL_BILLS/USD_CASH_LOOSE/PEN_COINS (el ProfitEngine vivo fallaba
     silencioso — fire-and-forget) → max_length=20 (migración `analytics/0008`)
     + clamp de `profit_pct` (DecimalField(8,4) desbordaba con costo ~0).
  Además: cuadratura día-a-día hoja↔BD → 11 tx faltantes insertadas (1 del 07-09
  con timestamp duplicado 12:00:00 que el loader dedupeó mal + 10 del 07-10
  posteriores a la carga); serie `paralelo_fisico_empresa` re-derivada y
  TrainingData refrescado. Total: 3779 tx hasta 2026-07-10.
  Barrido posterior ("¿falta algo más?"):
  6. `core/executive_dashboard.py::_get_capital` sumaba TODO el histórico de
     `CapitalComposicion` (56 días → Bs 14M fantasma, "56 branches") → ahora
     solo la composición más reciente por sucursal (distinct on branch).
  7. El mismo ordering-leak del GROUP BY estaba en `reports/generators.py`
     (by_type/by_currency/by_payment de los reportes gerenciales),
     `rates/ai_pricing.py` (contaba 1 BUY/1 SELL siempre) y
     `analytics/views.py` por_decision → `.order_by(<campo>)` explícito.
  NO-bugs verificados: caja/composición de hoy en 0 (la última caja manual del
  usuario es 2026-05-17 — dato que no existe en la fuente), Customers 0
  (histórico es INTERNA sin clientes), by_hour en hora local ✓ (TZ La_Paz).
- **Carga de pestañas secundarias de Google Sheets (2026-07-11)**: el export CSV
  solo trae la 1ª pestaña; el libro `KapitalyaRegistro2026` tiene 26 (bajar como
  XLSX con `exportMimeType=...spreadsheetml.sheet` + openpyxl en el contenedor).
  Cargado con marca `CARGA_GS_2026` (idempotente, en notas/descripcion):
  · "CATEGORIZACIÓN DE GASTOS" → `capital.Gasto`: +377 (feb2025→abr2026, mapeo
    de categorías libres→choices y medios→EFECTIVO/QR/TRANSFER/TARJETA; se
    saltaron 15 filas Ingresos/Depósitos que no son gastos). OJO: incluye
    transferencias personales/retiros (así lo lleva el dueño — negocio
    unipersonal); la ganancia neta baja en meses con gasto personal alto.
  · "Composicion Capital" → `CapitalSnapshot`: +52 balances totales
    (2026-01-02→07-10, tipo MANUAL, solo total_bob — sin desglose) → puebla
    Capital Timeline.
  · "Tarjetas" + "InventarioTarjetasAjustes" → 16 `TipoTarjeta` (Entel/Tigo/Viva,
    cortes 10-100 Bs, costo dist. real) + 16 `LoteCompra` iniciales con el stock
    del conteo físico 2026-05-01 (2.043 unidades, Bs 26.603 a costo).
  · `backfill_profit_ledger` ahora reconstruye snapshots para (fecha,branch) de
    ledger ∪ gastos (días con gasto sin tx) — re-corrido: 387 snapshots.
  · NO cargado (decisión): "Efectivo_BOB" (1.400 movs — diario de caja derivado;
    la app lleva el suyo propio), pestañas de resumen/dashboard (derivadas).
    Libro 2025: Control/TotalesDivisa ya cargados en sesiones previas
    (19 capital + 9 inventarios).
- **Módulo Ingresos Extra (2026-07-11)**: nuevo `capital.IngresoExtra` (migración
  `capital/0012`) + `IngresoExtraViewSet` en `/api/capital/ingresos/` (CRUD +
  `resumen/` por tipo) + pestaña "Ingresos" en la pantalla Capital (tabs ahora
  con `value` explícito 0-5; Snapshots=4, Caja=5) + IngresoDialog. Cargados los
  ingresos de la hoja: solo **5 reales** (Bs 1.250, mar-abr 2026) — las otras
  ~109 filas de "Ingresos extras" son plantilla vacía (solo defaults
  Efectivo/Sin observaciones). Fixes de paso: `CrearGastoSerializer` usaba
  `request.user.branch` (None para ADMIN → 500) → `_branch_para_registro()` con
  fallback a la sucursal principal de la empresa (aplicado a gasto e ingreso);
  el GastoDialog web enviaba `medio_pago: CASH/CHECK` y categorías
  SALARIOS/TECNOLOGIA/etc. que el backend rechaza con 400 → alineados a los
  choices reales (EFECTIVO/QR/TRANSFER/TARJETA; SUELDOS/BANCO/COMISIONES/…).
  Imagen frontend `v20260711` (manifest K8s actualizado).
- **UX móvil arreglada (2026-07-10)**: el usuario reportó fallas desde navegador de
  celular. 12 fixes en frontend-web: Tabs `scrollable` en 9 pantallas (Capital/
  Settings/Inventory/Reports/Tarjetas/UserAdmin/ReportsMain/Transactions/Analytics —
  antes las pestañas que no cabían quedaban inaccesibles), NotificationPanel
  `width: {xs:'100vw'}` (desbordaba 420px), TableContainer en BranchAnalytics y
  CompanyManagement (scroll horizontal de página), inputs ≥16px vía
  `@media (pointer: coarse)` en theme (zoom automático iOS), Dialogs con margen 10px
  y paddings compactos en xs (global en theme), PinDialog `inputMode: numeric`,
  SpeedDial con `safe-area-inset-bottom` + `pb` extra en contenido, SystemStatusBar
  visible en xs (solo dot), título AppBar `noWrap`, `100dvh` en spinners,
  manifest.json real ("Kapitalya ERP", theme #2563EB; era el placeholder CRA
  "React App") + borrado `public/index.html` muerto de CRA, Inter un solo `<link>`
  con preconnect en index.html (antes @import duplicado en index.css y theme.ts,
  bloqueado por la CSP de prod) + CSP de nginx.prod.conf permite
  fonts.googleapis.com/fonts.gstatic.com. Imagen frontend nueva:
  `kapitalya/forex-erp-frontend:v20260710` (manifest K8s ya actualizado).
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

## Sesión 2026-07-08 (production-ready)

Auditoría 3-frentes (backend/web/infra) + fixes aplicados. 172 tests backend,
tsc+build web y 18 tests mobile en verde post-cambios.

### Seguridad/multi-tenant (backend)
- **Signup público endurecido**: ya NO auto-une como CASHIER activo a la primera
  empresa; la cuenta queda `is_active=False` sin empresa hasta aprobación de un
  ADMIN (email y Google). El signup ya no emite tokens (`pending_approval`).
- **Tarjetas multi-tenant**: `TipoTarjeta.company` (FK, migración `tarjetas/0006`
  con backfill a la 1.ª empresa activa; unique ahora por company+operadora+denominación).
  Todo el módulo escopado: viewsets, profit, inventario, posición (caché por
  empresa+sucursal), KPIs, servicios (`company_id=`) y WS por grupo
  `tarjetas_inventario_<company_id>` (consumer y publisher).
- **`InventoryCard.company`** (migración `inventory/0006` + backfill): el viewset
  `/inventory/cards/` filtraba nada — cualquier usuario veía todas las empresas.
- **`_resolve_customer` escopado por empresa** (transactions): por `id` filtraba
  PII de clientes de otras empresas; `get_or_create` ahora por (company, documento).
- **`SECRET_KEY` fail-fast en production.py** (sin default; rechaza placeholders).
- **Consistencia `amount_to`**: el serializer valida `amount_to ≈ amount_from ×
  exchange_rate` (±1 BOB, solo flujo →BOB) — antes aceptaba cualquier total del cliente.
- **Guard anti-sobreventa FIFO** (`registrar_venta`): `restante > 0` post-bucle
  lanza dentro del atomic (dos ventas concurrentes de las últimas unidades).
- Apps huérfanas eliminadas del disco (10 cascarones sin `.py`, solo bytecode).

### Web
- WS tarjetas: token desde `getAccessToken()` (leía claves de storage que nadie
  escribía) + URL absoluta sin `/ws/ws/` duplicado — en prod nunca conectaba.
- Refresh al recargar usa `BASE_URL` (antes hardcodeaba `/api` e ignoraba
  `VITE_API_BASE_URL` → logout en cada F5 en deploy Tailscale).
- Signup/Login manejan `pending_approval` (Alert success/info).
- BranchAnalytics e InventoryMovements ya no disfrazan errores de red como
  "datos en cero".
- Pendiente (decisión de diseño): refresh token sigue en localStorage; moverlo a
  cookie httpOnly requiere cambio backend coordinado con la app móvil.

### Infra
- `docker-compose.prod.yml`: healthcheck redis autenticado (sin `-a` nunca llegaba
  a healthy y el stack no arrancaba), `REDIS_PASSWORD`/`FLOWER_PASSWORD` ahora
  requeridos `:?` (también en tailscale), flower con `--url_prefix`, `mem_limit`
  por servicio, y el frontend pasó a "publicador": copia el build al volumen en
  cada arranque (antes el volumen enmascaraba rebuilds para siempre).
- `nginx.prod.conf`: headers con `always` + repetidos en locations anidados (el
  de assets descartaba hasta el HSTS), `server_tokens off`, COOP/Permissions-Policy,
  TLS endurecido + ruta ACME, `/flower/` restringido a redes privadas,
  `server_name` unificado a `forex.kapitalya.com.bo` (tb. en `.env.production.example`).
- `start_prod.bat`: `--port 8007 --workers 2` (faltaba espacio), `serve -s dist`
  (no `build/`), y guard anti-placeholders; nuevo `scripts/preflight_prod.sh`.
- `frontend-web/Dockerfile` (K8s): `nginxinc/nginx-unprivileged:1.27-alpine` +
  security headers; `Dockerfile.prod` queda root a propósito (publicador de volumen).
- K8s: tags versionados `v20260708` en channels/frontend (`:latest` +
  `IfNotPresent` + `ctr import` nunca hace rollout), securityContext estándar en
  deployment-frontend, nota de backup para media hostPath (evidencia ASFI).

## Tasas para pronóstico — 3 series independientes (2026-07-10)

El forecasting ya no entrena una sola serie mezclada por par: hay **3 series reales
independientes** por par, distinguidas por `TrainingData.market`
(`web` | `competencia` | `empresa`) y por `ExchangeRate.market_type`:

| Serie | `market_type` (ExchangeRate) | Fuente real | Cobertura |
|-------|------------------------------|-------------|-----------|
| **web** | `paralelo_digital` | Dólar blue digital (dolarbluebolivia) | **solo USD/BOB** profundo (719 días 2024→2026); el resto de divisas no tiene historia digital |
| **competencia** | `paralelo_fisico_competencia` | CSV físico de mercado `tipos de cambio fisico mercado.csv` | 6 pares, ~1.2k–2k días 2023→2026 |
| **empresa** | `paralelo_fisico_empresa` | **Derivada de las transacciones reales** (mediana diaria buy/sell) | 6 pares, USD 326 días 2025→2026 |

Comandos (idempotentes, reproducibles):
```bash
python manage.py load_competition_rates --csv <ruta>   # competencia (reetiqueta + CSV)
python manage.py derive_empresa_rates --purge          # empresa desde transacciones
# TrainingData (las 3 series, agregación DIARIA — NO usar el slice crudo [:N]):
python manage.py shell -c "from predictions.tasks import update_training_data; \
  [update_training_data(p) for p in ['USD/BOB','EUR/BOB','BRL/BOB','ARS/BOB','PEN/BOB','CLP/BOB']]"
```

- `update_training_data(pair, market=None)` puebla las 3 series (agrega ExchangeRate a
  **1 punto/día** con `TruncDate`+`Avg` — evita que el ruido intradía del fx_engine/beat
  entierre la historia). La tarea diaria `train_all_prediction_models` ya la llama → las 3
  series se mantienen frescas solas.
- Pipeline/engine son market-aware: `ForexDataPipeline.build(pair, market=...)`,
  `ForexMLEngine.train_all(pair, market=...)` y `.predict(pair, market=...)` (default `web`
  = comportamiento previo). Verificado XGBoost OK en las 3 (USD/BOB MAPE web 0.35% /
  competencia 0.09% / empresa 0.15%).
- **Serving de los 3 pronósticos por API — HECHO (2026-07-10):** los artefactos ahora se
  keyean por market. `PredictionModel`/`EnsembleWeightHistory` tienen campo `market`
  (unique `(model_type, currency_pair, market)`, migración `predictions/0006`); los archivos
  de modelo llevan sufijo `__<market>` para ≠web (web sin sufijo → retrocompatible byte a
  byte). Helper `predictions/market_keys.py`. Enhebrado en los 4 forecasters
  (xgboost/arima/bilstm + prophet/lstm/ensemble legacy), engine (`_collect_base_predictions`,
  `_get_feature_importance`, `_backtesting_metrics`, `_invalidate_cache`, `cache_all_horizons`),
  ensemble (`compute_weights`/`_fallback_weight`/`conformalize`/meta-learner, filtran por
  `model__market`) y todas las tareas Celery (train/refresh/cache iteran las 3 series).
  **API:** `GET /api/predictions/forecast/<par>/?market=web|competencia|empresa` (default web;
  market inválido → 400). Verificado HTTP 200: USD/BOB web 10.38 / competencia 9.43 /
  empresa 11.41 — 3 pronósticos distintos, cada uno de su propio modelo.
  (ARIMA cae por `pmdarima` ausente — preexistente, degrada limpio; el ensemble combina
  los modelos disponibles.)

## Convenciones

- Idioma es-BO; zona `America/La_Paz`; moneda base BOB; regulador ASFI.
- Secretos siempre en `.env` / Secrets, nunca hardcodeados.
- JWT: access en memoria (TTL 15 min); refresh hoy en **localStorage** en la web
  (rotado + limpiado en logout) — migrarlo a cookie httpOnly sigue pendiente y
  requiere cambio backend coordinado con la app móvil (verificado 2026-07-08).
- Mobile: estilo de código propio con alineación multi-espacio (Prettier del preset
  `@react-native` marca esos archivos preexistentes; no reformatear en masa).
