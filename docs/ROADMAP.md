# Kapitalya ERP — Roadmap

Estado actual del sistema y plan de evolución hacia un producto SaaS escalable.

---

## Estado actual (v1.1 — Abril 2026)

### Completado ✅
- [x] Autenticación JWT con 2FA y PIN supervisor
- [x] Gestión multi-sucursal
- [x] Transacciones BUY/SELL con inventario thread-safe (select_for_update)
- [x] Inventario con WAC (Costo Promedio Ponderado)
- [x] Transferencias inter-sucursal
- [x] Modelos ML: Prophet + LSTM + Ensemble
- [x] Reportes ASFI: RTE, ROUE, PEP, Libro Diario
- [x] Capital en tiempo real (divisas + tarjetas + efectivo)
- [x] Gastos operativos categorizados
- [x] P&G consolidado (divisas + tarjetas − gastos)
- [x] Tarjetas prepago con costeo FIFO exacto
- [x] Snapshots de capital
- [x] WebSocket para tasas en tiempo real
- [x] Comprobantes PDF con código QR
- [x] App móvil React Native (Android)
- [x] Frontend web React + Redux

---

## Prioridad Alta — v1.2 (Q2 2026)

### Backend
- [ ] **Corregir `docker-compose.yml`**: servicio `frontend` apunta a `./frontend` pero el directorio real es `./frontend-web`. Corregir path.
- [ ] **Canales WebSocket en producción**: cambiar `InMemoryChannelLayer` a Redis Channel Layer en settings de producción.
- [ ] **Endpoint `/users/me/`**: verificar que existe y está correctamente registrado en `users/urls.py` (referenciado en la app móvil).
- [ ] **Endpoint `/customers/search/`**: ya existe como `@action` en `CustomerViewSet`, pero la app móvil lo llama como `/customers/search/?document=`. Confirmar URL correcta.
- [ ] **Tests unitarios**: cobertura actual estimada < 20%. Priorizar `TransactionService`, `CapitalService`, `GananciaService`, `TarjetaService`.
- [ ] **Rate limiting en endpoints sensibles**: extender más allá de `/transactions/`.
- [ ] **Celery Beat schedules**: poblar `django_celery_beat` via data migration para que los schedules existan en instalación limpia.

### Frontend Web
- [ ] **Módulo de capital integrado**: conectar `Capital.tsx` y `Ganancias.tsx` con los nuevos endpoints `/api/capital/`.
- [ ] **Selector de sucursal** para usuarios ADMIN (actualmente solo ve su propia sucursal).
- [ ] **Exportación de reportes** desde UI sin ir al admin de Django.
- [ ] **Notificaciones en tiempo real** via WebSocket (alertas de bajo stock, RTE generados).

### Mobile
- [ ] **Modo offline básico**: guardar transacciones localmente cuando no hay red y sincronizar al reconectar.
- [ ] **Notificaciones push** via Firebase Cloud Messaging.
- [ ] **Soporte iOS**: configurar certificados y pods.

---

## Prioridad Media — v1.3 (Q3 2026)

### Multitenancy (múltiples empresas)
- [ ] Separación de datos por `Company` / `Organization`
- [ ] Subdominios por empresa (`empresa1.kapitalya.com`)
- [ ] Billing y límites por plan (transacciones/mes, sucursales, usuarios)
- [ ] Panel super-admin para gestión de clientes SaaS

### ML y Analytics
- [ ] **Modelo ARIMA**: como alternativa ligera cuando no hay GPU
- [ ] **Reentrenamiento incremental**: sin reentrenar desde cero (online learning)
- [ ] **Dashboard de métricas ML**: MAE, MAPE histórico por modelo y par
- [ ] **Alertas de anomalías**: detectar tasas fuera de rango esperado
- [ ] **Predicción de demanda**: cuánta divisa se necesitará por día/hora

### Reportes avanzados
- [ ] **Reporte de conciliación**: comparar inventario teórico vs. real
- [ ] **Análisis de clientes**: segmentación, frecuencia, ticket promedio
- [ ] **Proyección de flujo de caja** a 30/60/90 días basada en histórico
- [ ] **Dashboard ASFI**: estado de cumplimiento consolidado

---

## Prioridad Baja — v2.0 (Q4 2026)

### Escalabilidad
- [ ] **Read replicas**: queries de reporting en replica secundaria
- [ ] **Particionado de tablas**: `Transaction` e `InventoryMovement` por año
- [ ] **Cache de tasas en Redis**: reducir queries a BD en endpoints de tasas
- [ ] **CDN para archivos estáticos y media** (PDFs, modelos ML)
- [ ] **Background export de reportes**: grandes reportes generados async y notificados

### Integraciones
- [ ] **Integración BCB API**: actualización automática de tasas oficiales
- [ ] **Integración bancaria**: conciliación automática de transferencias
- [ ] **Firma digital de comprobantes** (cumplimiento legal)
- [ ] **API pública**: para integración con sistemas de terceros
- [ ] **Webhooks**: notificar eventos a sistemas externos

### Operaciones
- [ ] **CI/CD**: GitHub Actions para tests + deploy automático
- [ ] **Monitoreo APM**: Sentry para errores, Prometheus + Grafana para métricas
- [ ] **Backup automático**: S3 / Backblaze para BD + media
- [ ] **Health checks**: endpoint `/health/` para load balancer
- [ ] **Logs estructurados**: JSON logs indexables en ELK / Loki

---

## Deuda técnica identificada

| Área | Problema | Impacto | Prioridad |
|------|---------|---------|-----------|
| `docker-compose.yml` | Path `./frontend` debería ser `./frontend-web` | Build falla en CI | Alta |
| `settings/base.py` | `CHANNEL_LAYERS` usa InMemoryChannelLayer | No escala en producción | Alta |
| `Transaction.profit_margin` | Usa spread fijo 0.3% en lugar del spread real | Estimación incorrecta | Media |
| `predictions/ml_service.py` | `fillna(method='ffill')` deprecado en pandas 2.x | Warning en producción | Media |
| Tests | Cobertura < 20% | Regresiones no detectadas | Alta |
| `UserActivity.ip_address` | Sin validación de IP privada/pública | Logs incorrectos en reverse proxy | Baja |

---

## Arquitectura objetivo (v2.0)

```
                    ┌──────────────────┐
                    │   CDN / Cloudflare│
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Nginx / Load   │
                    │   Balancer       │
                    └────┬─────────────┘
                 ┌───────┴───────┐
          ┌──────▼──────┐ ┌──────▼──────┐
          │  Backend 1  │ │  Backend 2  │  (horizontal scale)
          └──────┬──────┘ └──────┬──────┘
                 └───────┬───────┘
              ┌──────────┴──────────┐
       ┌──────▼──────┐       ┌──────▼──────┐
       │  PostgreSQL │       │    Redis     │
       │  (primary) │       │  (cluster)   │
       └──────┬──────┘       └─────────────┘
       ┌──────▼──────┐
       │  PostgreSQL │  (read replica para reportes)
       └─────────────┘
```
