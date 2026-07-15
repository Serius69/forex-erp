# analytics/models.py
"""
Modelos de analytics financiero para Kapitalya Casa de Cambio.

ARQUITECTURA:
  TransactionProfitLedger  → P&L por transacción individual (fuente de verdad)
  PnLDailySnapshot         → Agregado diario de P&L (precalculado para performance)
  ExposureSnapshot         → Exposición al riesgo por divisa (snapshot diario)
  SpreadSnapshot           → Histórico de spreads por divisa y tipo de mercado
"""
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.utils import timezone


class TransactionProfitLedger(models.Model):
    """
    Registro de P&L real por cada transacción de cambio.

    METODOLOGÍA WAC (Weighted Average Cost):
      BUY  → la empresa ADQUIERE divisa. Costo = amount_foreign × buy_rate.
              No hay ganancia inmediata; el costo actualiza el WAC del inventario.
              profit_bob = 0
              wac_resultante = nuevo WAC tras incorporar la compra.

      SELL → la empresa ENTREGA divisa. Ingreso = amount_foreign × sell_rate (BOB recibidos).
              Costo de la mercancía = amount_foreign × wac_al_momento_de_venta.
              profit_bob = (sell_rate - wac_at_transaction) × amount_foreign
              Si sell_rate > wac: ganancia positiva (spread favorable).
              Si sell_rate < wac: pérdida (spread insuficiente para cubrir el costo).

    Este ledger es INMUTABLE una vez creado. Nunca se edita.
    La reversa crea un nuevo registro con profit_bob negativo (compensación).
    """
    TX_TYPE = [('BUY', 'Compra'), ('SELL', 'Venta'), ('REVERSAL', 'Reversa')]

    transaction = models.ForeignKey(
        'transactions.Transaction',
        on_delete=models.PROTECT,
        related_name='profit_ledgers',
        help_text=(
            'Transacción origen de este registro de P&L. '
            'Una transacción puede tener dos filas: '
            'la original (BUY/SELL) y la compensación (REVERSAL).'
        ),
    )
    transaction_type  = models.CharField(max_length=8, choices=TX_TYPE)
    currency_code     = models.CharField(max_length=20, db_index=True)  # = Currency.code (codes largos: USD_SMALL_BILLS)
    branch            = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT, related_name='profit_ledgers',
    )
    fecha             = models.DateField(db_index=True)

    # ── Parámetros de la transacción ──────────────────────────────────────────
    amount_foreign    = models.DecimalField(
        max_digits=18, decimal_places=4,
        help_text='Monto en divisa extranjera intercambiado',
    )
    exchange_rate     = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text='Tipo de cambio usado en la transacción (BOB por unidad)',
    )
    amount_bob        = models.DecimalField(
        max_digits=18, decimal_places=2,
        help_text='Bolivianos involucrados en la transacción (amount_from.amount_to)',
    )

    # ── WAC y costo de la mercancía ───────────────────────────────────────────
    wac_at_transaction = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text=(
            'WAC del inventario al momento de la transacción. '
            'Para BUY: WAC ANTES de la compra. '
            'Para SELL: WAC ANTES de la venta (= costo unitario de lo vendido).'
        ),
    )
    wac_after_transaction = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text=(
            'WAC del inventario DESPUÉS de la transacción. '
            'Para BUY: nuevo WAC ponderado. '
            'Para SELL: igual al anterior (WAC no cambia al vender).'
        ),
    )
    cost_bob          = models.DecimalField(
        max_digits=18, decimal_places=2,
        help_text=(
            'Costo contable en BOB de la divisa involucrada. '
            'SELL: amount_foreign × wac_at_transaction. '
            'BUY: amount_foreign × exchange_rate (= lo que pagamos).'
        ),
    )

    # ── P&L ──────────────────────────────────────────────────────────────────
    profit_bob        = models.DecimalField(
        max_digits=18, decimal_places=2,
        help_text=(
            'Ganancia/pérdida neta en BOB. '
            'SELL: amount_bob - cost_bob = (sell_rate - wac) × amount_foreign. '
            'BUY: siempre 0 (la ganancia se realiza al vender).'
        ),
    )
    profit_pct        = models.DecimalField(
        max_digits=8, decimal_places=4, default=Decimal('0'),
        help_text='Margen sobre el costo: profit_bob / cost_bob × 100',
    )
    spread_bob        = models.DecimalField(
        max_digits=10, decimal_places=4, default=Decimal('0'),
        help_text='Spread por unidad: sell_rate - wac (o 0 para BUY)',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'analytics_profit_ledger'
        ordering            = ['-created_at']
        verbose_name        = 'Ledger de Ganancias'
        verbose_name_plural = 'Ledger de Ganancias'
        indexes = [
            models.Index(fields=['currency_code', '-fecha']),
            models.Index(fields=['branch', '-fecha']),
            models.Index(fields=['-fecha', 'transaction_type']),
        ]

    def __str__(self) -> str:
        sign = '+' if self.profit_bob >= 0 else ''
        return (
            f"{self.fecha} | {self.transaction_type} {self.currency_code} "
            f"| {sign}Bs.{self.profit_bob}"
        )


class PnLDailySnapshot(models.Model):
    """
    Snapshot diario de P&L — precalculado para performance en dashboards.

    Se recalcula automáticamente al cierre del día (signal/task) o manualmente.
    No es inmutable: se actualiza si se procesa una reversa del mismo día.

    FÓRMULA:
      ganancia_bruta_bob = ingreso_ventas_bob - costo_ventas_bob
      ganancia_neta_bob  = ganancia_bruta_bob - gastos_operativos_bob

    Donde:
      ingreso_ventas_bob = Σ amount_bob de transacciones SELL completadas del día
      costo_ventas_bob   = Σ cost_bob de TransactionProfitLedger SELL del día
      gastos_operativos  = Σ Gasto.monto_bob del día
    """
    fecha             = models.DateField(db_index=True)
    branch            = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT, related_name='pnl_snapshots',
    )

    # ── Ventas (SELL) ─────────────────────────────────────────────────────────
    num_ventas            = models.IntegerField(default=0)
    ingreso_ventas_bob    = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='BOB recibidos por ventas de divisa',
    )
    costo_ventas_bob      = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='Costo WAC de las divisas vendidas',
    )
    ganancia_bruta_bob    = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='ingreso_ventas - costo_ventas',
    )

    # ── Compras (BUY) — informativo ──────────────────────────────────────────
    num_compras           = models.IntegerField(default=0)
    inversion_compras_bob = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='BOB pagados al comprar divisa (inversión en stock)',
    )

    # ── Gastos operativos ─────────────────────────────────────────────────────
    gastos_operativos_bob = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='Suma de Gastos.monto_bob del día',
    )

    # ── Resultado neto ─────────────────────────────────────────────────────────
    ganancia_neta_bob     = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='ganancia_bruta - gastos_operativos',
    )
    margen_neto_pct       = models.DecimalField(
        max_digits=8, decimal_places=4, default=Decimal('0'),
        help_text='ganancia_neta / ingreso_ventas × 100',
    )

    calculado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table        = 'analytics_pnl_daily'
        unique_together = ['fecha', 'branch']
        ordering        = ['-fecha']
        verbose_name        = 'Snapshot P&L Diario'
        verbose_name_plural = 'Snapshots P&L Diario'
        indexes = [
            models.Index(fields=['branch', '-fecha']),
        ]

    def __str__(self) -> str:
        return f"P&L {self.fecha} | {self.branch} | Bs.{self.ganancia_neta_bob}"


class ExposureSnapshot(models.Model):
    """
    Exposición al riesgo de mercado por divisa — snapshot puntual.

    Exposición = valor de la divisa mantenida, expresado en BOB al precio actual.
    Si el tipo de cambio cae, la exposición (valorizada en BOB) cae → pérdida latente.

    MÉTRICAS:
      exposure_bob       = stock × (sell_rate / scale_factor)  ← valor de mercado
      unrealized_pnl_bob = (sell_rate_unit - wac) × stock     ← ganancia latente si vendiéramos ahora
      pct_of_capital     = exposure_bob / total_capital × 100 ← concentración de riesgo

    ALERTA: si pct_of_capital > umbral (default 60%) → riesgo de concentración.
    """
    ALERT_LEVELS = [
        ('OK',       'Normal'),
        ('WARNING',  'Advertencia'),
        ('CRITICAL', 'Crítico'),
    ]

    timestamp         = models.DateTimeField(db_index=True)
    branch            = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT, related_name='exposure_snapshots',
    )
    currency_code     = models.CharField(max_length=20, db_index=True)  # = Currency.code (codes largos: USD_SMALL_BILLS)
    currency_name     = models.CharField(max_length=100)
    scale_factor      = models.IntegerField(default=1)

    # ── Inventario ────────────────────────────────────────────────────────────
    stock_units       = models.DecimalField(
        max_digits=18, decimal_places=4,
        help_text='Stock en unidades de la divisa (en lotes para CLP/ARS)',
    )
    wac               = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text='Costo promedio ponderado actual (BOB por lote)',
    )

    # ── Valorización de mercado ───────────────────────────────────────────────
    sell_rate_unit    = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text='Tasa de venta por UNIDAD (normalizada por scale_factor)',
    )
    sell_rate_lote    = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text='Tasa de venta por lote (cotizada, antes de normalizar)',
    )
    exposure_bob      = models.DecimalField(
        max_digits=18, decimal_places=2,
        help_text='Valor de mercado total en BOB: stock × sell_rate_unit',
    )

    # ── Riesgo ────────────────────────────────────────────────────────────────
    pct_of_capital    = models.DecimalField(
        max_digits=7, decimal_places=4,
        help_text='% del capital total representado por esta divisa',
    )
    unrealized_pnl_bob = models.DecimalField(
        max_digits=18, decimal_places=2,
        help_text=(
            'Ganancia/pérdida latente: (sell_rate_unit - wac) × stock_units. '
            'Positivo: vendería con ganancia. Negativo: vendería con pérdida.'
        ),
    )
    alert_level       = models.CharField(
        max_length=8, choices=ALERT_LEVELS, default='OK',
    )

    class Meta:
        db_table  = 'analytics_exposure'
        ordering  = ['-timestamp', 'currency_code']
        verbose_name        = 'Snapshot de Exposición'
        verbose_name_plural = 'Snapshots de Exposición'
        indexes = [
            models.Index(fields=['branch', '-timestamp']),
            models.Index(fields=['currency_code', '-timestamp']),
            models.Index(fields=['alert_level', '-timestamp']),
        ]

    def __str__(self) -> str:
        return (
            f"{self.timestamp:%Y-%m-%d %H:%M} | {self.currency_code} "
            f"| Bs.{self.exposure_bob} | {self.pct_of_capital}% | {self.alert_level}"
        )


class SpreadSnapshot(models.Model):
    """
    Histórico de spreads por divisa y tipo de mercado.

    SPREAD = sell_rate - buy_rate (en BOB por unidad cotizada)
    SPREAD_PCT = spread / buy_rate × 100

    Permite analizar:
      - Evolución del spread a lo largo del tiempo
      - Comparación entre mercados (oficial vs paralelo)
      - Alertas si el spread cae por debajo del mínimo rentable
      - Cálculo de prima sobre la tasa oficial BCB
    """
    timestamp         = models.DateTimeField(db_index=True)
    currency_code     = models.CharField(max_length=20, db_index=True)  # = Currency.code (codes largos: USD_SMALL_BILLS)
    market_type       = models.CharField(
        max_length=30,
        help_text='Tipo de mercado: official, bcb, paralelo_digital, etc.',
    )

    # ── Tasas del momento ─────────────────────────────────────────────────────
    buy_rate          = models.DecimalField(max_digits=14, decimal_places=4)
    sell_rate         = models.DecimalField(max_digits=14, decimal_places=4)
    official_rate     = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        help_text='Tasa oficial BCB del momento (para calcular prima)',
    )

    # ── Métricas derivadas ────────────────────────────────────────────────────
    spread_bob        = models.DecimalField(
        max_digits=10, decimal_places=4,
        help_text='Spread en BOB: sell_rate - buy_rate',
    )
    spread_pct        = models.DecimalField(
        max_digits=8, decimal_places=4,
        help_text='Spread porcentual: spread / buy_rate × 100',
    )
    prima_oficial_pct = models.DecimalField(
        max_digits=8, decimal_places=4, default=Decimal('0'),
        help_text='Prima sobre tasa oficial: (sell_rate / official_rate - 1) × 100',
    )

    class Meta:
        db_table  = 'analytics_spread'
        ordering  = ['-timestamp']
        verbose_name        = 'Snapshot de Spread'
        verbose_name_plural = 'Snapshots de Spread'
        indexes = [
            models.Index(fields=['currency_code', '-timestamp']),
            models.Index(fields=['market_type', '-timestamp']),
            models.Index(fields=['currency_code', 'market_type', '-timestamp']),
        ]

    def __str__(self) -> str:
        return (
            f"{self.timestamp:%Y-%m-%d %H:%M} | {self.currency_code} "
            f"[{self.market_type}] spread={self.spread_bob} ({self.spread_pct}%)"
        )


class CapitalAnomalyLog(models.Model):
    """
    Registro persistente de anomalías detectadas por AnomalyDetector.

    Cada fila es inmutable una vez creada.  La resolución se registra con
    resolved=True + resolved_at, no modificando los campos originales.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    REGLAS Y UMBRALES
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    CAPITAL_DROP         — caída de capital en la última hora
      WARNING  : caída ≥ 3 %
      CRITICAL : caída ≥ 5 %

    MISSING_CASH         — discrepancia entre CashFlowLog y CashBOB declarado
      INFO     : sin registro CashBOB para hoy (falta reconteo)
      WARNING  : discrepancia ≥ Bs. 50
      CRITICAL : discrepancia ≥ Bs. 500

    NEGATIVE_BALANCE     — saldo negativo en cualquier cuenta
      CRITICAL : CurrencyInventory.total_balance < 0
      CRITICAL : CapitalComposicion.capital_neto_local < 0
      WARNING  : PnLDailySnapshot.ganancia_neta_bob < -Bs. 200

    RATE_INVERTED        — buy_rate ≥ sell_rate (spread negativo o cero)
      CRITICAL : sell_rate < buy_rate  (spread negativo — nunca debe pasar)
      WARNING  : sell_rate == buy_rate (spread cero — no hay margen)

    RATE_STALE           — tasa sin actualizar durante horario hábil
      WARNING  : sin actualización en > 2 h dentro de 08:00–20:00 Bolivia

    RATE_BCB_DEVIATION   — tasa de mercado muy alejada de la oficial BCB
      WARNING  : desviación ≥ 15 % sobre la oficial
      CRITICAL : desviación ≥ 30 %

    SPREAD_BELOW_MIN     — spread insuficiente para cubrir costos
      WARNING  : spread_pct < 0.30 %

    EXPOSURE_HIGH        — concentración excesiva en una divisa
      WARNING  : divisa > 40 % del capital
      CRITICAL : divisa > 60 % del capital
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """

    # ── Clasificación ─────────────────────────────────────────────────────────
    SEVERITY_CHOICES = [
        ('INFO',     'Información'),
        ('WARNING',  'Advertencia'),
        ('CRITICAL', 'Crítico'),
    ]
    RULE_CHOICES = [
        ('CAPITAL_DROP',       'Caída de capital'),
        ('MISSING_CASH',       'Diferencia en caja'),
        ('NEGATIVE_BALANCE',   'Saldo negativo'),
        ('RATE_INVERTED',      'Spread invertido'),
        ('RATE_STALE',         'Tasa desactualizada'),
        ('RATE_BCB_DEVIATION', 'Desviación sobre BCB'),
        ('SPREAD_BELOW_MIN',   'Spread insuficiente'),
        ('EXPOSURE_HIGH',      'Concentración de riesgo'),
    ]

    rule     = models.CharField(max_length=25, choices=RULE_CHOICES, db_index=True)
    severity = models.CharField(max_length=8,  choices=SEVERITY_CHOICES, db_index=True)

    # ── Contexto ──────────────────────────────────────────────────────────────
    branch   = models.ForeignKey(
        'users.Branch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='anomaly_logs',
    )
    currency = models.CharField(
        max_length=5, blank=True,
        help_text='Divisa involucrada (vacío si es de capital global)',
    )

    # ── Descripción legible ───────────────────────────────────────────────────
    description = models.TextField(help_text='Mensaje legible para el operador')

    # ── Valores que dispararon la alerta ─────────────────────────────────────
    value     = models.DecimalField(
        max_digits=18, decimal_places=4,
        help_text='Valor medido que cruzó el umbral',
    )
    threshold = models.DecimalField(
        max_digits=18, decimal_places=4,
        help_text='Umbral que fue superado',
    )
    details   = models.JSONField(
        default=dict,
        help_text='Datos adicionales: snapshot anterior, tasas, etc.',
    )

    # ── Ciclo de vida ─────────────────────────────────────────────────────────
    resolved    = models.BooleanField(default=False, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='resolved_anomalies',
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table            = 'analytics_anomaly_log'
        ordering            = ['-created_at']
        verbose_name        = 'Anomalía Detectada'
        verbose_name_plural = 'Anomalías Detectadas'
        indexes = [
            models.Index(fields=['severity', '-created_at']),
            models.Index(fields=['rule', '-created_at']),
            models.Index(fields=['branch', '-created_at']),
            models.Index(fields=['resolved', '-created_at']),
        ]

    def __str__(self) -> str:
        branch_str = self.branch.code if self.branch_id else 'GLOBAL'
        return (
            f"[{self.severity}] {self.rule} | {branch_str} | "
            f"{self.created_at:%Y-%m-%d %H:%M} | {self.description[:60]}"
        )


class DecisionLog(models.Model):
    """
    Registro persistente de cada evaluación del motor de decisiones.

    Cada fila representa una llamada a DecisionEngine.evaluar() y es INMUTABLE
    una vez creada, excepto por los campos de outcome (backfilled más tarde).

    OUTCOME EVALUATION:
      Los campos outcome_* se rellenan automáticamente cuando la tasa real
      está disponible (> EVAL_HOURS horas después).  La evaluación es lazy:
      se calcula la primera vez que el registro se consulta desde history/, o
      mediante una tarea periódica de Celery.

      Criterio de corrección:
        COMPRAR  → correcto si la tasa subió > 0.1%
        VENDER   → correcto si la tasa bajó  > 0.1%
        ESPERAR  → correcto si la tasa no movió más de ±1.0%
        SIN_DATOS → no evaluable
    """
    DECISION_CHOICES = [
        ('COMPRAR',   'Comprar'),
        ('VENDER',    'Vender'),
        ('ESPERAR',   'Esperar'),
        ('SIN_DATOS', 'Sin datos'),
    ]
    RIESGO_CHOICES = [
        ('BAJO',  'Bajo'),
        ('MEDIO', 'Medio'),
        ('ALTO',  'Alto'),
        ('N/A',   'N/A'),
    ]

    # ── Contexto de la evaluación ─────────────────────────────────────────────
    timestamp    = models.DateTimeField(auto_now_add=True, db_index=True)
    currency     = models.CharField(max_length=5,  db_index=True)
    branch       = models.ForeignKey(
        'users.Branch', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='decision_logs',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='decision_logs',
    )
    from_cache   = models.BooleanField(
        default=False,
        help_text='True si la respuesta fue servida desde caché Redis.',
    )

    # ── Decisión emitida ──────────────────────────────────────────────────────
    decision      = models.CharField(max_length=10, choices=DECISION_CHOICES, db_index=True)
    confianza     = models.IntegerField(help_text='Confianza 0–100')
    riesgo        = models.CharField(max_length=8, choices=RIESGO_CHOICES)
    precio_compra = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text='Precio de compra recomendado al momento de la decisión',
    )
    precio_venta  = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text='Precio de venta recomendado al momento de la decisión',
    )
    motivo        = models.TextField()
    score_total   = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('0'),
    )

    # ── Snapshot del input utilizado ──────────────────────────────────────────
    input_snapshot = models.JSONField(
        default=dict,
        help_text=(
            'Datos de entrada usados: tasas, spread, stock, volumen, '
            'tendencia, competencia, binance al momento de la decisión.'
        ),
    )
    full_result = models.JSONField(
        default=dict,
        help_text='Resultado completo de DecisionEngine.evaluar() — para trazabilidad.',
    )

    # ── Outcome (backfilled) ──────────────────────────────────────────────────
    outcome_rate         = models.DecimalField(
        max_digits=14, decimal_places=4,
        null=True, blank=True,
        help_text='Tasa de venta real EVAL_HOURS horas después de la decisión.',
    )
    outcome_delta_pct    = models.DecimalField(
        max_digits=8, decimal_places=4,
        null=True, blank=True,
        help_text='% de cambio de la tasa entre la decision y el outcome.',
    )
    decision_was_correct = models.BooleanField(
        null=True,
        help_text='¿La dirección del mercado coincidió con la decisión?',
    )
    outcome_evaluated_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Momento en que se evaluó el outcome.',
    )

    class Meta:
        db_table            = 'analytics_decision_log'
        ordering            = ['-timestamp']
        verbose_name        = 'Decisión Registrada'
        verbose_name_plural = 'Decisiones Registradas'
        indexes = [
            models.Index(fields=['currency', '-timestamp']),
            models.Index(fields=['decision',  '-timestamp']),
            models.Index(fields=['branch',    '-timestamp']),
            models.Index(fields=['decision_was_correct', '-timestamp']),
        ]

    def __str__(self) -> str:
        branch_str = self.branch.code if self.branch_id else 'GLOBAL'
        correct_str = {True: 'OK', False: 'FAIL', None: '?'}.get(self.decision_was_correct, '?')
        return (
            f"{self.timestamp:%Y-%m-%d %H:%M} | {self.currency} "
            f"| {self.decision} ({self.confianza}%) | {branch_str} | {correct_str}"
        )
