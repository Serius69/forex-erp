# inventory/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CurrencyInventoryViewSet, InventoryMovementViewSet,
    InventoryTransferViewSet, InventoryAlertViewSet, InventoryCardViewSet,
)

router = DefaultRouter()
router.register(r'stock',     CurrencyInventoryViewSet,  basename='inventory')
router.register(r'movements', InventoryMovementViewSet,  basename='movements')
router.register(r'transfers', InventoryTransferViewSet,  basename='transfers')
router.register(r'alerts',    InventoryAlertViewSet,     basename='alerts')
router.register(r'cards',     InventoryCardViewSet,      basename='cards')

urlpatterns = [
    path('', include(router.urls)),
]
