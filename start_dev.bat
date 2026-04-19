@echo off
echo Iniciando Kapitalya en modo DESARROLLO...
start "Backend DEV" cmd /k "cd /d e:\data\forex-erp\backend && set "DJANGO_SETTINGS_MODULE=core.settings.development" && venv\Scripts\activate && python manage.py migrate && uvicorn core.asgi:application --host 0.0.0.0 --port 8000 --reload"
timeout /t 3 /nobreak >nul
start "Frontend DEV" cmd /k "cd frontend-web && npm start"
echo Backend: http://localhost:8000/api
echo Frontend: http://localhost:3000
pause