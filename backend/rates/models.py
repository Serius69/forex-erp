# rates/models.py
from django.db import models
from django.core.cache import cache
from decimal import Decimal

class Currency(models.Model):
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=50)
    symbol = models.CharField(max_length=5)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Divisa'
        verbose_name_plural = 'Divisas'
        ordering = ['code']
    
    def __str__(self):
        return f"{self.code} - {self.name}"

class ExchangeRate(models.Model):
    currency_from = models.ForeignKey(
        Currency,
        on_delete=models.CASCADE,
        related_name='rates_from'
    )
    currency_to = models.ForeignKey(
        Currency,
        on_delete=models.CASCADE,
        related_name='rates_to'
    )
    official_rate = models.DecimalField(max_digits=10, decimal_places=4)
    buy_rate = models.DecimalField(max_digits=10, decimal_places=4)
    sell_rate = models.DecimalField(max_digits=10, decimal_places=4)
    source = models.CharField(max_length=50, default='BCB')
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['currency_from', 'currency_to', 'valid_from']
        ordering = ['-valid_from']
        indexes = [
            models.Index(fields=['currency_from', 'currency_to', '-valid_from']),
        ]
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Invalidar cache
        cache_key = f"rate_{self.currency_from.code}_{self.currency_to.code}"
        cache.delete(cache_key)
    
    @property
    def spread(self):
        return self.sell_rate - self.buy_rate
    
    @property
    def spread_percentage(self):
        if self.buy_rate:
            return ((self.spread / self.buy_rate) * 100).quantize(Decimal('0.01'))
        return Decimal('0')

class RateConfiguration(models.Model):
    currency_from = models.ForeignKey(
        Currency,
        on_delete=models.CASCADE,
        related_name='config_from'
    )
    currency_to = models.ForeignKey(
        Currency,
        on_delete=models.CASCADE,
        related_name='config_to'
    )
    buy_margin_morning = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Margen de compra en la mañana (%)"
    )
    sell_margin_morning = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Margen de venta en la mañana (%)"
    )
    buy_margin_afternoon = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Margen de compra en la tarde (%)"
    )
    sell_margin_afternoon = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Margen de venta en la tarde (%)"
    )
    buy_margin_evening = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Margen de compra en la noche (%)"
    )
    sell_margin_evening = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Margen de venta en la noche (%)"
    )
    min_transaction_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=10
    )
    max_transaction_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=10000
    )
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['currency_from', 'currency_to']
        verbose_name = 'Configuración de Tasa'
        verbose_name_plural = 'Configuraciones de Tasas'
    
    def get_current_margins(self):
        """Obtiene los márgenes según la hora actual"""
        from datetime import datetime
        current_hour = datetime.now().hour
        
        if 6 <= current_hour < 12:  # Mañana
            return self.buy_margin_morning, self.sell_margin_morning
        elif 12 <= current_hour < 18:  # Tarde
            return self.buy_margin_afternoon, self.sell_margin_afternoon
        else:  # Noche
            return self.buy_margin_evening, self.sell_margin_evening