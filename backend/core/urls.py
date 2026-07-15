# core/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenBlacklistView
from users.views import ForexTokenView, SignupView, GoogleAuthView, dashboard_stats
from transactions.views import TransactionViewSet, CustomerViewSet
from core.health import health_check, readiness_check, metrics_view, api_health, api_health_detailed
from core.frontend_error_log import receive_frontend_error
from core.exceptions import handler_404, handler_500
from core.maintenance_views import (
    maintenance_status, maintenance_toggle,
    maintenance_clear_cache, maintenance_recalculate,
)
from core.import_views import ExcelImportView
from core.executive_dashboard import ExecutiveDashboardView
from core.dashboard_charts import DashboardChartsView

# Router para transacciones
tx_router = DefaultRouter()
tx_router.register(r'', TransactionViewSet, basename='transactions')

# Router para clientes
customer_router = DefaultRouter()
customer_router.register(r'', CustomerViewSet, basename='customers')

urlpatterns = [
    path('admin/', admin.site.urls),

    # ── Health & monitoring ──────────────────────────────────────────────────
    path('health/',                  health_check,        name='health'),
    path('health/ready/',            readiness_check,     name='readiness'),
    path('health/metrics/',          metrics_view,        name='metrics'),
    path('api/health/',              api_health,          name='api-health'),
    path('api/health/detailed/',     api_health_detailed, name='api-health-detailed'),

    # Frontend error logging
    path('api/logs/frontend-error/', receive_frontend_error, name='frontend-error-log'),

    # Auth
    path('api/auth/signup/',  SignupView.as_view(),       name='auth_signup'),
    path('api/auth/login/',   ForexTokenView.as_view(),   name='token_obtain_pair'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/logout/',  TokenBlacklistView.as_view(), name='token_blacklist'),
    path('api/auth/google/',  GoogleAuthView.as_view(),   name='auth_google'),

    # Tenants (companies, subscriptions)
    path('api/tenants/',       include('tenants.urls')),

    # Users
    path('api/users/',         include('users.urls')),

    # Rates
    path('api/rates/',         include('rates.urls')),

    # Transactions y Customers separados
    path('api/transactions/',  include(tx_router.urls)),
    path('api/customers/',     include(customer_router.urls)),

    # Inventory
    path('api/inventory/',     include('inventory.urls')),

    # Predictions
    path('api/predictions/',   include('predictions.urls')),

    # Indicadores macroeconómicos Bolivia
    path('api/macro/',         include('macro.urls')),

    # Reports
    path('api/reports/',       include('reports.urls')),

    # Dashboard
    path('api/dashboard/stats/',     dashboard_stats,                   name='dashboard-stats'),
    path('api/dashboard/charts/',    DashboardChartsView.as_view(),     name='dashboard-charts'),
    path('api/dashboard/executive/', ExecutiveDashboardView.as_view(),  name='dashboard-executive'),

    # Tarjetas (phone cards)
    path('api/tarjetas/', include('tarjetas.urls')),

    # Capital (gastos + snapshots + ganancias + caja manual)
    path('api/capital/', include('capital.urls')),

    # Analytics (P&L, exposición, spread, decisiones)
    path('api/analytics/', include('analytics.urls')),

    # Snapshots del sistema
    path('api/snapshots/', include('snapshots.urls')),

    # Alertas del sistema (log persistente + reconocimiento)
    path('api/alerts/', include('alerts.urls')),

    # AI Business Intelligence
    path('api/ai/',        include('analytics.ai_urls')),

    # Migración de datos desde Google Sheets
    path('api/migration/', include('data_migration.urls')),

    # Importación de datos desde Excel
    path('api/import/excel/',            ExcelImportView.as_view(), name='import-excel'),

    # Mantenimiento del sistema
    path('api/maintenance/',             maintenance_status,      name='maintenance-status'),
    path('api/maintenance/toggle/',      maintenance_toggle,      name='maintenance-toggle'),
    path('api/maintenance/clear-cache/', maintenance_clear_cache, name='maintenance-clear-cache'),
    path('api/maintenance/recalculate/', maintenance_recalculate, name='maintenance-recalculate'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# ── Handlers globales de error ────────────────────────────────────────────────
handler404 = 'core.exceptions.handler_404'
handler500 = 'core.exceptions.handler_500'