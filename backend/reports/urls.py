# reports/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    RTEViewSet, ROUEViewSet, PEPViewSet,
    DailyLogViewSet, ManagementReportViewSet, GeneratedReportViewSet,
    RTEReportView, PEPReportView,
)

# ── Routers para operaciones CRUD / list / retrieve ───────────────────────────
rte_router       = DefaultRouter()
roue_router      = DefaultRouter()
pep_router       = DefaultRouter()
daily_log_router = DefaultRouter()
mgmt_router      = DefaultRouter()
generated_router = DefaultRouter()

rte_router.register(r'',       RTEViewSet,              basename='rte')
roue_router.register(r'',      ROUEViewSet,             basename='roue')
pep_router.register(r'',       PEPViewSet,              basename='pep')
daily_log_router.register(r'', DailyLogViewSet,         basename='daily-log')
mgmt_router.register(r'',      ManagementReportViewSet, basename='management')
generated_router.register(r'', GeneratedReportViewSet,  basename='generated')

urlpatterns = [
    # ── Descarga directa RTE (vistas dedicadas, sin ambigüedad de router) ────
    path('asfi/rte/download-excel/',
         RTEReportView.as_view(), {'fmt': 'excel'},
         name='rte-download-excel'),
    path('asfi/rte/download-pdf/',
         RTEReportView.as_view(), {'fmt': 'pdf'},
         name='rte-download-pdf'),
    path('asfi/rte/download-csv/',
         RTEReportView.as_view(), {'fmt': 'csv'},
         name='rte-download-csv'),

    # ── Descarga directa PEP ──────────────────────────────────────────────────
    path('asfi/pep/download-excel/',
         PEPReportView.as_view(), {'fmt': 'excel'},
         name='pep-download-excel'),
    path('asfi/pep/download-pdf/',
         PEPReportView.as_view(), {'fmt': 'pdf'},
         name='pep-download-pdf'),

    # ── ViewSets ASFI (list, retrieve, monthly_report, daily-log/generate) ───
    path('asfi/rte/',       include(rte_router.urls)),
    path('asfi/roue/',      include(roue_router.urls)),
    path('asfi/pep/',       include(pep_router.urls)),
    path('asfi/daily-log/', include(daily_log_router.urls)),

    # ── Reportes gerenciales ──────────────────────────────────────────────────
    path('management/', include(mgmt_router.urls)),

    # ── Historial de reportes generados ──────────────────────────────────────
    path('generated/',  include(generated_router.urls)),
]
