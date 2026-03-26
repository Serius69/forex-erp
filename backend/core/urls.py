# core/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework.routers import DefaultRouter
from users.views import ForexTokenView, dashboard_stats
from transactions.views import TransactionViewSet, CustomerViewSet

# Router para transacciones
tx_router = DefaultRouter()
tx_router.register(r'', TransactionViewSet, basename='transactions')

# Router para clientes
customer_router = DefaultRouter()
customer_router.register(r'', CustomerViewSet, basename='customers')

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth
    path('api/auth/login/',    ForexTokenView.as_view(),   name='token_obtain_pair'),
    path('api/auth/refresh/',  TokenRefreshView.as_view(), name='token_refresh'),

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

    # Reports
    path('api/reports/',       include('reports.urls')),

    # Dashboard
    path('api/dashboard/stats/', dashboard_stats, name='dashboard-stats'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)