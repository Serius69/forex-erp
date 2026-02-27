# Forex ERP — Casa de Cambio de Divisas

Sistema integral ERP/CRM para gestión de casa de cambio: transacciones, inventario, tasas, predicciones ML y reportes financieros.

---

## Arquitectura

```
forex-erp/
├── backend/
│   ├── core/                  # Configuración Django, Celery, Backup
│   ├── predictions/           # Modelos ML, API de predicciones
│   ├── transactions/          # Transacciones y clientes
│   ├── inventory/             # Control de stock y alertas
│   ├── reports/               # Generación de reportes
│   ├── users/                 # Autenticación y permisos
│   ├── rates/                 # Gestión de tasas de cambio
│   └── api/                   # Rutas y documentación
├── frontend/
│   └── src/
│       └── components/        # Dashboard, TransactionForm
├── mobile/
│   └── src/
│       └── screens/           # HomeScreen
└── ml-models/                 # Modelos entrenados serializados
```

### Stack Tecnológico

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11, Django 4.x, Django REST Framework |
| Base de datos | PostgreSQL 15 |
| Cache | Redis 7 |
| Tareas asíncronas | Celery + Celery Beat |
| Websockets | Django Channels |
| ML | Prophet, scikit-learn, TensorFlow |
| Frontend | React 18, Material-UI |
| App Móvil | React Native |
| Infraestructura | Docker, Nginx, AWS S3 |

---

## Desarrollo

### Requisitos

- Docker y Docker Compose
- Python 3.11+
- Node.js 18+

### 1. Clonar y configurar variables de entorno

```bash
git clone https://github.com/tu-org/forex-erp.git
cd forex-erp
cp .env.example .env
# Editar .env con tus valores locales
```

### 2. Levantar servicios con Docker

```bash
docker compose up -d postgres redis
```

### 3. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### 4. Workers Celery (en terminales separadas)

```bash
# Worker
celery -A core worker -l info

# Scheduler
celery -A core beat -l info
```

### 5. Frontend

```bash
cd frontend
npm install
npm start                        # http://localhost:3000
```

### 6. App Móvil

```bash
cd mobile
npm install
npx react-native run-android     # o run-ios
```

---

## Producción

### 1. Variables de entorno requeridas

```env
DB_PASSWORD=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
BACKUP_BUCKET=
DJANGO_SECRET_KEY=
DJANGO_ALLOWED_HOSTS=
```

### 2. Levantar stack completo

```bash
docker compose up -d
```

Esto levanta: `postgres`, `redis`, `backend` (gunicorn), `celery`, `celery-beat`, `frontend` y `nginx`.

### 3. Migraciones y archivos estáticos

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py collectstatic --noinput
```

### 4. Entrenar modelos ML (primera vez)

```bash
docker compose exec backend python manage.py shell -c \
  "from predictions.tasks import train_models; train_models()"
```

### Tareas programadas automáticas (Celery Beat)

| Tarea | Frecuencia |
|---|---|
| Actualizar tasas oficiales (BCB) | Cada 30 min |
| Entrenar modelos de predicción | Diario 2:00 AM |
| Generar reporte diario | Diario 11:30 PM |
| Verificar niveles de inventario | Cada 15 min |
| Backup de base de datos | Cada 6 horas |

---

## API

Documentación completa disponible en `/api/docs/` (Swagger) una vez levantado el backend.

Endpoints principales:

```
POST /api/auth/login/
GET  /api/rates/current/
POST /api/transactions/
GET  /api/transactions/daily-summary/
GET  /api/predictions/current/
POST /api/predictions/train/
GET  /api/reports/daily/
```