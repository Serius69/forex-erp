# capital/models.py
"""
Modelos para control de capital y gastos operativos.

Capital total = efectivo_bob + qr_bob + divisas_bob + tarjetas_bob - pasivos_bob

Donde:
  divisas_bob = sum(inventario_divisa × tasa_venta_actual)  ← valor de mercado
  tarjetas_bob = sum(inventario_tarjeta × precio_venta_prom)← valor a precio de venta
"""
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.utils import timezone


class Gasto(models.Model):
    """
    Gasto operativo del negocio (alquiler, servicios, comisiones, etc.)
    Reduce el capital efectivo disponible.
    """
    CATEGORIAS = [
        ('ALQUILER',     'Alquiler'),
        ('SERVICIOS',    'Servicios básicos'),
        ('SUELDOS',      'Sueldos y salarios'),
        ('COMISIONES',   'Comisiones'),
        ('PUBLICIDAD',   'Publicidad y marketing'),
        ('IMPUESTOS',    'Impuestos y tasas'),
        ('SUMINISTROS',  'Suministros y materiales'),
        ('MANTENIMIENTO','Mantenimiento'),
        ('TRANSPORTE',   'Transporte y logística'),
        ('BANCO',        'Comisiones bancarias'),
        ('OTROS',        'Otros gastos'),
    ]
    MEDIOS_PAGO = [
        ('EFECTIVO', 'Efectivo'),
        ('QR',       'QR / Billetera digital'),
        ('TRANSFER', 'Transferencia bancaria'),
        ('TARJETA',  'Tarjeta de débito/crédito'),
    ]

    fecha       = models.DateField(default=timezone.localdate)
    categoria   = models.CharField(max_length=20, choices=CATEGORIAS)
    descripcion = models.CharField(max_length=300)
    monto_bob   = models.DecimalField(
        max_digits=15, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Monto del gasto en BOB'
    )
    medio_pago  = models.CharField(max_length=10, choices=MEDIOS_PAGO, default='EFECTIVO')
    proveedor   = models.CharField(max_length=200, blank=True)
    nro_factura = models.CharField(max_length=50, blank=True)
    notas       = models.TextField(blank=True)
    branch      = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT, related_name='gastos'
    )
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='gastos_registrados'
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'capital_gasto'
        ordering            = ['-fecha', '-created_at']
        verbose_name        = 'Gasto'
        verbose_name_plural = 'Gastos'
        indexes = [
            models.Index(fields=['-fecha']),
            models.Index(fields=['categoria', '-fecha']),
            models.Index(fields=['branch', '-fecha']),
        ]

    def __str__(self):
        return f"{self.fecha} | {self.get_categoria_display()} | Bs. {self.monto_bob}"


class IngresoExtra(models.Model):
    """
    Ingreso no cambiario (ventas indirectas, comisiones, 'caiditas', intereses).
    Aumenta el capital efectivo disponible. Contraparte de Gasto.
    """
    fecha       = models.DateField(default=timezone.localdate)
    tipo        = models.CharField(
        max_length=50,
        help_text="Concepto libre: Venta indirecta, Caiditas, Comisión, Interés, etc."
    )
    monto_bob   = models.DecimalField(
        max_digits=15, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Monto del ingreso en BOB'
    )
    medio_pago  = models.CharField(max_length=10, choices=Gasto.MEDIOS_PAGO, default='EFECTIVO')
    notas       = models.TextField(blank=True)
    branch      = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT, related_name='ingresos_extra'
    )
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ingresos_registrados'
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'capital_ingreso_extra'
        ordering            = ['-fecha', '-created_at']
        verbose_name        = 'Ingreso Extra'
        verbose_name_plural = 'Ingresos Extra'
        indexes = [
            models.Index(fields=['-fecha']),
            models.Index(fields=['branch', '-fecha']),
        ]

    def __str__(self):
        return f"{self.fecha} | {self.tipo} | Bs. {self.monto_bob}"


class CapitalSnapshot(models.Model):
    """
    Instantánea del capital total en un momento dado.
    Se crea al cerrar el día o manualmente.

    Permite:
    - Historial de capital
    - Detectar discrepancias (capital esperado vs real)
    - Auditoría financiera
    """
    fecha           = models.DateField()
    branch          = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT, related_name='capital_snapshots'
    )

    # Componentes del capital (todos en BOB)
    efectivo_bob    = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    qr_bob          = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                          help_text='Saldo en billeteras QR / cuentas digitales')
    divisas_bob     = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                          help_text='Valor de las divisas al TC de venta')
    tarjetas_bob    = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                          help_text='Valor inventario tarjetas al precio de venta prom')
    pasivos_bob     = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                          help_text='Deudas / créditos a pagar')
    total_bob       = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                          help_text='efectivo + qr + divisas + tarjetas - pasivos')

    # Detalle en JSON para auditoría
    detalle_divisas   = models.JSONField(default=dict, help_text='Desglose por divisa')
    detalle_tarjetas  = models.JSONField(default=dict, help_text='Desglose por tipo de tarjeta')

    # Tipo de snapshot
    TIPO_CHOICES = [
        ('CIERRE',  'Cierre de día'),
        ('MANUAL',  'Manual / Ad-hoc'),
        ('APERTURA','Apertura de día'),
    ]
    tipo            = models.CharField(max_length=10, choices=TIPO_CHOICES, default='MANUAL')
    notas           = models.TextField(blank=True)
    generado_por    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='snapshots_capital'
    )
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'capital_snapshot'
        ordering            = ['-fecha', '-created_at']
        verbose_name        = 'Snapshot de Capital'
        verbose_name_plural = 'Snapshots de Capital'
        indexes = [
            models.Index(fields=['-fecha', 'branch']),
        ]

    def __str__(self):
        return f"Capital {self.fecha} | {self.branch} | Bs. {self.total_bob}"


class CapitalManualEntry(models.Model):
    """
    Saldo manual de efectivo, QR y pasivos — editable como Excel.
    Representa el estado ACTUAL de la caja física y digital.

    A diferencia de CapitalSnapshot (instantáneas históricas),
    este modelo almacena el saldo vigente y mantiene historial de ediciones.
    """
    branch       = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT, related_name='capital_manual_entries'
    )
    fecha        = models.DateField(default=timezone.localdate)
    efectivo_bob = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='Efectivo físico en caja BOB',
    )
    qr_bob       = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='Saldo en billeteras QR / cuentas digitales BOB',
    )
    pasivos_bob  = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='Deudas / obligaciones a pagar en BOB',
    )
    notas        = models.TextField(blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='capital_entries',
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'capital_manual_entry'
        ordering            = ['-fecha', '-updated_at']
        verbose_name        = 'Entrada Manual de Capital'
        verbose_name_plural = 'Entradas Manuales de Capital'
        # Una entrada por sucursal por día (única vigente)
        unique_together     = ['branch', 'fecha']
        indexes = [
            models.Index(fields=['branch', '-fecha']),
        ]

    def __str__(self):
        return (
            f"{self.fecha} | {self.branch} | "
            f"EFE: {self.efectivo_bob} | QR: {self.qr_bob}"
        )


class CapitalComposicion(models.Model):
    """
    Desglose detallado del efectivo físico y digital en caja.

    TOTAL EFECTIVO BOB = fuertes + caja_chica + monedas + rotos + sueltos
    TOTAL ACTIVOS      = total_efectivo + qr_transferencias + tarjetas_telefonicas + divisas_bob (calc)
    CAPITAL NETO       = total_activos - pasivos

    Una entrada por sucursal por día (única vigente).
    El historial de cambios se mantiene en CapitalComposicionHistory.
    """
    branch    = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT,
        related_name='capital_composiciones',
    )
    fecha     = models.DateField(default=timezone.localdate)

    # ── Efectivo físico BOB (billetes y monedas) ──────────────────────────────
    fuertes   = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text='Billetes de 200, 100, 50 BOB (denominación alta)',
    )
    caja_chica = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text='Billetes de 20, 10 BOB',
    )
    monedas   = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text='Monedas de 5, 2, 1, 0.50, 0.20, 0.10 BOB',
    )
    rotos     = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text='Billetes dañados, rasgados o muy usados (se aceptan al 100%)',
    )
    sueltos   = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text='Billetes sueltos sin clasificar',
    )

    # ── Digital ───────────────────────────────────────────────────────────────
    qr_transferencias = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text='Saldo en billeteras QR y cuentas de transferencia',
    )
    tarjetas_telefonicas = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text='Valor en BOB del stock de tarjetas telefónicas en caja',
    )

    # ── Pasivos ───────────────────────────────────────────────────────────────
    pasivos   = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text='Deudas con acreedores / obligaciones a pagar',
    )

    notas     = models.TextField(blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='capital_composiciones',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table        = 'capital_composicion'
        unique_together = ['branch', 'fecha']
        ordering        = ['-fecha', '-updated_at']
        verbose_name        = 'Composición de Capital'
        verbose_name_plural = 'Composiciones de Capital'
        indexes = [
            models.Index(fields=['branch', '-fecha']),
        ]

    def __str__(self):
        return f"{self.fecha} | {self.branch} | EFE: {self.total_efectivo} | NET: {self.total_activos}"

    # ── Propiedades calculadas ────────────────────────────────────────────────

    @property
    def total_efectivo(self) -> Decimal:
        """Suma de todo el efectivo físico en BOB."""
        return (
            self.fuertes + self.caja_chica + self.monedas
            + self.rotos  + self.sueltos
        )

    @property
    def total_digital(self) -> Decimal:
        """Efectivo digital (QR + tarjetas telefónicas)."""
        return self.qr_transferencias + self.tarjetas_telefonicas

    @property
    def total_activos(self) -> Decimal:
        """Activos controlables desde esta composición (sin divisas extranjeras)."""
        return self.total_efectivo + self.total_digital

    @property
    def capital_neto_local(self) -> Decimal:
        """Capital neto SIN divisas extranjeras."""
        return self.total_activos - self.pasivos

    @property
    def total_bob(self) -> Decimal:
        """Alias de capital_neto_local para compatibilidad con dashboard."""
        return self.capital_neto_local

    def to_snapshot_dict(self) -> dict:
        """Serializes this composicion to a JSON-safe dict for history snapshots."""
        return {
            'fuertes':              str(self.fuertes),
            'caja_chica':           str(self.caja_chica),
            'monedas':              str(self.monedas),
            'rotos':                str(self.rotos),
            'sueltos':              str(self.sueltos),
            'qr_transferencias':    str(self.qr_transferencias),
            'tarjetas_telefonicas': str(self.tarjetas_telefonicas),
            'pasivos':              str(self.pasivos),
            'notas':                self.notas,
        }


class CapitalComposicionHistory(models.Model):
    """Historial inmutable de cambios en CapitalComposicion — append-only."""
    composicion = models.ForeignKey(
        CapitalComposicion, on_delete=models.CASCADE, related_name='history',
    )
    # Snapshot prev/new para auditoría completa
    snapshot_prev = models.JSONField(
        help_text='Estado previo completo {fuertes, caja_chica, ...}'
    )
    snapshot_new  = models.JSONField(
        help_text='Estado nuevo completo {fuertes, caja_chica, ...}'
    )
    motivo        = models.CharField(max_length=300, blank=True)
    modificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
    )
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'capital_composicion_history'
        ordering = ['-created_at']
        verbose_name        = 'Historial Composición'
        verbose_name_plural = 'Historial Composiciones'


class CapitalEntryHistory(models.Model):
    """Historial de cambios en CapitalManualEntry — inmutable (append-only)."""
    entry        = models.ForeignKey(
        CapitalManualEntry, on_delete=models.CASCADE, related_name='history'
    )
    efectivo_bob_prev = models.DecimalField(max_digits=18, decimal_places=2)
    qr_bob_prev      = models.DecimalField(max_digits=18, decimal_places=2)
    pasivos_bob_prev = models.DecimalField(max_digits=18, decimal_places=2)
    efectivo_bob_new = models.DecimalField(max_digits=18, decimal_places=2)
    qr_bob_new       = models.DecimalField(max_digits=18, decimal_places=2)
    pasivos_bob_new  = models.DecimalField(max_digits=18, decimal_places=2)
    motivo           = models.CharField(max_length=300, blank=True)
    modificado_por   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
    )
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'capital_entry_history'
        ordering  = ['-created_at']
        verbose_name        = 'Historial de Capital'
        verbose_name_plural = 'Historial de Capital'


class CashBOB(models.Model):
    """
    Composición física del efectivo BOB clasificada por ubicación y denominación.

    FUERTES     — caja fuerte, billetes de 200/100/50 Bs.
    SUELTOS     — caja fuerte, billetes operativos de 20/10 Bs.
    CAJA CHICA  — cajero, billetes mixtos (200→10 Bs).
    QR/TRANSFER — saldo digital (puede tener centavos).

    Una entrada por sucursal por día.  El historial de ediciones queda en
    CapitalComposicionHistory a través de sync_to_composicion().
    """
    branch = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT, related_name='cash_bob_entries',
    )
    fecha = models.DateField(default=timezone.localdate)

    # ── Fuertes (caja fuerte, denominaciones altas) ───────────────────────────
    fuertes_200 = models.PositiveIntegerField(default=0, help_text='Cantidad de billetes de 200 Bs')
    fuertes_100 = models.PositiveIntegerField(default=0, help_text='Cantidad de billetes de 100 Bs')
    fuertes_50  = models.PositiveIntegerField(default=0, help_text='Cantidad de billetes de 50 Bs')

    # ── Sueltos (caja fuerte, denominaciones operativas) ─────────────────────
    sueltos_20 = models.PositiveIntegerField(default=0, help_text='Cantidad de billetes de 20 Bs')
    sueltos_10 = models.PositiveIntegerField(default=0, help_text='Cantidad de billetes de 10 Bs')

    # ── Caja chica (cajero, denominaciones mixtas) ───────────────────────────
    caja_chica_200 = models.PositiveIntegerField(default=0)
    caja_chica_100 = models.PositiveIntegerField(default=0)
    caja_chica_50  = models.PositiveIntegerField(default=0)
    caja_chica_20  = models.PositiveIntegerField(default=0)
    caja_chica_10  = models.PositiveIntegerField(default=0)

    # ── Digital ───────────────────────────────────────────────────────────────
    qr_transferencias = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text='Saldo en billeteras QR / transferencias bancarias',
    )

    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='cash_bob_entries',
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table        = 'capital_cash_bob'
        unique_together = ['branch', 'fecha']
        ordering        = ['-fecha', '-updated_at']
        verbose_name        = 'Caja BOB'
        verbose_name_plural = 'Cajas BOB'
        indexes = [
            models.Index(fields=['branch', '-fecha']),
        ]

    def __str__(self):
        return (
            f"{self.fecha} | {self.branch} | "
            f"EFE: {self.total_efectivo_fisico()} | QR: {self.qr_transferencias}"
        )

    # ── Cálculos ──────────────────────────────────────────────────────────────

    def total_fuertes(self) -> Decimal:
        """Valor total de billetes en caja fuerte (200+100+50 Bs)."""
        return Decimal(
            self.fuertes_200 * 200
            + self.fuertes_100 * 100
            + self.fuertes_50 * 50
        )

    def total_sueltos(self) -> Decimal:
        """Valor total de billetes sueltos en caja fuerte (20+10 Bs)."""
        return Decimal(self.sueltos_20 * 20 + self.sueltos_10 * 10)

    def total_caja_chica(self) -> Decimal:
        """Valor total de billetes en cajero (denominaciones mixtas)."""
        return Decimal(
            self.caja_chica_200 * 200
            + self.caja_chica_100 * 100
            + self.caja_chica_50 * 50
            + self.caja_chica_20 * 20
            + self.caja_chica_10 * 10
        )

    def total_efectivo_fisico(self) -> Decimal:
        """Efectivo físico total (fuertes + sueltos + caja chica)."""
        return self.total_fuertes() + self.total_sueltos() + self.total_caja_chica()

    def total_general_bob(self) -> Decimal:
        """Total BOB = efectivo físico + QR/transferencias."""
        return self.total_efectivo_fisico() + self.qr_transferencias


class CurrencyPosition(models.Model):
    """
    Posición neta por divisa en una sucursal.

    Actualizada automáticamente al completar cada Transaction.
    Permite calcular P&L no realizado a tasa paralela y oficial.

    Una entrada por (branch, currency).
    """
    branch   = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT,
        related_name='currency_positions',
    )
    currency = models.ForeignKey(
        'rates.Currency', on_delete=models.PROTECT,
        related_name='positions',
    )

    # ── Posición ──────────────────────────────────────────────────────────────
    net_position = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal('0'),
        help_text='Posición neta en unidades de la divisa (+ = largo, - = corto).',
    )
    avg_acquisition_cost = models.DecimalField(
        max_digits=10, decimal_places=4, default=Decimal('0'),
        help_text='Costo promedio de adquisición en BOB (WAC).',
    )
    total_bought    = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('0'))
    total_sold      = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('0'))
    total_cost_bob  = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='Costo total acumulado en BOB (para calcular WAC).',
    )

    # ── P&L no realizado (calculado al momento del snapshot) ─────────────────
    unrealized_pnl_parallel  = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='P&L no realizado valorizado a tasa paralela.',
    )
    unrealized_pnl_official  = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal('0'),
        help_text='P&L no realizado valorizado a tasa paralela (alias histórico, igual a unrealized_pnl_parallel).',
    )
    parallel_rate_used  = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    official_rate_used  = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text='Alias histórico — almacena la tasa paralela usada (BCB eliminado).',
    )

    last_tx_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table        = 'capital_currency_position'
        unique_together = [('branch', 'currency')]
        ordering        = ['branch', 'currency__code']
        verbose_name        = 'Posición por Divisa'
        verbose_name_plural = 'Posiciones por Divisa'
        indexes = [
            models.Index(fields=['branch', 'currency']),
        ]

    def __str__(self):
        sign = '+' if self.net_position >= 0 else ''
        return f'{self.branch} | {self.currency.code} {sign}{self.net_position}'

    def apply_buy(self, amount: Decimal, rate_bob: Decimal) -> None:
        """Empresa compra divisa: aumenta posición, actualiza WAC."""
        self.total_bought  += amount
        self.total_cost_bob += amount * rate_bob
        self.net_position  += amount
        if self.net_position > 0:
            self.avg_acquisition_cost = self.total_cost_bob / self.net_position
        self.last_tx_at = timezone.now()

    def apply_sell(self, amount: Decimal, rate_bob: Decimal) -> None:
        """Empresa vende divisa: reduce posición.

        La venta consume costo al WAC vigente (COGS) — reduce total_cost_bob sin
        tocar avg_acquisition_cost (bajo WAC el costo unitario no cambia al vender).
        Antes no reducía total_cost_bob → se rompía la invariante
        total_cost_bob == net_position * avg_acquisition_cost y una compra
        posterior inflaba el WAC de forma permanente.
        """
        cogs = min(amount * self.avg_acquisition_cost, self.total_cost_bob)
        self.total_sold    += amount
        self.net_position  -= amount
        self.total_cost_bob -= cogs
        self.last_tx_at     = timezone.now()

    def update_unrealized_pnl(self, parallel_rate: Decimal, official_rate: Decimal = None) -> None:
        """Recalcula el P&L no realizado a tasa paralela. official_rate ignorado (BCB eliminado)."""
        book_value = self.net_position * self.avg_acquisition_cost
        market_value = self.net_position * parallel_rate
        pnl = market_value - book_value
        self.unrealized_pnl_parallel = pnl
        self.unrealized_pnl_official = pnl  # mismo valor — BCB eliminado
        self.parallel_rate_used = parallel_rate
        self.official_rate_used = parallel_rate  # alias histórico


class CurrencyPositionHistory(models.Model):
    """Snapshot diario de la posición por divisa — append-only."""
    position    = models.ForeignKey(CurrencyPosition, on_delete=models.PROTECT, related_name='history')
    fecha       = models.DateField(db_index=True)
    net_position = models.DecimalField(max_digits=18, decimal_places=4)
    avg_acquisition_cost = models.DecimalField(max_digits=10, decimal_places=4)
    unrealized_pnl_parallel = models.DecimalField(max_digits=18, decimal_places=2)
    unrealized_pnl_official = models.DecimalField(max_digits=18, decimal_places=2)
    parallel_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True)
    official_rate = models.DecimalField(
        max_digits=10, decimal_places=4, null=True,
        help_text='Alias histórico — almacena la tasa paralela (BCB eliminado).',
    )
    snapshot_type = models.CharField(max_length=10, choices=[('DAILY', 'Diario'), ('MANUAL', 'Manual')], default='DAILY')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'capital_currency_position_history'
        ordering  = ['-fecha', '-created_at']
        verbose_name        = 'Historial Posición Divisa'
        verbose_name_plural = 'Historial Posiciones Divisa'
        indexes = [models.Index(fields=['position', '-fecha'])]


class CashFlowLog(models.Model):
    """
    Registro inmutable de flujo de efectivo BOB generado por transacciones de cambio.

    Cada transacción BUY/SELL produce exactamente un CashFlowLog:
      BUY  → tipo='OUT', empresa paga BOB al cliente
      SELL → tipo='IN',  empresa recibe BOB del cliente

    Las reversas producen un log de compensación con el tipo opuesto.

    Permite:
      - Auditoría completa de todos los movimientos de caja originados en transacciones
      - Reconstruir el saldo cronológico de cualquier campo de CapitalComposicion
      - Detectar discrepancias entre el saldo contable y el físico
    """
    TIPO_CHOICES = [
        ('IN',  'Entrada de efectivo'),
        ('OUT', 'Salida de efectivo'),
    ]

    # ── Origen ────────────────────────────────────────────────────────────────
    transaction = models.ForeignKey(
        'transactions.Transaction',
        on_delete=models.PROTECT,
        related_name='cash_flow_logs',
        help_text='Transacción que originó este movimiento de caja',
    )
    tipo = models.CharField(
        max_length=3,
        choices=TIPO_CHOICES,
        db_index=True,
    )
    concepto = models.CharField(
        max_length=300,
        help_text='Descripción legible: "COMPRA USD × 100", "REVERSA VENTA EUR × 50", etc.',
    )

    # ── Monto y campo afectado ────────────────────────────────────────────────
    monto_bob = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Monto absoluto en BOB (siempre positivo; tipo indica dirección)',
    )
    campo_afectado = models.CharField(
        max_length=30,
        help_text=(
            'Campo de CapitalComposicion modificado: '
            '"fuertes", "qr_transferencias", etc.'
        ),
    )

    # ── Saldo antes / después ─────────────────────────────────────────────────
    saldo_anterior   = models.DecimalField(
        max_digits=18, decimal_places=2,
        help_text='Valor del campo antes de aplicar la transacción',
    )
    saldo_resultante = models.DecimalField(
        max_digits=18, decimal_places=2,
        help_text='Valor del campo después de aplicar la transacción',
    )

    # ── Contexto ──────────────────────────────────────────────────────────────
    branch   = models.ForeignKey(
        'users.Branch',
        on_delete=models.PROTECT,
        related_name='cash_flow_logs',
    )
    fecha    = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table            = 'capital_cashflow_log'
        ordering            = ['-created_at']
        verbose_name        = 'Log de Flujo de Caja'
        verbose_name_plural = 'Logs de Flujo de Caja'
        indexes = [
            models.Index(fields=['branch', '-fecha']),
            models.Index(fields=['transaction']),
            models.Index(fields=['tipo', '-fecha']),
        ]

    def __str__(self) -> str:
        sign = '+' if self.tipo == 'IN' else '-'
        return f"{self.fecha} | {sign}Bs.{self.monto_bob} | {self.concepto}"


# ── Cuentas por pagar (acreedores) ──────────────────────────────────────────
# Migrado del sheet legado: ledger "Fecha | Acreedor | Monto Acreditado Bs" +
# bloque de pasivos de la composición de capital. El saldo NO se guarda: se deriva
# de los MovimientoAcreedor (cargos − abonos) para evitar denormalización que drifte.

class Acreedor(models.Model):
    """Acreedor / proveedor al que se le debe (cuenta por pagar). Un acreedor puede
    llevarse en BOB o en divisa (p.ej. 'Acreedor 2 dolar' del sheet)."""
    MONEDA_CHOICES = [('BOB', 'Bolivianos'), ('USD', 'Dólares')]

    nombre     = models.CharField(max_length=200)
    moneda     = models.CharField(max_length=3, choices=MONEDA_CHOICES, default='BOB',
                                  help_text='Moneda en que se lleva la deuda con este acreedor.')
    documento  = models.CharField(max_length=50, blank=True, help_text='NIT/CI (opcional).')
    is_active  = models.BooleanField(default=True, db_index=True)
    notas      = models.TextField(blank=True)
    branch     = models.ForeignKey('users.Branch', on_delete=models.PROTECT,
                                   related_name='acreedores')
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Acreedor'
        verbose_name_plural = 'Acreedores'
        ordering            = ['nombre']
        indexes = [models.Index(fields=['branch', 'is_active'], name='capital_acr_branch__b3f6d1_idx')]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.moneda})"


class MovimientoAcreedor(models.Model):
    """Movimiento del ledger de un acreedor: CARGO aumenta la deuda, ABONO la paga."""
    TIPO_CHOICES = [
        ('CARGO', 'Cargo — nueva deuda'),
        ('ABONO', 'Abono — pago al acreedor'),
    ]
    acreedor     = models.ForeignKey(Acreedor, on_delete=models.CASCADE, related_name='movimientos')
    fecha        = models.DateField(default=timezone.localdate)
    tipo         = models.CharField(max_length=6, choices=TIPO_CHOICES)
    monto_bob    = models.DecimalField(max_digits=18, decimal_places=2,
                                       validators=[MinValueValidator(Decimal('0.01'))])
    monto_divisa = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True,
                                       help_text='Monto en la moneda del acreedor si es ≠ BOB.')
    concepto     = models.CharField(max_length=300, blank=True)
    notas        = models.TextField(blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='+')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Movimiento de acreedor'
        verbose_name_plural = 'Movimientos de acreedores'
        ordering            = ['-fecha', '-created_at']
        indexes = [
            models.Index(fields=['acreedor', '-fecha'], name='capital_mov_acreed_e7a8b9_idx'),
            models.Index(fields=['tipo', '-fecha'], name='capital_mov_tipo_fe_c1d2e3_idx'),
        ]

    def __str__(self) -> str:
        sign = '+' if self.tipo == 'CARGO' else '-'
        return f"{self.fecha} | {self.acreedor.nombre} | {sign}Bs.{self.monto_bob}"


# ── Caja chica (ledger de fondo fijo) ───────────────────────────────────────
# En el sheet era una LÍNEA de saldo con drift (11.640 / 22.549 corte / 16.510).
# Acá se vuelve un ledger real: APERTURA fija el corte, INGRESO/EGRESO lo mueven.

class MovimientoCajaChica(models.Model):
    """Ledger de caja chica. Saldo = Σ(APERTURA+INGRESO) − Σ(EGRESO) por sucursal."""
    TIPO_CHOICES = [
        ('APERTURA', 'Apertura / corte inicial'),
        ('INGRESO',  'Ingreso / reposición'),
        ('EGRESO',   'Egreso / gasto'),
    ]
    fecha       = models.DateField(default=timezone.localdate)
    tipo        = models.CharField(max_length=8, choices=TIPO_CHOICES, default='EGRESO')
    monto_bob   = models.DecimalField(max_digits=18, decimal_places=2,
                                      validators=[MinValueValidator(Decimal('0.01'))])
    concepto    = models.CharField(max_length=300)
    notas       = models.TextField(blank=True)
    branch      = models.ForeignKey('users.Branch', on_delete=models.PROTECT,
                                    related_name='movimientos_caja_chica')
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='+')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Movimiento de caja chica'
        verbose_name_plural = 'Movimientos de caja chica'
        ordering            = ['-fecha', '-created_at']
        indexes = [
            models.Index(fields=['branch', '-fecha'], name='capital_ccc_branch__a1e2c3_idx'),
            models.Index(fields=['tipo', '-fecha'], name='capital_ccc_tipo_fe_d4f5a6_idx'),
        ]

    def __str__(self) -> str:
        sign = '-' if self.tipo == 'EGRESO' else '+'
        return f"{self.fecha} | caja chica | {sign}Bs.{self.monto_bob} | {self.concepto}"
