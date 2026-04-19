# backend/rates/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CurrencyViewSet,
    ExchangeRateViewSet,
    ExchangeRateSourceViewSet,
    RateConfigurationViewSet,
    LiveRatesView,
    ArbitrageView,
    RateHistoryView,
    BinanceP2PView,
    AIPricingView,
    ForecastView,
    EngineView,
)

router = DefaultRouter()
router.register(r'currencies',     CurrencyViewSet,          basename='currencies')
router.register(r'exchange-rates', ExchangeRateViewSet,      basename='exchange-rates')
router.register(r'sources',        ExchangeRateSourceViewSet, basename='rate-sources')
router.register(r'configuration',  RateConfigurationViewSet, basename='rate-configuration')
router.register(r'live',           LiveRatesView,            basename='live-rates')
router.register(r'arbitrage',      ArbitrageView,            basename='arbitrage')
router.register(r'engine',         EngineView,               basename='engine')

urlpatterns = [
    path('', include(router.urls)),
    path('history/',    RateHistoryView.as_view(),  name='rate-history'),
    path('binance/',    BinanceP2PView.as_view(),   name='binance-p2p'),
    path('ai-pricing/', AIPricingView.as_view(),    name='ai-pricing'),
    path('forecast/',   ForecastView.as_view(),     name='rate-forecast'),
]
