# predictions/models.py
from django.db import models
from django.contrib.postgres.fields import ArrayField
import json

class PredictionModel(models.Model):
    MODEL_TYPES = [
        ('PROPHET', 'Prophet'),
        ('LSTM', 'LSTM'),
        ('ARIMA', 'ARIMA'),
        ('ENSEMBLE', 'Ensemble'),
    ]
    
    name = models.CharField(max_length=100)
    model_type = models.CharField(max_length=20, choices=MODEL_TYPES)
    currency_pair = models.CharField(max_length=10)
    parameters = models.JSONField(default=dict)
    metrics = models.JSONField(default=dict)
    model_file = models.FileField(upload_to='ml_models/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_trained = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Modelo de Predicción'
        verbose_name_plural = 'Modelos de Predicción'
        unique_together = ['model_type', 'currency_pair']
    
    def __str__(self):
        return f"{self.name} - {self.currency_pair}"

class Prediction(models.Model):
    model = models.ForeignKey(PredictionModel, on_delete=models.CASCADE)
    currency_pair = models.CharField(max_length=10)
    prediction_date = models.DateTimeField()
    
    # Predicciones
    predicted_rate = models.DecimalField(max_digits=10, decimal_places=4)
    predicted_buy_rate = models.DecimalField(max_digits=10, decimal_places=4)
    predicted_sell_rate = models.DecimalField(max_digits=10, decimal_places=4)
    
    # Intervalos de confianza
    confidence_lower = models.DecimalField(max_digits=10, decimal_places=4)
    confidence_upper = models.DecimalField(max_digits=10, decimal_places=4)
    confidence_score = models.FloatField(default=0)
    
    # Factores externos considerados
    external_factors = models.JSONField(default=dict)
    
    # Resultado real (para evaluar precisión)
    actual_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    error_percentage = models.FloatField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-prediction_date']
        indexes = [
            models.Index(fields=['currency_pair', 'prediction_date']),
            models.Index(fields=['created_at']),
        ]
    
    def calculate_error(self):
        """Calcula el error de predicción si hay tasa real"""
        if self.actual_rate and self.predicted_rate:
            error = abs(self.actual_rate - self.predicted_rate)
            self.error_percentage = (error / self.actual_rate) * 100
            self.save()

class TrainingData(models.Model):
    """Datos históricos para entrenamiento"""
    currency_pair = models.CharField(max_length=10)
    date = models.DateTimeField()
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    volume = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    
    # Indicadores externos
    international_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    inflation_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    oil_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Indicadores técnicos calculados
    ma_7 = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    ma_30 = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    volatility = models.FloatField(null=True, blank=True)
    
    source = models.CharField(max_length=50, default='BCB')
    
    class Meta:
        unique_together = ['currency_pair', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['currency_pair', '-date']),
        ]