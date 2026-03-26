# inventory/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CurrencyInventoryViewSet, InventoryTransferViewSet, InventoryAlertViewSet

router = DefaultRouter()
router.register(r'stock',     CurrencyInventoryViewSet, basename='inventory')
router.register(r'transfers', InventoryTransferViewSet, basename='transfers')
router.register(r'alerts',    InventoryAlertViewSet,    basename='alerts')

urlpatterns = [
    path('', include(router.urls)),
]
