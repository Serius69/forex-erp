from rest_framework import serializers
from .models import (
    Currency, ExchangeRate, ExchangeRateSource,
    RateConfiguration, ExchangeRateSnapshot, ReferenceRate,
)


class ExchangeRateSourceSerializer(serializers.ModelSerializer):
    is_healthy = serializers.BooleanField(read_only=True)

    class Meta:
        model  = ExchangeRateSource
        fields = [
            'id', 'name', 'source_type', 'url', 'is_active',
            'fetch_interval_min', 'weight', 'priority',
            'last_fetched_at', 'last_success_at', 'consecutive_failures',
            'is_healthy', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'last_fetched_at', 'last_success_at']


class CurrencySerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model  = Currency
        fields = [
            'id', 'code', 'name', 'name_en', 'name_es', 'symbol',
            'is_active', 'use_exchange_rate', 'is_base_currency',
            'scale_factor', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_name(self, obj):
        return obj.name_es or obj.name_en


class ExchangeRateSerializer(serializers.ModelSerializer):
    currency_from = CurrencySerializer(read_only=True)
    currency_to   = CurrencySerializer(read_only=True)
    currency_from_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_from', write_only=True)
    currency_to_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_to', write_only=True)
    spread             = serializers.DecimalField(max_digits=10, decimal_places=4, read_only=True)
    spread_percentage  = serializers.DecimalField(max_digits=5,  decimal_places=2, read_only=True)
    # Traceability (read-only, computed by the fetcher/aggregator pipeline)
    is_inference       = serializers.BooleanField(read_only=True)
    requires_warning   = serializers.BooleanField(read_only=True)
    source_method_display = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model  = ExchangeRate
        fields = [
            'id', 'currency_from', 'currency_from_id',
            'currency_to', 'currency_to_id',
            'official_rate', 'buy_rate', 'sell_rate',
            'spread', 'spread_percentage',
            'market_type',
            'rate_source',
            # Legacy source label
            'source',
            # ── Traceability fields (Phase 3) ─────────────────────────────────
            'source_method',          # API | SCRAP | MANUAL | INFERENCE
            'source_method_display',  # human-readable label
            'source_url',             # URL consultada
            'fetched_at',             # timestamp de la consulta
            'created_by',             # user FK (null = auto)
            'is_validated',           # admin-approved
            'confidence',             # 0.000–1.000
            'is_inference',           # computed: source_method == INFERENCE and not validated
            'requires_warning',       # computed: inference or low confidence
            # ── Sistema primario ──────────────────────────────────────────────
            'is_primary',             # True = tasa usada en transacciones
            'avg_rate',               # mid-rate (buy+sell)/2
            # ─────────────────────────────────────────────────────────────────
            'valid_from', 'valid_until',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'created_at', 'updated_at',
            'is_inference', 'requires_warning', 'source_method_display',
            'avg_rate',
        ]

    def get_source_method_display(self, obj) -> str:
        labels = {
            'API':       'API externa (tiempo real)',
            'SCRAP':     'Web scraping',
            'MANUAL':    'Ingreso manual',
            'INFERENCE': 'Estimado/inferido',
        }
        return labels.get(obj.source_method, obj.source_method)


class RateConfigurationSerializer(serializers.ModelSerializer):
    currency_from = CurrencySerializer(read_only=True)
    currency_to   = CurrencySerializer(read_only=True)
    currency_from_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_from', write_only=True)
    currency_to_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_to', write_only=True)
    current_margins = serializers.SerializerMethodField()

    class Meta:
        model  = RateConfiguration
        fields = [
            'id', 'currency_from', 'currency_from_id',
            'currency_to', 'currency_to_id',
            'buy_margin_morning',    'sell_margin_morning',
            'buy_margin_afternoon',  'sell_margin_afternoon',
            'buy_margin_evening',    'sell_margin_evening',
            'min_transaction_amount', 'max_transaction_amount',
            'is_active', 'current_margins',
        ]

    def get_current_margins(self, obj):
        buy, sell = obj.get_current_margins()
        return {'buy': buy, 'sell': sell}


class ExchangeRateSnapshotSerializer(serializers.ModelSerializer):
    """Serializa un snapshot diario del estado del mercado."""
    usd_spread_pct = serializers.SerializerMethodField()

    class Meta:
        model  = ExchangeRateSnapshot
        fields = [
            'id', 'date', 'status',
            'avg_usd_buy', 'avg_usd_sell', 'usd_spread_pct',
            'max_spread_pct', 'source_count', 'anomaly_count',
            'close_usd_buy', 'close_usd_sell',
            'close_eur_buy', 'close_eur_sell',
            'best_source', 'aggregated_data', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_usd_spread_pct(self, obj) -> float | None:
        if obj.avg_usd_buy and obj.avg_usd_sell and obj.avg_usd_buy > 0:
            return float((obj.avg_usd_sell - obj.avg_usd_buy) / obj.avg_usd_buy * 100)
        return None


class ReferenceRateSerializer(serializers.ModelSerializer):
    """
    Tasa de referencia BCB / BCP — SOLO para display.
    ⚠️  No usar para operaciones de cambio.
    """
    display_label = serializers.SerializerMethodField()

    class Meta:
        model  = ReferenceRate
        fields = [
            'id', 'currency', 'source',
            'reference_buy', 'reference_sell',
            'display_label', 'timestamp',
        ]
        read_only_fields = fields

    def get_display_label(self, obj) -> str:
        return 'Solo referencia - no usado para operaciones'


class LiveEngineRateSerializer(serializers.Serializer):
    """
    Serializer for FXEngine output rates (2-decimal precision).
    Used by /api/rates/fx-engine/ endpoint.
    """
    currency     = serializers.CharField()
    buy_rate     = serializers.DecimalField(max_digits=10, decimal_places=2)
    sell_rate    = serializers.DecimalField(max_digits=10, decimal_places=2)
    avg_rate     = serializers.DecimalField(max_digits=10, decimal_places=2)
    spread       = serializers.DecimalField(max_digits=10, decimal_places=2)
    spread_pct   = serializers.DecimalField(max_digits=6,  decimal_places=2)
    market_buy   = serializers.DecimalField(max_digits=10, decimal_places=2)
    market_sell  = serializers.DecimalField(max_digits=10, decimal_places=2)
    margin_buy   = serializers.DecimalField(max_digits=10, decimal_places=2)
    margin_sell  = serializers.DecimalField(max_digits=10, decimal_places=2)
    sources      = serializers.ListField(child=serializers.CharField())
    source_count = serializers.IntegerField()
    confidence   = serializers.DecimalField(max_digits=5, decimal_places=3)
    scale_factor = serializers.IntegerField()