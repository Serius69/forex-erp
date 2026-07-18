from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    GastoViewSet, IngresoExtraViewSet, CapitalSnapshotViewSet, CapitalManualEntryViewSet,
    CapitalComposicionViewSet, CashBOBViewSet,
    capital_actual, ganancias_divisas, resumen_financiero, capital_resumen,
    capital_at_date,
    # Nuevos endpoints C3/C4/C6
    capital_position_view, capital_pnl_view, capital_history_view,
    capital_alerts_view, capital_kpis_view,
    # Migración legado: cuentas por pagar + caja chica
    AcreedorViewSet, MovimientoAcreedorViewSet, MovimientoCajaChicaViewSet,
)

router = DefaultRouter()
router.register(r'gastos',       GastoViewSet,              basename='gastos')
router.register(r'ingresos',     IngresoExtraViewSet,       basename='ingresos-extra')
router.register(r'snapshots',    CapitalSnapshotViewSet,    basename='snapshots')
router.register(r'caja',         CapitalManualEntryViewSet, basename='capital-caja')
router.register(r'composicion',  CapitalComposicionViewSet, basename='composicion')
router.register(r'cash-bob',     CashBOBViewSet,            basename='cash-bob')
router.register(r'acreedores',            AcreedorViewSet,            basename='acreedores')
router.register(r'acreedores-movimientos', MovimientoAcreedorViewSet, basename='acreedor-mov')
router.register(r'caja-chica',            MovimientoCajaChicaViewSet, basename='caja-chica')

urlpatterns = [
    path('', include(router.urls)),
    path('actual/',          capital_actual,     name='capital-actual'),
    path('ganancias/',       ganancias_divisas,  name='ganancias-divisas'),
    path('resumen/',         resumen_financiero, name='resumen-financiero'),
    path('resumen-capital/', capital_resumen,    name='capital-resumen'),
    path('at-date/',         capital_at_date,    name='capital-at-date'),
    # ── Nuevos C3/C4/C6 ──────────────────────────────────────────────────────
    path('position/',        capital_position_view, name='capital-position'),
    path('pnl/',             capital_pnl_view,      name='capital-pnl'),
    path('history/',         capital_history_view,  name='capital-history'),
    path('alerts/',          capital_alerts_view,   name='capital-alerts-new'),
    path('metrics/kpis/',    capital_kpis_view,     name='capital-kpis'),
]
