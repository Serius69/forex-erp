from rest_framework import serializers
from .models import PredictionModel, Prediction, TrainingData


class PredictionModelSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PredictionModel
        fields = [
            'id', 'name', 'model_type', 'currency_pair',
            'parameters', 'metrics', 'model_file',
            'is_active', 'created_at', 'last_trained',
        ]
        read_only_fields = ['created_at', 'last_trained']


class PredictionSerializer(serializers.ModelSerializer):
    model      = PredictionModelSerializer(read_only=True)
    model_id   = serializers.PrimaryKeyRelatedField(
        queryset=PredictionModel.objects.all(),
        source='model', write_only=True)

    class Meta:
        model  = Prediction
        fields = [
            'id', 'model', 'model_id', 'currency_pair',
            'prediction_date',
            'predicted_rate', 'predicted_buy_rate', 'predicted_sell_rate',
            'confidence_lower', 'confidence_upper', 'confidence_score',
            'external_factors',
            'actual_rate', 'error_percentage',
            'created_at',
        ]
        read_only_fields = ['created_at', 'error_percentage']


class TrainingDataSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TrainingData
        fields = [
            'id', 'currency_pair', 'date', 'rate', 'volume',
            'international_rate', 'interest_rate',
            'inflation_rate', 'oil_price',
            'ma_7', 'ma_30', 'volatility', 'source',
        ]