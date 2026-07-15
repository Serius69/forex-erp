# tarjetas/models.py
"""
Módulo de gestión de tarjetas telefónicas prepago.
Kapitalya compra lotes de tarjetas y las vende individualmente.

Lógica financiera:
  Ganancia = (precio_venta - precio_costo_prom) × unidades_vendidas
  Inventario = compras_acumuladas - ventas_acumuladas
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
from django.db import transaction as db_tx

User = get_user_model()

MONEY_Q = Decimal('0.01')


class TipoTarjeta(models.Model):
    """
    Catálogo de tipos/denominaciones de tarjetas.
    Ej: Tigo 5 BOB, Viva 10 BOB, Claro 20 BOB.
    """
    OPERADORAS = [
        ('TIGO',   'Tigo'),
        ('VIVA',   'Viva'),
        ('CLARO',  'Claro'),
        ('ENTEL',  'Entel'),
        ('OTRA',   'Otra'),
    ]

    # Aislamiento multi-tenant: el catálogo (y por FK, lotes/ventas/movimientos)
    # pertenece a una empresa. null solo para datos legados pre-migración.
    company         = models.ForeignKey(
        'tenants.Company', on_delete=models.PROTECT,
        related_name='tipos_tarjeta', null=True, blank=True,
    )
    operadora       = models.CharField(max_length=10, choices=OPERADORAS)
    nombre          = models.CharField(max_length=100, help_text="Ej: Tigo 5 BOB")
    denominacion    = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Valor nominal en BOB"
    )
    descripcion     = models.TextField(blank=True)
    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'tarjetas_tipo'
        ordering            = ['operadora', 'denominacion']
        unique_together     = ['company', 'operadora', 'denominacion']
        verbose_name        = 'Tipo de Tarjeta'
        verbose_name_plural = 'Tipos de Tarjeta'
        indexes             = [
            models.Index(fields=['operadora', 'is_active']),
            models.Index(fields=['company', 'is_active']),
        ]

    def __str__(self):
        return f"{self.nombre} (Bs. {self.denominacion})"

    @property
    def stock_actual(self) -> int:
        """Stock disponible = comprado - vendido."""
        comprado = self.lotes.filter(
            is_active=True
        ).aggregate(total=models.Sum('cantidad_restante'))['total'] or 0
        return int(comprado)

    @property
    def costo_promedio(self) -> Decimal:
        """Costo promedio ponderado de las unidades en stock."""
        lotes_activos = self.lotes.filter(
            is_active=True, cantidad_restante__gt=0
        )
        total_unidades = Decimal('0')
        total_costo    = Decimal('0')
        for lote in lotes_activos:
            total_unidades += lote.cantidad_restante
            total_costo    += lote.cantidad_restante * lote.precio_costo
        if total_unidades == 0:
            return Decimal('0')
        return (total_costo / total_unidades).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

    @property
    def valor_inventario_bob(self) -> Decimal:
        """Valor total del inventario a costo (BOB)."""
        return (self.costo_promedio * self.stock_actual).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


class LoteCompra(models.Model):
    """
    Lote de tarjetas comprado a un proveedor.
    Se usa FIFO para determinar el costo de cada venta.
    """
    tipo_tarjeta    = models.ForeignKey(
        TipoTarjeta, on_delete=models.PROTECT, related_name='lotes'
    )
    proveedor       = models.CharField(max_length=200, default='Proveedor')
    cantidad_total  = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    cantidad_restante = models.PositiveIntegerField()   # decrementado en cada venta
    precio_costo    = models.DecimalField(
        max_digits=10, decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))],
        help_text="Precio de costo por tarjeta en BOB"
    )
    # Factura del proveedor
    numero_factura  = models.CharField(max_length=50, blank=True)
    fecha_compra    = models.DateField(default=timezone.localdate)
    # Auditoría
    registrado_por  = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='lotes_registrados'
    )
    is_active       = models.BooleanField(default=True)  # False cuando se agota
    notas           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'tarjetas_lote'
        ordering            = ['fecha_compra', 'id']   # FIFO por fecha
        verbose_name        = 'Lote de Compra'
        verbose_name_plural = 'Lotes de Compra'
        indexes = [
            models.Index(fields=['tipo_tarjeta', 'is_active', 'fecha_compra']),
        ]

    def __str__(self):
        return f"Lote {self.id} — {self.tipo_tarjeta} × {self.cantidad_total}"

    @property
    def costo_total_bob(self) -> Decimal:
        return (self.precio_costo * self.cantidad_total).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

    def clean(self):
        if self.cantidad_restante > self.cantidad_total:
            raise ValidationError("cantidad_restante no puede ser mayor que cantidad_total.")

    def save(self, *args, **kwargs):
        if not self.pk:
            self.cantidad_restante = self.cantidad_total
        if self.cantidad_restante == 0:
            self.is_active = False
        self.full_clean()
        super().save(*args, **kwargs)


class VentaTarjeta(models.Model):
    """
    Registro de una venta de tarjetas (puede ser múltiple unidades).
    FIFO: consume unidades del lote más antiguo primero.
    """
    MEDIOS_PAGO = [
        ('CASH',     'Efectivo'),
        ('QR',       'QR'),
        ('TRANSFER', 'Transferencia'),
    ]
    ESTADOS = [
        ('COMPLETADA', 'Completada'),
        ('ANULADA',    'Anulada'),
    ]

    # Número único de venta
    numero_venta    = models.CharField(max_length=20, unique=True, editable=False)
    estado          = models.CharField(max_length=10, choices=ESTADOS, default='COMPLETADA', db_index=True)
    tipo_tarjeta    = models.ForeignKey(
        TipoTarjeta, on_delete=models.PROTECT, related_name='ventas'
    )
    cantidad        = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    precio_venta    = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Precio de venta por tarjeta en BOB"
    )
    total_bob       = models.DecimalField(
        max_digits=15, decimal_places=2,
        help_text="total = precio_venta × cantidad"
    )
    # Costo real FIFO calculado en el momento de la venta
    costo_fifo_bob  = models.DecimalField(
        max_digits=15, decimal_places=4,
        default=Decimal('0'),
        help_text="Costo real de las unidades vendidas (FIFO)"
    )
    ganancia_bob    = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal('0'),
        help_text="Ganancia neta = total_bob - costo_fifo_bob"
    )
    # Comisión/cargo adicional (facturación: Total = Compra + Comisión)
    comision_bob    = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0'),
        help_text="Comisión o cargo adicional sobre la venta en BOB",
    )
    total_con_comision = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text="total_bob + comision_bob",
    )
    medio_pago      = models.CharField(max_length=10, choices=MEDIOS_PAGO, default='CASH')
    cliente_nombre  = models.CharField(max_length=200, blank=True)
    cliente_tel     = models.CharField(max_length=20, blank=True)
    notas           = models.TextField(blank=True)
    # Auditoría
    cajero          = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='ventas_tarjetas'
    )
    branch          = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT, related_name='ventas_tarjetas'
    )
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'tarjetas_venta'
        ordering            = ['-created_at']
        verbose_name        = 'Venta de Tarjeta'
        verbose_name_plural = 'Ventas de Tarjetas'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['tipo_tarjeta', '-created_at']),
            models.Index(fields=['cajero', '-created_at']),
        ]

    # Auditoría de anulación
    motivo_anulacion = models.TextField(blank=True)
    anulado_por     = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='ventas_anuladas',
    )
    anulado_at      = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Venta {self.numero_venta} — {self.tipo_tarjeta} × {self.cantidad}"

    def save(self, *args, **kwargs):
        # Calcular total antes de guardar
        self.total_bob = (
            self.precio_venta * self.cantidad
        ).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class DetalleVentaLote(models.Model):
    """
    Detalle FIFO: qué unidades se consumieron de qué lote en cada venta.
    Permite auditoría completa de cada venta y cálculo exacto de ganancia.
    """
    venta           = models.ForeignKey(
        VentaTarjeta, on_delete=models.CASCADE, related_name='detalles_lote'
    )
    lote            = models.ForeignKey(
        LoteCompra, on_delete=models.PROTECT, related_name='movimientos'
    )
    cantidad_consumida = models.PositiveIntegerField()
    costo_unitario  = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        db_table = 'tarjetas_detalle_venta_lote'
        verbose_name = 'Detalle Venta-Lote'

    @property
    def costo_total(self) -> Decimal:
        return (self.costo_unitario * self.cantidad_consumida).quantize(
            Decimal('0.0001'), rounding=ROUND_HALF_UP
        )


class MovimientoTarjeta(models.Model):
    """
    Libro-diario unificado de tarjetas.

    Cada compra de lote genera un movimiento COMPRA (+stock, -caja).
    Cada venta genera un movimiento VENTA (-stock, +caja).

    Permite calcular P&L de tarjetas en cualquier ventana de tiempo
    sin tener que unir las tablas LoteCompra y VentaTarjeta.
    """
    TIPO_MOV = [
        ('COMPRA', 'Compra de lote'),
        ('VENTA',  'Venta a cliente'),
    ]

    tipo_movimiento = models.CharField(max_length=6, choices=TIPO_MOV, db_index=True)
    tipo_tarjeta    = models.ForeignKey(
        TipoTarjeta, on_delete=models.PROTECT, related_name='movimientos'
    )
    cantidad        = models.PositiveIntegerField()

    # Precio unitario según el tipo de movimiento:
    #   COMPRA → precio de costo por unidad
    #   VENTA  → precio de venta por unidad
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=4)
    total_bob       = models.DecimalField(max_digits=15, decimal_places=2)

    # Solo en VENTA: ganancia neta calculada por FIFO
    ganancia_bob    = models.DecimalField(
        max_digits=15, decimal_places=2,
        null=True, blank=True,
        help_text="Ganancia neta. Solo aplica a VENTA.",
    )

    # Referencias opcionales a los registros origen
    lote_compra     = models.ForeignKey(
        LoteCompra, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='movimientos_diario',
        help_text="Referencia al lote de compra origen (solo COMPRA).",
    )
    venta_tarjeta   = models.ForeignKey(
        VentaTarjeta, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='movimientos_diario',
        help_text="Referencia a la venta origen (solo VENTA).",
    )

    # Auditoría
    usuario         = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='movimientos_tarjetas'
    )
    branch          = models.ForeignKey(
        'users.Branch', on_delete=models.PROTECT,
        null=True, blank=True, related_name='movimientos_tarjetas',
    )
    notas           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table            = 'tarjetas_movimiento'
        ordering            = ['-created_at']
        verbose_name        = 'Movimiento de Tarjeta'
        verbose_name_plural = 'Movimientos de Tarjetas'
        indexes = [
            models.Index(fields=['tipo_tarjeta', '-created_at']),
            models.Index(fields=['tipo_movimiento', '-created_at']),
            models.Index(fields=['branch', '-created_at']),
        ]

    def __str__(self):
        return (
            f"{self.get_tipo_movimiento_display()} — "
            f"{self.tipo_tarjeta} × {self.cantidad} "
            f"@ Bs.{self.precio_unitario}"
        )

    @property
    def impacto_caja_bob(self) -> Decimal:
        """
        Impacto neto en caja BOB.
        COMPRA: negativo (salida de dinero).
        VENTA:  positivo (entrada de dinero).
        """
        if self.tipo_movimiento == 'COMPRA':
            return -self.total_bob
        return self.total_bob


class AlertaInventarioTarjeta(models.Model):
    """
    Umbrales de stock mínimo por tipo de tarjeta (opcionalmente por sucursal).

    stock_minimo  → warning (stock bajo)
    stock_critico → alerta roja
    """
    tipo_tarjeta    = models.ForeignKey(
        TipoTarjeta, on_delete=models.CASCADE, related_name='alertas_inventario',
    )
    branch          = models.ForeignKey(
        'users.Branch', on_delete=models.CASCADE,
        null=True, blank=True, related_name='alertas_tarjetas',
        help_text="Dejar vacío para aplicar globalmente a todas las sucursales",
    )
    stock_minimo    = models.PositiveIntegerField(
        default=20, help_text="Stock mínimo antes de warning (amarillo)",
    )
    stock_critico   = models.PositiveIntegerField(
        default=5, help_text="Stock crítico — alerta roja",
    )
    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'tarjetas_alerta_inventario'
        unique_together     = ['tipo_tarjeta', 'branch']
        verbose_name        = 'Alerta de Inventario'
        verbose_name_plural = 'Alertas de Inventario'
        indexes             = [
            models.Index(fields=['tipo_tarjeta', 'is_active']),
        ]

    def __str__(self):
        sufijo = f" — {self.branch}" if self.branch else " (global)"
        return f"Alerta {self.tipo_tarjeta}{sufijo}: min={self.stock_minimo} crit={self.stock_critico}"

    def clean(self):
        if self.stock_critico >= self.stock_minimo:
            raise ValidationError(
                "stock_critico debe ser menor que stock_minimo."
            )
