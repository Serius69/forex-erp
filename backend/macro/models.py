"""
Series macroeconómicas de Bolivia — datos REALES para contexto y features ML.

Antes de este módulo no existía ningún extractor macro: los campos
inflation_rate/interest_rate/oil_price de predictions.TrainingData quedaban
siempre NULL y los modelos entrenaban con macro=0. Este módulo persiste las
series y `predictions.tasks.update_training_data` las consume.

Fuentes v1 (todas verificadas accesibles desde el contenedor):
  · World Bank API (anual)  — inflación, reservas, PIB, deuda, tasa activa, TC oficial promedio
  · open.er-api.com (diario) — USD/BOB internacional
  · Interna (diaria)         — brecha oficial↔paralelo calculada de ExchangeRate
"""
from django.db import models


class MacroIndicator(models.Model):
    """Un punto (serie, fecha) de un indicador macroeconómico."""

    SERIES_CHOICES = [
        # ── World Bank (anual) ────────────────────────────────────────────────
        ('inflacion_yoy',      'Inflación anual % (WB FP.CPI.TOTL.ZG)'),
        ('reservas_usd',       'Reservas internacionales US$ (WB FI.RES.TOTL.CD)'),
        ('pib_crecimiento',    'Crecimiento PIB % (WB NY.GDP.MKTP.KD.ZG)'),
        ('deuda_externa_usd',  'Deuda externa US$ (WB DT.DOD.DECT.CD)'),
        ('tasa_interes_activa', 'Tasa de interés activa % (WB FR.INR.LEND)'),
        ('tc_oficial_promedio', 'TC oficial promedio anual (WB PA.NUS.FCRF)'),
        # ── Diarias ───────────────────────────────────────────────────────────
        ('usd_internacional',  'USD/BOB internacional (open.er-api.com)'),
        ('tc_oficial_diario',  'TC oficial BCB diario (dolarapi/currency-api)'),
        ('brecha_oficial_pct', 'Brecha oficial↔paralelo % (interna)'),
        ('sentimiento_dolar',  'Sentimiento noticias dólar [-1,1] (RSS)'),
    ]

    series     = models.CharField(max_length=32, choices=SERIES_CHOICES, db_index=True)
    date       = models.DateField(db_index=True)
    value      = models.DecimalField(max_digits=20, decimal_places=6)
    unit       = models.CharField(max_length=20, blank=True, default='')
    source     = models.CharField(max_length=60, blank=True, default='')
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Indicador Macro'
        verbose_name_plural = 'Indicadores Macro'
        unique_together     = [('series', 'date')]
        ordering            = ['-date']
        indexes             = [
            models.Index(fields=['series', '-date'], name='macro_series_date_idx'),
        ]

    def __str__(self):
        return f'{self.series} {self.date}: {self.value}'

    @classmethod
    def latest(cls, series: str):
        """Último punto de una serie (o None)."""
        return cls.objects.filter(series=series).order_by('-date').first()

    @classmethod
    def latest_value_map(cls) -> dict:
        """{series: value} con el último punto de cada serie — para features ML."""
        out = {}
        for series, _label in cls.SERIES_CHOICES:
            row = cls.latest(series)
            if row is not None:
                out[series] = row.value
        return out


class NewsItem(models.Model):
    """
    Noticia relevante al mercado cambiario boliviano (vía RSS de Google News).

    `sentiment` ∈ [-1, 1]: >0 = presión ALCISTA sobre el dólar paralelo
    (escasez, devaluación, crisis); <0 = presión BAJISTA (desembolsos,
    estabilización, suben reservas). Scoring por keywords en español
    (determinista y auditable — sin LLM).
    """
    title        = models.CharField(max_length=400)
    url          = models.URLField(max_length=600, unique=True)
    source       = models.CharField(max_length=120, blank=True, default='')
    published_at = models.DateTimeField(db_index=True)
    sentiment    = models.FloatField(default=0.0)
    keywords     = models.JSONField(default=list, blank=True)
    query        = models.CharField(max_length=80, blank=True, default='')
    fetched_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'Noticia'
        verbose_name_plural = 'Noticias'
        ordering            = ['-published_at']
        indexes             = [
            models.Index(fields=['-published_at'], name='news_pub_idx'),
            models.Index(fields=['sentiment', '-published_at'], name='news_sent_idx'),
        ]

    def __str__(self):
        return f'[{self.sentiment:+.2f}] {self.title[:60]}'
