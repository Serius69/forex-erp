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

### Backend / Web (ver `docs/ROADMAP.md` — v1.2 Q2 2026)
- WebSocket producción: cambiar `InMemoryChannelLayer` → Redis Channel Layer.
- `predictions/ml_service.py`: `fillna(method='ffill')` deprecado en pandas 2.x → `.ffill()`.
- Poblar `django_celery_beat` (schedules) vía data migration para instalación limpia.
- Tests backend: cobertura < 20% (priorizar Transaction/Capital/Ganancia/Tarjeta services).
- Web: integrar Capital.tsx / Ganancias.tsx con `/api/capital/`; selector de sucursal ADMIN;
  exportación de reportes desde UI; notificaciones WS de bajo stock / RTE.
- `Transaction.profit_margin` usa spread fijo 0.3% en vez del spread real.
> Nota: al momento de esta sesión el backend/web tienen cambios locales sin commitear
> (trabajo en curso del autor); no se tocaron para evitar entrelazar diffs.

### Mobile (ver `docs/MOBILE.md`)
- **Hecho**: modo offline con cola + sincronización (`offlineQueue` + `useOfflineSync`);
  captura de PIN de operación en login; `src/config.ts` para la URL/puerto del backend;
  fix de `payload` fuera de scope en `TransactionScreen`; setup de Jest (mocks nativos).
- **Pendiente (requiere cuentas/nativo)**: notificaciones push Firebase (FCM);
  biometría para el PIN supervisor; soporte iOS completo (certificados + pods).

## Convenciones

- Idioma es-BO; zona `America/La_Paz`; moneda base BOB; regulador ASFI.
- Secretos siempre en `.env` / Secrets, nunca hardcodeados.
- JWT: access en memoria (TTL 15 min), refresh en httpOnly cookie.
- Mobile: estilo de código propio con alineación multi-espacio (Prettier del preset
  `@react-native` marca esos archivos preexistentes; no reformatear en masa).
