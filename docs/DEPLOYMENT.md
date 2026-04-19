# Kapitalya ERP — Deployment

---

## Desarrollo local (sin Docker)

### Prerrequisitos
- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- Node.js 18+

### 1. Backend

```bash
cd backend

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus valores locales

# Crear base de datos
createdb forex_erp_dev

# Migraciones
python manage.py migrate

# Crear superusuario
python manage.py createsuperuser

# Datos de ejemplo (opcional)
python scripts/seed_kapitalya.py

# Iniciar servidor de desarrollo
python manage.py runserver 0.0.0.0:8000
```
uvicorn core.asgi:application --host 0.0.0.0 --port 8000 --reload 

### 2. Celery (en terminales separadas)

```bash
# Worker
celery -A core worker -l info

# Beat (tareas periódicas)
celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### 3. Frontend Web

```bash
cd frontend-web
npm install
npm run dev     # Vite dev server → http://localhost:3000
```

### 4. App Móvil (Android)

```bash
cd frontend-mobile/ForexERPMobile
npm install

# Iniciar Metro bundler
npm start

# En otra terminal (con emulador activo)
npm run android
```

---

## Desarrollo con Docker

```bash
# Levantar todos los servicios
docker compose up -d

# Ver logs
docker compose logs -f backend
docker compose logs -f celery

# Ejecutar migraciones
docker compose exec backend python manage.py migrate

# Crear superusuario
docker compose exec backend python manage.py createsuperuser

# Detener
docker compose down
```

**Servicios disponibles:**
| Servicio | URL/Puerto |
|----------|-----------|
| Backend API | http://localhost:8000 |
| Frontend Web | http://localhost:3000 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |
| Django Admin | http://localhost:8000/admin |

---

## Variables de entorno

Crear `backend/.env` con las siguientes variables:

```bash
# ── Seguridad ──────────────────────────────────────────────────
SECRET_KEY=genera-una-clave-segura-con-openssl-rand-base64-50
DEBUG=False

# ── Host ───────────────────────────────────────────────────────
ALLOWED_HOSTS=localhost,127.0.0.1,tu-dominio.com
CORS_ALLOWED_ORIGINS=https://tu-frontend.com,http://localhost:3000

# ── Base de datos ───────────────────────────────────────────────
DB_ENGINE=django.db.backends.postgresql
DB_NAME=forex_erp
DB_USER=forex_user
DB_PASSWORD=password-seguro-aqui
DB_HOST=postgres          # 'localhost' en dev local, 'postgres' en Docker
DB_PORT=5432

# ── Redis / Celery ──────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
CHANNEL_LAYERS_HOST=redis

# ── Archivos estáticos ──────────────────────────────────────────
STATIC_ROOT=/app/staticfiles
MEDIA_ROOT=/app/media
```

**Generar SECRET_KEY seguro:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## Producción

### Configuración adicional

```bash
# Usar settings de producción
export DJANGO_SETTINGS_MODULE=core.settings.production

# Colectar archivos estáticos
python manage.py collectstatic --no-input

# Verificar configuración
python manage.py check --deploy
```

**`core/settings/production.py` agrega:**
- `SECURE_SSL_REDIRECT = True`
- `SESSION_COOKIE_SECURE = True`
- `CSRF_COOKIE_SECURE = True`
- `CHANNEL_LAYERS` → Redis (no InMemory)
- `CACHES` → Redis cache backend

### Nginx (ejemplo)

```nginx
server {
    listen 80;
    server_name tu-dominio.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name tu-dominio.com;

    ssl_certificate     /etc/ssl/certs/kapitalya.crt;
    ssl_certificate_key /etc/ssl/private/kapitalya.key;

    # API y WebSocket
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Frontend estático
    location / {
        root /var/www/kapitalya;
        try_files $uri /index.html;
    }

    # Archivos de media
    location /media/ {
        alias /app/media/;
    }
}
```

### Gunicorn con workers ASGI (para WebSocket)

```bash
# Para soporte WebSocket real en producción, usar Daphne o Uvicorn
daphne -b 0.0.0.0 -p 8000 core.asgi:application

# O con Uvicorn workers en Gunicorn
gunicorn core.asgi:application \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --workers 4 \
  --timeout 120
```

---

## Migraciones

```bash
# Ver estado de migraciones
python manage.py showmigrations

# Crear nuevas migraciones tras cambios en modelos
python manage.py makemigrations

# Aplicar migraciones
python manage.py migrate

# Revertir última migración de una app
python manage.py migrate inventory 0001
```

---

## Backup y restauración

```bash
# Backup de base de datos
python manage.py dbbackup  # si django-dbbackup está configurado

# O con pg_dump directo
pg_dump -h localhost -U forex_user forex_erp > backup_$(date +%Y%m%d).sql

# Restaurar
psql -h localhost -U forex_user forex_erp < backup_20260407.sql

# Backup de archivos media (modelos ML, PDFs)
tar -czf media_backup_$(date +%Y%m%d).tar.gz backend/media/
```

---

## Monitoreo

```bash
# Estado de tareas Celery
celery -A core inspect active
celery -A core inspect scheduled

# Flower (UI para Celery)
pip install flower
celery -A core flower --port=5555
# → http://localhost:5555

# Logs de Django
tail -f logs/django.log
tail -f logs/celery.log
```

---

## Solución de problemas comunes

| Problema | Solución |
|----------|---------|
| `django.db.utils.OperationalError: could not connect to server` | Verificar PostgreSQL corriendo y credenciales en `.env` |
| `redis.exceptions.ConnectionError` | Verificar Redis corriendo en puerto 6379 |
| `ModuleNotFoundError: No module named 'prophet'` | `pip install prophet` — requiere pystan |
| Migraciones de `capital`/`tarjetas` no aplicadas | `python manage.py migrate capital && python manage.py migrate tarjetas` |
| WebSocket no conecta en producción | Nginx debe tener configuración `Upgrade` para `/ws/` |
| LSTM falla por memoria | Desactivar modelo LSTM: `PredictionModel.objects.filter(model_type='LSTM').update(is_active=False)` |
