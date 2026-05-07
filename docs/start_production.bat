@echo off
cd E:\data\forex-erp\backend
call venv\Scripts\activate
set DJANGO_SETTINGS_MODULE=core.settings.production
set DJANGO_SECRET_KEY=tu-clave-segura-de-50-chars
set DB_NAME=forex_erp
set DB_USER=postgres
set DB_PASSWORD=tu-password-seguro
set REDIS_URL=redis://127.0.0.1:6379/0

:: Migrar y colectar estáticos
python manage.py migrate --noinput
python manage.py collectstatic --noinput

:: Arrancar uvicorn con workers
uvicorn core.asgi:application ^
  --host 0.0.0.0 ^
  --port 8007^
  --workers 2 ^
  --loop uvloop ^
  --log-level warning ^
  --access-log