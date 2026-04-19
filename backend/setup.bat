@echo off
echo ============================================
echo  Kapitalya ERP — Setup y primer arranque
echo ============================================
echo.

cd /d %~dp0

echo [1/5] Aplicando migraciones...
python manage.py migrate --run-syncdb
if errorlevel 1 (echo ERROR en migrate & pause & exit /b 1)

echo.
echo [2/5] Cargando datos iniciales (currencies, branches, rates, admin)...
python manage.py seed_data
if errorlevel 1 (echo ERROR en seed_data & pause & exit /b 1)

echo.
echo [3/5] Creando directorios de media...
if not exist media\reports\asfi mkdir media\reports\asfi
if not exist media\reports\management mkdir media\reports\management
if not exist media\transaction_documents mkdir media\transaction_documents

echo.
echo [4/5] Colectando archivos estáticos...
python manage.py collectstatic --noinput 2>nul

echo.
echo [5/5] Verificando configuracion...
python manage.py check --deploy 2>nul || python manage.py check
if errorlevel 1 (echo ADVERTENCIA: hay checks de configuracion & echo Puede ser normal en desarrollo)

echo.
echo ============================================
echo  Setup completo!
echo.
echo  Para iniciar el servidor:
echo    python manage.py runserver 0.0.0.0:8000
echo.
echo  Credenciales por defecto:
echo    Admin:  admin / admin1234
echo    Cajero: cajero1 / cajero1234
echo.
echo  Endpoints principales:
echo    POST /api/auth/login/
echo    GET  /api/rates/exchange-rates/current/
echo    POST /api/transactions/
echo    GET  /api/rates/history/?currency=USD^&days=30
echo    POST /api/import/excel/
echo    GET  /api/reports/management/pnl/?date_from=2026-01-01^&date_to=2026-04-07
echo ============================================
pause
