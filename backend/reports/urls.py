from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (RTEViewSet, ROUEViewSet, PEPViewSet,
                     DailyLogViewSet, ManagementReportViewSet)

router = DefaultRouter()
router.register(r'asfi/rte',        RTEViewSet,              basename='rte')
router.register(r'asfi/roue',       ROUEViewSet,             basename='roue')
router.register(r'asfi/pep',        PEPViewSet,              basename='pep')
router.register(r'asfi/daily-log',  DailyLogViewSet,         basename='daily-log')
router.register(r'management',      ManagementReportViewSet, basename='management')

urlpatterns = [path('', include(router.urls))]