@echo off
echo Iniciando Kapitalya en modo PRODUCCION...

REM Guard anti-placeholders: no arrancar produccion con SECRET_KEY/DB_PASSWORD de plantilla
findstr /C:"CAMBIAR_" backend\.env.production >nul 2>&1
if %errorlevel%==0 (
    echo ERROR: backend\.env.production contiene placeholders CAMBIAR_*.
    echo Configura secretos reales antes de arrancar produccion.
    exit /b 1
)

cd frontend-web && npm run build && cd ..
cd backend
venv\Scripts\activate
set DJANGO_SETTINGS_MODULE=core.settings.production
python manage.py migrate --noinput
python manage.py collectstatic --noinput
cd ..
start "Backend PROD" cmd /k "cd backend && venv\Scripts\activate && set DJANGO_SETTINGS_MODULE=core.settings.production && uvicorn core.asgi:application --host 0.0.0.0 --port 8007 --workers 2 --log-level warning"
timeout /t 3 /nobreak >nul
REM Vite genera dist/ (no build/)
start "Frontend PROD" cmd /k "cd frontend-web && npx serve -s dist -l 3000"
pause
