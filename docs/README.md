# Kapitalya ERP — Documentación

Sistema ERP para casas de cambio bolivianas. Django REST + React + React Native + ML.

---

## Índice de documentación

| Documento | Descripción |
|-----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Arquitectura general, diagrama de componentes, flujo de datos |
| [BACKEND.md](BACKEND.md) | Apps Django, modelos, servicios, Celery tasks |
| [FRONTEND.md](FRONTEND.md) | React web, Redux, componentes clave |
| [MOBILE.md](MOBILE.md) | React Native, pantallas, navegación |
| [API.md](API.md) | Endpoints REST, payloads, ejemplos |
| [ML_MODELS.md](ML_MODELS.md) | Prophet, LSTM, Ensemble — entrenamiento y predicción |
| [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) | Cómo funciona el negocio: spreads, capital, FIFO, ASFI |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Docker, desarrollo local, producción, variables de entorno |
| [ROADMAP.md](ROADMAP.md) | Deuda técnica, próximas versiones, escalabilidad |

---

## Inicio rápido

```bash
# 1. Clonar y configurar entorno
cp backend/.env.example backend/.env
# Editar .env con tus credenciales

# 2. Levantar con Docker
docker compose up -d
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser

# 3. Acceder
# API:      http://localhost:8007/api
# Admin:    http://localhost:8007/admin
# Frontend: http://localhost:3000
```

## Apps del sistema

| App | Dominio |
|-----|---------|
| `users` | Usuarios, sucursales, autenticación, 2FA |
| `rates` | Tasas de cambio, márgenes, WebSocket live |
| `transactions` | Compra/venta divisas, clientes, comprobantes |
| `inventory` | Stock por sucursal, WAC, transferencias |
| `predictions` | ML: Prophet + LSTM + Ensemble |
| `reports` | ASFI: RTE, ROUE, PEP, Libro Diario |
| `capital` | Gastos, snapshots, P&G consolidado |
| `tarjetas` | Tarjetas prepago con costeo FIFO |
