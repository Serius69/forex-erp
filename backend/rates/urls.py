# backend/rates/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CurrencyViewSet, ExchangeRateViewSet, RateConfigurationViewSet

router = DefaultRouter()
router.register(r'currencies',     CurrencyViewSet,          basename='currencies')
router.register(r'exchange-rates', ExchangeRateViewSet,      basename='exchange-rates')
router.register(r'configuration',  RateConfigurationViewSet, basename='rate-configuration')

urlpatterns = [
    path('', include(router.urls)),
]