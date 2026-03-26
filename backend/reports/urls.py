# reports/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (RTEViewSet, ROUEViewSet, PEPViewSet,
                     DailyLogViewSet, ManagementReportViewSet)

rte_router       = DefaultRouter()
roue_router      = DefaultRouter()
pep_router       = DefaultRouter()
daily_log_router = DefaultRouter()
mgmt_router      = DefaultRouter()

rte_router.register(r'',       RTEViewSet,              basename='rte')
roue_router.register(r'',      ROUEViewSet,             basename='roue')
pep_router.register(r'',       PEPViewSet,              basename='pep')
daily_log_router.register(r'', DailyLogViewSet,         basename='daily-log')
mgmt_router.register(r'',      ManagementReportViewSet, basename='management')

urlpatterns = [
    path('asfi/rte/',       include(rte_router.urls)),
    path('asfi/roue/',      include(roue_router.urls)),
    path('asfi/pep/',       include(pep_router.urls)),
    path('asfi/daily-log/', include(daily_log_router.urls)),
    path('management/',     include(mgmt_router.urls)),
]