from rest_framework import serializers
from .models import Currency, ExchangeRate, RateConfiguration

class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ['id', 'code', 'name', 'symbol', 'is_active']

class ExchangeRateSerializer(serializers.ModelSerializer):
    currency_from = CurrencySerializer(read_only=True)
    currency_to = CurrencySerializer(read_only=True)
    currency_from_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_from', write_only=True
    )
    currency_to_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_to', write_only=True
    )
    spread = serializers.DecimalField(max_digits=10, decimal_places=4, read_only=True)
    spread_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    
    class Meta:
        model = ExchangeRate
        fields = [
            'id', 'currency_from', 'currency_to', 'currency_from_id', 'currency_to_id',
            'official_rate', 'buy_rate', 'sell_rate', 'spread', 'spread_percentage',
            'source', 'valid_from', 'valid_until', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'spread', 'spread_percentage']

class RateConfigurationSerializer(serializers.ModelSerializer):
    currency_from = CurrencySerializer(read_only=True)
    currency_to = CurrencySerializer(read_only=True)
    currency_from_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_from', write_only=True
    )
    currency_to_id = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(), source='currency_to', write_only=True
    )
    
    class Meta:
        model = RateConfiguration
        fields = '__all__'
        read_only_fields = ['id']

class ExchangeCalculationSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    currency_from = serializers.CharField(max_length=3)
    currency_to = serializers.CharField(max_length=3, default='BOB')
    transaction_type = serializers.ChoiceField(choices=['BUY', 'SELL'])