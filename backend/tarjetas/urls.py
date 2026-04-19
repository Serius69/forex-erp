from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    TipoTarjetaViewSet,
    LoteCompraViewSet,
    VentaTarjetaViewSet,
    MovimientoTarjetaViewSet,
    ComprarTarjetaView,
    VenderTarjetaView,
    InventarioTarjetaView,
)

router = DefaultRouter()
router.register(r'tipos',       TipoTarjetaViewSet,      basename='tipos-tarjeta')
router.register(r'lotes',       LoteCompraViewSet,       basename='lotes-tarjeta')
router.register(r'ventas',      VentaTarjetaViewSet,     basename='ventas-tarjeta')
router.register(r'movimientos', MovimientoTarjetaViewSet, basename='movimientos-tarjeta')

urlpatterns = [
    # ── Endpoints principales (especificados en el módulo) ────────────────────
    #   POST /api/tarjetas/comprar/    → registra compra de lote
    #   POST /api/tarjetas/vender/     → registra venta a cliente (FIFO)
    #   GET  /api/tarjetas/inventario/ → snapshot de stock + P&L
    path('comprar/',    ComprarTarjetaView.as_view(),   name='tarjetas-comprar'),
    path('vender/',     VenderTarjetaView.as_view(),    name='tarjetas-vender'),
    path('inventario/', InventarioTarjetaView.as_view(), name='tarjetas-inventario'),

    # ── Router ViewSets (CRUD + acciones adicionales) ─────────────────────────
    #   GET /api/tarjetas/tipos/                    → catálogo de tipos
    #   GET /api/tarjetas/lotes/                    → historial de lotes
    #   GET /api/tarjetas/ventas/                   → historial de ventas
    #   GET /api/tarjetas/ventas/resumen/           → resumen por período
    #   GET /api/tarjetas/movimientos/              → libro diario unificado
    #   GET /api/tarjetas/movimientos/profit/       → P&L con margen %
    path('', include(router.urls)),
]
