@echo off
echo Iniciando Kapitalya en modo PRODUCCION...
cd frontend-web && npm run build && cd ..
cd backend
venv\Scripts\activate
set DJANGO_SETTINGS_MODULE=core.settings.production
python manage.py migrate --noinput
python manage.py collectstatic --noinput
cd ..
start "Backend PROD" cmd /k "cd backend && venv\Scripts\activate && set DJANGO_SETTINGS_MODULE=core.settings.production && uvicorn core.asgi:application --host 0.0.0.0 --port 8007--workers 2 --log-level warning"
timeout /t 3 /nobreak >nul
start "Frontend PROD" cmd /k "cd frontend-web && npx serve -s build -l 3000"
pause