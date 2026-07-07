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
    ProfitOptimizerView,
    CashVariantsView,
    RateSnapshotView,
    FXEngineView,
    # B3/B4 — nuevos
    ProfitabilityAnalysisView,
    DynamicSpreadView,
    ParallelRateView,
    # Integration layer
    ConsensusView,
    RawHistoryView,
    IntegrationSourcesView,
    LatestRawView,
    # Continuous extraction
    ExtractionStatusView,
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
    path('history/',          RateHistoryView.as_view(),      name='rate-history'),
    path('binance/',          BinanceP2PView.as_view(),       name='binance-p2p'),
    path('ai-pricing/',       AIPricingView.as_view(),        name='ai-pricing'),
    path('forecast/',         ForecastView.as_view(),         name='rate-forecast'),
    # ── New: Auto Profit Mode ────────────────────────────────────────────────
    path('profit-optimizer/', ProfitOptimizerView.as_view(),  name='profit-optimizer'),
    # ── New: Physical Cash Variants ──────────────────────────────────────────
    path('cash-variants/',    CashVariantsView.as_view(),     name='cash-variants'),
    # ── New: Daily Snapshots ─────────────────────────────────────────────────
    path('snapshots/',        RateSnapshotView.as_view(),     name='rate-snapshots'),
    # ── Production FX Engine (parallel market only, 2-decimal) ───────────────
    path('fx-engine/',        FXEngineView.as_view(),         name='fx-engine'),
    path('fx-engine/run/',    FXEngineView.as_view(),         name='fx-engine-run'),
    # ── B3: Análisis de rentabilidad ──────────────────────────────────────────
    path('profitability-analysis/', ProfitabilityAnalysisView.as_view(), name='profitability-analysis'),
    # ── B2: Spread dinámico ───────────────────────────────────────────────────
    path('dynamic-spread/',         DynamicSpreadView.as_view(),         name='dynamic-spread'),
    # ── B1: Tasa paralela consolidada ─────────────────────────────────────────
    path('parallel-rate/',          ParallelRateView.as_view(),          name='parallel-rate'),
    # ── Integration layer ─────────────────────────────────────────────────────
    path('consensus/',              ConsensusView.as_view(),             name='integration-consensus'),
    path('raw-history/',            RawHistoryView.as_view(),            name='integration-raw-history'),
    path('integration-sources/',    IntegrationSourcesView.as_view(),    name='integration-sources'),
    path('latest-raw/',             LatestRawView.as_view(),             name='integration-latest-raw'),
    # ── Continuous extraction status ──────────────────────────────────────────
    path('extraction-status/',      ExtractionStatusView.as_view(),      name='extraction-status'),
]
