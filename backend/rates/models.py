# rates/models.py
from django.db import models
from django.core.cache import cache
from django.core.exceptions import ValidationError
from decimal import Decimal


class ExchangeRateSource(models.Model):
    """
    Fuente de datos de tipo de cambio.
    Registra cada proveedor (BCB, mercado paralelo, plataformas digitales),
    su estado de salud y configuración de scraping/API.
    """
    SOURCE_TYPES = [
        ('bcb_official',  'BCB Oficial'),
        ('bcb_reference', 'BCB Referencial'),
        ('digital',       'Plataforma Digital'),
        ('parallel',      'Mercado Paralelo'),
    ]

    name                  = models.CharField(max_length=100, unique=True)
    source_type           = models.CharField(max_length=20, choices=SOURCE_TYPES, db_index=True)
    url                   = models.URLField(blank=True, help_text='URL base del scraping/API')
    is_active             = models.BooleanField(default=True, db_index=True)
    fetch_interval_min    = models.IntegerField(
        default=30, help_text='Frecuencia de actualización en minutos')
    weight                = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal('1.00'),
        help_text='Peso en el cálculo de tasa promedio ponderada (paralelo>digital>oficial)')
    priority              = models.IntegerField(
        default=1, help_text='Mayor número = usada primero como fallback')
    # Estado de salud
    last_fetched_at       = models.DateTimeField(null=True, blank=True)
    last_success_at       = models.DateTimeField(null=True, blank=True)
    consecutive_failures  = models.IntegerField(default=0)
    # Configuración extra (headers personalizados, tokens, selectores CSS, etc.)
    config                = models.JSONField(
        default=dict, blank=True,
        help_text='Configuración extra: {"headers": {}, "css_selector": "", "timeout": 15}')
    notes                 = models.TextField(blank=True)
    created_at            = models.DateTimeField(auto_now_add=True)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Fuente de Tasa'
        verbose_name_plural = 'Fuentes de Tasas'
        ordering            = ['-priority', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_source_type_display()})"

    def mark_success(self):
        from django.utils import timezone
        self.last_fetched_at      = timezone.now()
        self.last_success_at      = timezone.now()
        self.consecutive_failures = 0
        self.save(update_fields=['last_fetched_at', 'last_success_at', 'consecutive_failures'])

    def mark_failure(self):
        from django.utils import timezone
        self.last_fetched_at      = timezone.now()
        self.consecutive_failures += 1
        self.save(update_fields=['last_fetched_at', 'consecutive_failures'])

    @property
    def is_healthy(self) -> bool:
        """Fuente con menos de 5 fallos consecutivos."""
        return self.consecutive_failures < 5

class Currency(models.Model):
    code              = models.CharField(max_length=10, unique=True)
    name_en           = models.CharField(max_length=100, verbose_name='Name (EN)')
    name_es           = models.CharField(max_length=100, verbose_name='Nombre (ES)', blank=True)
    symbol            = models.CharField(max_length=10)
    is_active         = models.BooleanField(default=True, db_index=True)
    use_exchange_rate = models.BooleanField(
        default=True,
        help_text='True → usa tasas de cambio. False → valor fijo (efectivo directo).',
    )
    is_base_currency  = models.BooleanField(
        default=False,
        help_text='Solo UNA divisa puede ser la base. Normalmente BOB.',
    )
    scale_factor      = models.IntegerField(
        default=1,
        help_text=(
            'Multiplicador de unidades. '
            'scale_factor=1000 → tasa cotizada por 1000 unidades reales '
            '(ej. CLP, ARS). scale_factor=1 → tasa por unidad (ej. USD, EUR).'
        ),
    )
    created_at        = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        verbose_name        = 'Divisa'
        verbose_name_plural = 'Divisas'
        ordering            = ['code']

    def __str__(self):
        return f"{self.code} - {self.name_en}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.is_base_currency:
            qs = Currency.objects.filter(is_base_currency=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError('Ya existe una divisa base. Desactívela primero.')

class ExchangeRate(models.Model):
    MARKET_TYPE_CHOICES = [
        # ── Oficiales ──────────────────────────────────────────────────────────
        ('official',                    'Oficial BCB'),
        ('bcb',                         'BCB Referencial'),
        # ── Paralelo digital ──────────────────────────────────────────────────
        ('paralelo_digital',            'Paralelo Digital (Binance/Takenos/Airtm)'),
        # ── Paralelo físico ───────────────────────────────────────────────────
        ('paralelo_fisico_empresa',     'Paralelo Físico — Empresa'),
        ('paralelo_fisico_competencia', 'Paralelo Físico — Competencia'),
        # ── Legacy aliases (no romper datos históricos) ───────────────────────
        ('parallel', 'Mercado Paralelo (legacy)'),
        ('digital',  'Plataforma Digital (legacy)'),
    ]

    # ── Método de obtención del dato (trazabilidad regulatoria) ───────────────
    SOURCE_METHOD_CHOICES = [
        ('API',       'API externa — dato en tiempo real'),
        ('SCRAP',     'Web scraping — HTML o JSON parseado'),
        ('MANUAL',    'Ingreso manual — operador/administrador'),
        ('INFERENCE', 'Inferido/estimado — sin fuente directa verificable'),
    ]

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
    market_type = models.CharField(
        max_length=30,
        choices=MARKET_TYPE_CHOICES,
        default='official',
        db_index=True,
        help_text='Tipo de mercado que representa esta tasa.',
    )
    # Fuente estructurada (puede ser nula para tasas manuales/legacy)
    rate_source = models.ForeignKey(
        ExchangeRateSource,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rates',
        help_text='Fuente de datos que generó esta tasa.',
    )
    official_rate = models.DecimalField(max_digits=10, decimal_places=4)
    buy_rate  = models.DecimalField(max_digits=10, decimal_places=4)
    sell_rate = models.DecimalField(max_digits=10, decimal_places=4)
    source    = models.CharField(max_length=50, default='BCB',
                                 help_text='Nombre(s) de la fuente — legado, usar source_method para clasificación.')

    # ── TRACEABILITY FIELDS (Phase 3) ─────────────────────────────────────────
    source_method = models.CharField(
        max_length=10,
        choices=SOURCE_METHOD_CHOICES,
        default='SCRAP',
        db_index=True,
        help_text='Método por el que se obtuvo la tasa: API, SCRAP, MANUAL o INFERENCE.',
    )
    source_url = models.URLField(
        blank=True, null=True,
        help_text='URL exacta de donde se obtuvo el dato (para auditoría).',
    )
    fetched_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Momento en que se consultó la fuente externa.',
    )
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rates_created',
        help_text='Usuario que creó la tasa (null = proceso automático).',
    )
    is_validated = models.BooleanField(
        default=False,
        help_text='True si un administrador verificó y aprobó esta tasa.',
    )
    confidence = models.DecimalField(
        max_digits=4, decimal_places=3,
        default=Decimal('1.000'),
        help_text='Confianza 0.000–1.000 heredada del fetcher (0.5=hardcoded, 0.95=API directa).',
    )
    # ─────────────────────────────────────────────────────────────────────────

    # ── Sistema primario de tasas ─────────────────────────────────────────────
    is_primary = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            'True para la tasa que el sistema usará en todas las transacciones. '
            'Solo puede haber una tasa primaria activa por par de divisas. '
            'Seleccionada automáticamente por ExchangeRateService basado en '
            'confianza, fuente y tipo de mercado.'
        ),
    )
    avg_rate = models.DecimalField(
        max_digits=10, decimal_places=4,
        null=True, blank=True,
        help_text='Promedio simple de buy y sell rate (mid-rate).',
    )

    valid_from  = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['currency_from', 'currency_to', 'valid_from', 'market_type', 'rate_source']
        ordering = ['-valid_from']
        indexes = [
            models.Index(fields=['currency_from', 'currency_to', '-valid_from']),
            models.Index(fields=['market_type', 'currency_from', 'currency_to']),
            models.Index(fields=['rate_source', 'currency_from', '-valid_from']),
            models.Index(fields=['valid_until', 'currency_from', 'currency_to']),
            models.Index(fields=['source_method', 'currency_from', '-valid_from']),
            models.Index(fields=['is_validated', 'source_method']),
        ]

    @property
    def is_inference(self) -> bool:
        """True cuando la tasa es estimada/inferida y NO fue validada manualmente."""
        return self.source_method == 'INFERENCE' and not self.is_validated

    @property
    def requires_warning(self) -> bool:
        """True cuando la tasa requiere advertencia al usuario (inferida o baja confianza)."""
        return self.source_method == 'INFERENCE' or self.confidence < Decimal('0.70')

    def clean(self):
        """Validaciones financieras antes de guardar."""
        import logging
        log = logging.getLogger('kapitalya.rates')

        if self.buy_rate <= 0 or self.sell_rate <= 0 or self.official_rate <= 0:
            raise ValidationError("Las tasas deben ser mayores a cero.")
        if self.buy_rate > self.sell_rate:
            raise ValidationError(
                "La tasa de compra no puede ser mayor que la tasa de venta."
            )

        # Desviación máxima por tipo de mercado:
        #   official → 10%  (regulación ASFI)
        #   bcb      → 15%  (tasa referencial puede diferir ligeramente)
        #   digital  → 60%  (plataformas digitales tienen sus propios spreads)
        #   parallel → sin límite (mercado libre, el precio lo determina la oferta/demanda)
        if self.market_type in ('official', 'bcb') and self.official_rate > 0:
            # Ajustar official_rate al mismo escalado que buy/sell.
            # official_rate se almacena por UNIDAD (lo que entrega el BCB).
            # buy_rate/sell_rate se cotizan por scale_factor unidades.
            # Ej. CLP: official=0.0076 por CLP → adjusted=7.6 por 1000 CLP.
            try:
                scale = Decimal(str(self.currency_from.scale_factor))
            except (AttributeError, Exception):
                scale = Decimal('1')

            adjusted_official = self.official_rate * scale
            if adjusted_official > 0:
                buy_dev  = abs(self.buy_rate  - adjusted_official) / adjusted_official
                sell_dev = abs(self.sell_rate - adjusted_official) / adjusted_official
                max_dev  = max(buy_dev, sell_dev)

                limit = Decimal('0.10') if self.market_type == 'official' else Decimal('0.15')
                if max_dev > limit:
                    cur_code = getattr(self.currency_from, 'code', '?')
                    raise ValidationError(
                        f"Tasa {self.market_type} de {cur_code} se desvía {max_dev*100:.1f}% "
                        f"de la referencia BCB ajustada "
                        f"({adjusted_official:.4f} BOB por {int(scale)} unidad(es)). "
                        f"Máximo permitido: {float(limit)*100:.0f}%. "
                        f"Use market_type='digital' o market_type='parallel' para tasas de mercado libre."
                    )

        if self.market_type in ('parallel', 'digital'):
            log.debug(
                "FREE_MARKET_RATE_SAVED type=%s currency=%s buy=%s sell=%s official=%s",
                self.market_type,
                getattr(self.currency_from, 'code', self.currency_from_id),
                self.buy_rate, self.sell_rate, self.official_rate,
            )

    def save(self, *args, **kwargs):
        if self.buy_rate and self.sell_rate and not self.avg_rate:
            self.avg_rate = (self.buy_rate + self.sell_rate) / Decimal('2')
        self.full_clean()
        super().save(*args, **kwargs)
        cache_key = f"rate_{self.currency_from.code}_{self.currency_to.code}"
        cache.delete(cache_key)
        cache.delete(f"primary_rate_{self.currency_from.code}_{self.currency_to.code}")
    
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


class ExchangeRateDecisionLog(models.Model):
    """
    Auditoría de cada decisión del motor de precios AI.
    Registra qué tasas se usaron, con qué pesos, y cuál fue el TC sugerido.
    """
    TRIGGER_CHOICES = [
        ('scheduled',   'Tarea programada'),
        ('manual',      'Solicitud manual'),
        ('inventory',   'Alerta de inventario'),
        ('demand',      'Cambio de demanda'),
    ]

    currency_code   = models.CharField(max_length=10, db_index=True)
    branch          = models.ForeignKey(
        'users.Branch', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pricing_decisions',
    )
    trigger         = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default='scheduled')

    # Tasas de cada fuente en el momento de la decisión
    rate_bcb        = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    rate_binance    = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    rate_historical = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    rate_competition = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    # Pesos usados (deben sumar 1.0)
    weight_bcb        = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.25'))
    weight_binance    = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.35'))
    weight_historical = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.25'))
    weight_competition = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.15'))

    # TC base (antes de ajustes)
    base_rate_bob   = models.DecimalField(max_digits=12, decimal_places=4)

    # Ajustes dinámicos aplicados
    inventory_factor = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal('1.0000'),
                                           help_text='Factor de ajuste por nivel de inventario')
    demand_factor    = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal('1.0000'),
                                           help_text='Factor de ajuste por demanda reciente')

    # TC sugeridos finales
    suggested_buy   = models.DecimalField(max_digits=12, decimal_places=4)
    suggested_sell  = models.DecimalField(max_digits=12, decimal_places=4)
    suggested_spread = models.DecimalField(max_digits=12, decimal_places=4)
    suggested_spread_pct = models.DecimalField(max_digits=6, decimal_places=3)

    # TC real al momento (para comparar)
    actual_buy      = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    actual_sell     = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    # Contexto de inventario
    inventory_stock     = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    inventory_minimum   = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    inventory_maximum   = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    inventory_stock_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                               help_text='Stock como % del máximo')

    # Contexto de demanda (últimas 4h)
    recent_buy_count  = models.IntegerField(default=0)
    recent_sell_count = models.IntegerField(default=0)

    # Recomendación textual
    recommendation  = models.CharField(max_length=500, blank=True)

    created_at      = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table  = 'rates_pricing_decision_log'
        ordering  = ['-created_at']
        indexes   = [
            models.Index(fields=['currency_code', '-created_at']),
            models.Index(fields=['branch', '-created_at']),
        ]
        verbose_name        = 'Decisión de Precios AI'
        verbose_name_plural = 'Decisiones de Precios AI'

    def __str__(self):
        return (f'{self.currency_code} buy={self.suggested_buy} sell={self.suggested_sell} '
                f'[{self.created_at:%Y-%m-%d %H:%M}]')

    @property
    def deviation_from_actual_pct(self) -> Decimal | None:
        """% de diferencia entre TC sugerido y TC actual (en sell_rate)."""
        if self.actual_sell and self.actual_sell > 0:
            return ((self.suggested_sell - self.actual_sell) / self.actual_sell * 100).quantize(
                Decimal('0.01'))
        return None