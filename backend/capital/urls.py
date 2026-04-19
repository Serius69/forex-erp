from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    GastoViewSet, CapitalSnapshotViewSet, CapitalManualEntryViewSet,
    CapitalComposicionViewSet, CashBOBViewSet,
    capital_actual, ganancias_divisas, resumen_financiero, capital_resumen,
    capital_at_date,
)

router = DefaultRouter()
router.register(r'gastos',       GastoViewSet,              basename='gastos')
router.register(r'snapshots',    CapitalSnapshotViewSet,    basename='snapshots')
router.register(r'caja',         CapitalManualEntryViewSet, basename='capital-caja')
router.register(r'composicion',  CapitalComposicionViewSet, basename='composicion')
router.register(r'cash-bob',     CashBOBViewSet,            basename='cash-bob')

urlpatterns = [
    path('', include(router.urls)),
    path('actual/',          capital_actual,     name='capital-actual'),
    path('ganancias/',       ganancias_divisas,  name='ganancias-divisas'),
    path('resumen/',         resumen_financiero, name='resumen-financiero'),
    path('resumen-capital/', capital_resumen,    name='capital-resumen'),
    path('at-date/',         capital_at_date,    name='capital-at-date'),
]
