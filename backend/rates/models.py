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
        ('digital',  'Plataforma Digital'),
        ('parallel', 'Mercado Paralelo'),
    ]

    TIPO_FUENTE_CHOICES = [
        ('P2P',       'P2P Exchange'),
        ('AGREGADOR', 'Agregador / Sitio Web'),
        ('EXCHANGE',  'Exchange Centralizado'),
        ('WALLET',    'Wallet / Remesa'),
    ]

    METODO_HTTP_CHOICES = [
        ('GET',  'GET'),
        ('POST', 'POST'),
    ]

    # Identificador slug único para la capa de integrations/
    id_fuente         = models.CharField(max_length=60, unique=True, null=True, blank=True,
                                         help_text='Slug único: binance_p2p_bob, saldoar…')
    tipo_fuente       = models.CharField(max_length=20, choices=TIPO_FUENTE_CHOICES,
                                         null=True, blank=True, db_index=True)
    metodo_http       = models.CharField(max_length=4, choices=METODO_HTTP_CHOICES, default='GET')
    requiere_auth     = models.BooleanField(default=False)
    pais_referencia   = models.CharField(max_length=3, blank=True,
                                          help_text='Código ISO 3166-1 alpha-2 (BO, AR, BR…)')
    necesita_revision = models.BooleanField(default=False,
                                             help_text='True si el parser no encontró el dato en el último ciclo')

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
    code              = models.CharField(max_length=20, unique=True)
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

    @property
    def name(self) -> str:
        return self.name_es or self.name_en

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
        default='paralelo_digital',
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
    source    = models.CharField(max_length=50, default='',
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


class ExchangeRateSnapshot(models.Model):
    """
    Snapshot diario del estado del mercado de divisas.
    Captura el estado agregado de todas las fuentes al final de cada día
    para análisis histórico, auditoría y backtesting del motor de precios.
    """
    SNAPSHOT_STATUS = [
        ('partial',  'Parcial — algunas fuentes no disponibles'),
        ('complete', 'Completo — todas las fuentes respondieron'),
        ('degraded', 'Degradado — solo fuentes secundarias'),
    ]

    date             = models.DateField(unique=True, db_index=True)
    status           = models.CharField(max_length=10, choices=SNAPSHOT_STATUS, default='partial')
    aggregated_data  = models.JSONField(
        default=dict,
        help_text=(
            'Mapa {currency_code: {buy, sell, avg, spread_pct, confidence, '
            'sources[], market_type, source_method}} para cada divisa activa.'
        ),
    )
    best_source      = models.CharField(
        max_length=50, blank=True,
        help_text='Fuente más confiable del día (binance/dolarblue/bcb/manual).',
    )
    avg_usd_buy      = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text='Promedio de compra USD/BOB del día.',
    )
    avg_usd_sell     = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text='Promedio de venta USD/BOB del día.',
    )
    max_spread_pct   = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        help_text='Spread máximo registrado durante el día (%).',
    )
    source_count     = models.IntegerField(
        default=0,
        help_text='Número de fuentes activas que reportaron en este snapshot.',
    )
    anomaly_count    = models.IntegerField(
        default=0,
        help_text='Número de anomalías de precio detectadas durante el día.',
    )
    # Tasas de cierre de cada par clave (denormalizadas para consulta rápida)
    close_usd_buy    = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    close_usd_sell   = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    close_eur_buy    = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    close_eur_sell   = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    notes            = models.TextField(blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Snapshot de Tasas'
        verbose_name_plural = 'Snapshots de Tasas'
        ordering            = ['-date']
        indexes             = [
            models.Index(fields=['-date']),
            models.Index(fields=['status', '-date']),
        ]

    def __str__(self):
        return f"RateSnapshot {self.date} USD={self.avg_usd_buy}/{self.avg_usd_sell}"


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
    rate_binance    = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    rate_historical = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    rate_competition = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    # Pesos usados (deben sumar 1.0)
    weight_binance    = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.45'))
    weight_historical = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.35'))
    weight_competition = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.20'))

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


# ─────────────────────────────────────────────────────────────────────────────
#  Integration layer — datos crudos y consenso
# ─────────────────────────────────────────────────────────────────────────────

class ExchangeRateRaw(models.Model):
    """
    Cada dato crudo recibido de una fuente externa.
    Inmutable — nunca se modifica, solo se inserta.
    Activo de ML: conservar indefinidamente (limpiar a S3 tras 90 días).
    """
    fuente           = models.ForeignKey(
        ExchangeRateSource, on_delete=models.PROTECT,
        related_name='raw_rates', null=True, blank=True,
        help_text='Fuente que generó este dato (null si fuente eliminada)',
    )
    id_fuente_str    = models.CharField(max_length=60, db_index=True,
                                         help_text='Copia de id_fuente para búsquedas rápidas sin JOIN')
    moneda_base      = models.CharField(max_length=3, db_index=True)
    moneda_cotizada  = models.CharField(max_length=3, db_index=True)
    precio_compra    = models.DecimalField(max_digits=18, decimal_places=8)
    precio_venta     = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    precio_promedio  = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    spread_pct       = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    timestamp_fuente = models.DateTimeField(
        help_text='Momento en que la fuente dice que es el dato (puede ser aproximado)')
    timestamp_captura = models.DateTimeField(auto_now_add=True, db_index=True)
    payload_raw      = models.JSONField(default=dict,
                                         help_text='JSON original completo — activo de ML')
    es_valido        = models.BooleanField(default=True, db_index=True)
    notas            = models.TextField(blank=True)

    class Meta:
        verbose_name        = 'Dato Crudo de Tasa'
        verbose_name_plural = 'Datos Crudos de Tasas'
        ordering            = ['-timestamp_captura']
        indexes             = [
            models.Index(fields=['moneda_base', 'moneda_cotizada', '-timestamp_captura'],
                         name='rates_raw_pair_ts_idx'),
            models.Index(fields=['id_fuente_str', '-timestamp_captura'],
                         name='rates_raw_fuente_ts_idx'),
            models.Index(fields=['es_valido', 'moneda_base', '-timestamp_captura'],
                         name='rates_raw_valid_idx'),
        ]

    def __str__(self):
        return (f'{self.moneda_base}/{self.moneda_cotizada} '
                f'{self.precio_compra} [{self.id_fuente_str}]')

    def save(self, *args, **kwargs):
        if self.precio_compra and self.precio_venta and not self.precio_promedio:
            self.precio_promedio = (self.precio_compra + self.precio_venta) / Decimal('2')
        if self.precio_compra and self.precio_venta and not self.spread_pct:
            if self.precio_compra > 0:
                self.spread_pct = (
                    (self.precio_venta - self.precio_compra) / self.precio_compra * 100
                ).quantize(Decimal('0.000001'))
        super().save(*args, **kwargs)


class ExchangeRateConsensus(models.Model):
    """
    Tasa de consenso calculada periódicamente a partir de múltiples fuentes.
    Solo uno puede tener vigente=True por par de monedas a la vez.
    """
    METODO_CHOICES = [
        ('MEDIA_PONDERADA',  'Media ponderada por confianza'),
        ('MEDIANA',          'Mediana simple'),
        ('WINSORIZED_MEAN',  'Media Winsorizada (sin outliers)'),
    ]

    par              = models.CharField(max_length=7, db_index=True,
                                         help_text='ej: USD/BOB')
    moneda_base      = models.CharField(max_length=3)
    moneda_cotizada  = models.CharField(max_length=3)
    precio_consenso  = models.DecimalField(max_digits=18, decimal_places=8)
    precio_compra    = models.DecimalField(max_digits=18, decimal_places=8,
                                            null=True, blank=True)
    precio_venta     = models.DecimalField(max_digits=18, decimal_places=8,
                                            null=True, blank=True)
    fuentes_usadas   = models.JSONField(default=list,
                                         help_text='[{id_fuente, peso, precio_compra, precio_venta}]')
    fuentes_count    = models.IntegerField(default=0)
    confianza_pct    = models.IntegerField(default=0,
                                            help_text='0-100: % de confianza del consenso')
    timestamp_calculo = models.DateTimeField(auto_now_add=True, db_index=True)
    metodo_calculo   = models.CharField(max_length=20, choices=METODO_CHOICES,
                                         default='MEDIA_PONDERADA')
    vigente          = models.BooleanField(default=False, db_index=True,
                                            help_text='Solo True para el consenso activo por par')
    cambio_pct_24h   = models.DecimalField(max_digits=8, decimal_places=4,
                                            null=True, blank=True,
                                            help_text='Variación vs consenso de hace 24h (%)')
    tendencia        = models.CharField(max_length=10, blank=True,
                                         help_text='ALCISTA | BAJISTA | NEUTRAL')

    class Meta:
        verbose_name        = 'Consenso de Tasa'
        verbose_name_plural = 'Consensos de Tasas'
        ordering            = ['-timestamp_calculo']
        indexes             = [
            models.Index(fields=['par', '-timestamp_calculo'], name='rates_cons_par_ts_idx'),
            models.Index(fields=['vigente', 'par'],             name='rates_cons_vigente_idx'),
        ]

    def __str__(self):
        return (f'{self.par} consenso={self.precio_consenso} '
                f'fuentes={self.fuentes_count} confianza={self.confianza_pct}%'
                f'{" [VIGENTE]" if self.vigente else ""}')

    def tendencia_display(self) -> str:
        if self.cambio_pct_24h is None:
            return 'NEUTRAL'
        if self.cambio_pct_24h > Decimal('0.1'):
            return 'ALCISTA'
        if self.cambio_pct_24h < Decimal('-0.1'):
            return 'BAJISTA'
        return 'NEUTRAL'


class RawRateSnapshot(models.Model):
    """
    Registro inmutable de cada intento de extracción de tasa por fetcher.
    Alimentado por continuous_fx_extraction; base para métricas de salud del sistema.
    """
    SOURCE_CHOICES = [
        ('binance_p2p',         'Binance P2P'),
        ('dolar_blue_bolivia',  'DolarBlueBolivia'),
        ('airtm',               'AirTM'),
        ('eldorado',            'Eldorado'),
        ('wallbit',             'Wallbit'),
        ('saldoar',             'SaldoAR'),
        ('okx',                 'OKX P2P'),
        ('p2p_exchanges',       'P2P Exchanges'),
        ('p2p_multi_fiat',      'P2P Multi-Fiat'),
        ('digital',             'Digital (Takenos/Airtm)'),
        ('parallel',            'Parallel Scraper'),
        ('dolarapi',            'DolarAPI'),
        ('criptoya',            'Criptoya'),
        ('other',               'Other'),
    ]

    source          = models.CharField(max_length=30, choices=SOURCE_CHOICES, db_index=True)
    currency_pair   = models.CharField(max_length=10, db_index=True,
                                       help_text='ej: USD/BOB, USDT/ARS')
    raw_value       = models.DecimalField(max_digits=18, decimal_places=8,
                                          null=True, blank=True)
    fetched_at      = models.DateTimeField(auto_now_add=True, db_index=True)
    response_time_ms = models.IntegerField(default=0, help_text='Tiempo de respuesta en ms')
    success         = models.BooleanField(default=True, db_index=True)
    error_message   = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name        = 'Snapshot Crudo de Tasa'
        verbose_name_plural = 'Snapshots Crudos de Tasas'
        ordering            = ['-fetched_at']
        indexes             = [
            models.Index(fields=['-fetched_at'],             name='rawsnap_ts_idx'),
            models.Index(fields=['source', 'currency_pair'], name='rawsnap_src_pair_idx'),
            models.Index(fields=['success', '-fetched_at'],  name='rawsnap_ok_ts_idx'),
        ]

    def __str__(self):
        status = 'OK' if self.success else 'ERR'
        return f'[{status}] {self.source} {self.currency_pair} {self.fetched_at:%H:%M:%S}'