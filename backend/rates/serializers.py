from rest_framework import serializers
from .models import Currency, ExchangeRate, RateConfiguration


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model  = Currency
        fields = ['id', 'code', 'name', 'symbol', 'is_active']


class ExchangeRateSerializer(serializers.ModelSerializer):
    currency_from = CurrencySerializer(read_only=True)
    currency_to   = CurrencySerializer(read_only=True)
    currency_from_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_from', write_only=True)
    currency_to_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_to', write_only=True)
    spread            = serializers.DecimalField(max_digits=10, decimal_places=4, read_only=True)
    spread_percentage = serializers.DecimalField(max_digits=5,  decimal_places=2, read_only=True)

    class Meta:
        model  = ExchangeRate
        fields = [
            'id', 'currency_from', 'currency_from_id',
            'currency_to', 'currency_to_id',
            'official_rate', 'buy_rate', 'sell_rate',
            'spread', 'spread_percentage',
            'source', 'valid_from', 'valid_until',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


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