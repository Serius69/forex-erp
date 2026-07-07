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
    PosicionInventarioView,
    AlertasInventarioView,
    HistorialMovimientosView,
    KPIsTarjetasView,
)

router = DefaultRouter()
router.register(r'tipos',       TipoTarjetaViewSet,      basename='tipos-tarjeta')
router.register(r'lotes',       LoteCompraViewSet,       basename='lotes-tarjeta')
router.register(r'ventas',      VentaTarjetaViewSet,     basename='ventas-tarjeta')
router.register(r'movimientos', MovimientoTarjetaViewSet, basename='movimientos-tarjeta')

urlpatterns = [
    # ── Endpoints principales ─────────────────────────────────────────────────
    path('comprar/',    ComprarTarjetaView.as_view(),   name='tarjetas-comprar'),
    path('vender/',     VenderTarjetaView.as_view(),    name='tarjetas-vender'),
    path('inventario/', InventarioTarjetaView.as_view(), name='tarjetas-inventario'),

    # ── Inventario avanzado ───────────────────────────────────────────────────
    path('inventario/posicion/',             PosicionInventarioView.as_view(),   name='tarjetas-posicion'),
    path('inventario/alertas/',              AlertasInventarioView.as_view(),    name='tarjetas-alertas'),
    path('inventario/historial_movimientos/', HistorialMovimientosView.as_view(), name='tarjetas-historial'),
    path('inventario/kpis/',                 KPIsTarjetasView.as_view(),         name='tarjetas-kpis'),

    # ── Router ViewSets (CRUD + acciones) ─────────────────────────────────────
    path('', include(router.urls)),
]
