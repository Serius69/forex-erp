# predictions/models.py
from django.db import models
from django.contrib.postgres.fields import ArrayField
from decimal import Decimal
import json

class PredictionModel(models.Model):
    MODEL_TYPES = [
        ('PROPHET',  'Prophet'),
        ('LSTM',     'LSTM (legacy)'),
        ('BILSTM',   'BiLSTM + Attention'),
        ('XGBOOST',  'XGBoost'),
        ('ARIMA',    'Auto-ARIMA'),
        ('ENSEMBLE', 'Ensemble'),
    ]
    
    MARKET_CHOICES = [
        ('web',         'Web / Paralelo digital'),
        ('competencia', 'Competencia / Físico mercado'),
        ('empresa',     'Empresa / Transacciones propias'),
    ]

    name = models.CharField(max_length=100)
    model_type = models.CharField(max_length=20, choices=MODEL_TYPES)
    currency_pair = models.CharField(max_length=10)
    market = models.CharField(
        max_length=15, choices=MARKET_CHOICES, default='web', db_index=True,
        help_text='Serie que este modelo pronostica: web / competencia / empresa.',
    )
    parameters = models.JSONField(default=dict)
    metrics = models.JSONField(default=dict)
    model_file = models.FileField(upload_to='ml_models/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_trained = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Modelo de Predicción'
        verbose_name_plural = 'Modelos de Predicción'
        unique_together = ['model_type', 'currency_pair', 'market']

    def __str__(self):
        return f"{self.name} - {self.currency_pair} [{self.market}]"

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
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['currency_pair', 'prediction_date']),
            models.Index(fields=['created_at']),
        ]
    
    def calculate_error(self):
        """Calcula el error de predicción si hay tasa real (Decimal, MAPE)."""
        if self.actual_rate and self.predicted_rate and self.actual_rate != 0:
            actual    = Decimal(str(self.actual_rate))
            predicted = Decimal(str(self.predicted_rate))
            error_pct = (abs(actual - predicted) / actual * Decimal('100'))
            self.error_percentage = float(
                error_pct.quantize(Decimal('0.0001'))
            )
            self.save(update_fields=['error_percentage'])

class TrainingData(models.Model):
    """Datos históricos para entrenamiento"""

    # ── Fuente/serie de mercado (pronóstico independiente por fuente) ──────────
    #   web         → tasa digital/paralelo web (Binance/dólar blue)   → paralelo_digital
    #   competencia → tasa física de mercado/competencia (casas)        → paralelo_fisico_competencia
    #   empresa     → tasa efectiva realizada por la propia empresa      → paralelo_fisico_empresa
    #                 (derivada de las transacciones reales)
    MARKET_CHOICES = [
        ('web',         'Web / Paralelo digital'),
        ('competencia', 'Competencia / Físico mercado'),
        ('empresa',     'Empresa / Transacciones propias'),
    ]

    currency_pair = models.CharField(max_length=10)
    market = models.CharField(
        max_length=15,
        choices=MARKET_CHOICES,
        default='web',
        db_index=True,
        help_text='Fuente de la serie: web (digital), competencia (físico mercado) '
                  'o empresa (transacciones propias). Cada una se pronostica por separado.',
    )
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
        unique_together = ['currency_pair', 'market', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['currency_pair', '-date']),
            models.Index(fields=['currency_pair', 'market', '-date']),
        ]


class EnsembleWeightHistory(models.Model):
    """Historial de pesos dinámicos del ensemble — permite auditar cómo evolucionaron."""
    currency_pair = models.CharField(max_length=10, db_index=True)
    market        = models.CharField(max_length=15, default='web', db_index=True)
    weights       = models.JSONField()        # {'PROPHET': 0.35, 'BILSTM': 0.30, ...}
    recorded_at   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-recorded_at']
        indexes  = [models.Index(fields=['currency_pair', '-recorded_at'])]

    def __str__(self):
        return f"Weights {self.currency_pair} @ {self.recorded_at:%Y-%m-%d %H:%M}"