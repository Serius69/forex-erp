# transactions/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from decimal import Decimal  # still needed for exchange_rate, profit_margin
import uuid
from django.utils import timezone
from .validators import (
    DENOMINATION_CHOICES,
    validate_transaction_amounts,
)

User = get_user_model()

class Customer(models.Model):
    DOCUMENT_TYPES = [
        ('CI', 'Cédula de Identidad'),
        ('NIT', 'NIT'),
        ('PASSPORT', 'Pasaporte'),
        ('RUC', 'RUC'),
    ]
    
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default='CI')
    document_number = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    birth_date = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=50, default='Boliviana')
    is_pep = models.BooleanField(
        default=False,
        help_text="Persona Expuesta Políticamente"
    )
    is_frequent = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        indexes = [
            models.Index(fields=['document_number']),
            models.Index(fields=['full_name']),
        ]
    
    def __str__(self):
        return f"{self.full_name} ({self.document_number})"
    
    @property
    def transaction_count(self):
        return self.transactions.count()
    
    @property
    def total_volume(self):
        from django.db.models import Sum
        return self.transactions.aggregate(
            total=Sum('amount_from')
        )['total'] or 0

class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('BUY', 'Compra'),
        ('SELL', 'Venta'),
    ]

    TRANSACTION_CATEGORIES = [
        ('REPORTABLE', 'Reportable ASFI'),
        ('INTERNA',    'Interna (no reportable)'),
    ]

    PAYMENT_METHODS = [
        ('CASH', 'Efectivo'),
        ('TRANSFER', 'Transferencia'),
        ('CHECK', 'Cheque'),
        ('CARD', 'Tarjeta'),
        ('QR', 'QR'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pendiente'),
        ('COMPLETED', 'Completada'),
        ('CANCELLED', 'Cancelada'),
        ('REVERSED', 'Revertida'),
    ]

    # Identificación única
    transaction_number = models.CharField(
        max_length=20,
        unique=True,
        editable=False
    )

    # Tipo de operación (BUY/SELL) y categoría regulatoria (REPORTABLE/INTERNA)
    transaction_type = models.CharField(max_length=4, choices=TRANSACTION_TYPES)
    transaction_category = models.CharField(
        max_length=12,
        choices=TRANSACTION_CATEGORIES,
        default='REPORTABLE',
        db_index=True,
        help_text=(
            'REPORTABLE: requiere CI del cliente, se incluye en reportes ASFI. '
            'INTERNA: sin datos de cliente obligatorios, no aparece en reportes ASFI.'
        ),
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')

    # Cliente — null solo para transacciones INTERNA
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='transactions',
        null=True,
        blank=True,
    )
    
    # Divisas y montos
    currency_from = models.ForeignKey(
        'rates.Currency',
        on_delete=models.PROTECT,
        related_name='transactions_from'
    )
    currency_to = models.ForeignKey(
        'rates.Currency',
        on_delete=models.PROTECT,
        related_name='transactions_to'
    )
    amount_from = models.IntegerField(
        validators=[MinValueValidator(1)]
    )
    amount_to = models.IntegerField(
        validators=[MinValueValidator(1)]
    )
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))]
    )
    
    # Método de pago
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS)
    payment_reference = models.CharField(max_length=100, blank=True)

    # Denominación de billetes (solo aplica a CASH USD)
    denomination_type = models.CharField(
        max_length=10,
        choices=DENOMINATION_CHOICES,
        null=True,
        blank=True,
        help_text='Tipo de billete USD: BILLS (100/50), SUELTOS (5/10/20), SINGLES (1/2). '
                  'Requerido para transacciones en efectivo USD.',
    )

    # ── Datos de cliente desnormalizados ─────────────────────────────────────
    # Siempre se sincronizan desde customer FK en save().
    # Para transacciones INTERNA sin customer, se pueden proveer directamente.
    nombre_cliente = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text='Nombre completo del cliente (desnormalizado de customer.full_name).',
    )
    carnet_identidad = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            'Número de CI/documento (desnormalizado de customer.document_number). '
            'Requerido para transacciones REPORTABLE.'
        ),
    )

    # ── Visibilidad de cumplimiento ASFI ──────────────────────────────────────
    visible_asfi = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            'Si TRUE, la transacción aparece en los reportes regulatorios ASFI '
            '(RTE, Libro Diario).  Se establece automáticamente según '
            'transaction_category: REPORTABLE → True, INTERNA → False.  '
            'Puede sobreescribirse manualmente en casos excepcionales.'
        ),
    )
    # Legacy alias — mantenido para backward-compat de reportes existentes.
    is_reportable_to_asfi = models.BooleanField(
        default=True,
        db_index=True,
        help_text='Alias de visible_asfi. Mantenido para compatibilidad con reportes ASFI.',
    )
    
    # Usuario y sucursal
    cashier = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='transactions_as_cashier'
    )
    branch = models.ForeignKey(
        'users.Branch',
        on_delete=models.PROTECT,
        related_name='transactions'
    )
    
    # Supervisor (para montos altos)
    supervisor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transactions_as_supervisor'
    )
    
    # Información adicional
    notes = models.TextField(blank=True)
    receipt_number = models.CharField(max_length=50, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Transacción'
        verbose_name_plural = 'Transacciones'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['transaction_number']),
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['branch', '-created_at']),
        ]
        permissions = [
            ('can_reverse_transaction', 'Puede revertir transacciones'),
            ('can_view_all_branches', 'Puede ver transacciones de todas las sucursales'),
        ]
    
    def clean(self):
        """Valida denominación, montos y datos de cliente según categoría."""
        super().clean()

        # REPORTABLE → CI obligatorio (desde customer FK o campo directo)
        if self.transaction_category == 'REPORTABLE':
            has_customer_ci = bool(self.customer_id)
            has_direct_ci   = bool((self.carnet_identidad or '').strip())
            if not has_customer_ci and not has_direct_ci:
                raise ValidationError({
                    'carnet_identidad': (
                        'Las transacciones REPORTABLE requieren CI del cliente '
                        '(campo carnet_identidad o un customer con document_number).'
                    )
                })

        if self.currency_from_id and self.currency_to_id and self.amount_from and self.amount_to:
            validate_transaction_amounts(
                currency_from_code=self.currency_from.code,
                currency_to_code=self.currency_to.code,
                amount_from=self.amount_from,
                amount_to=self.amount_to,
                payment_method=self.payment_method or '',
                denomination_type=self.denomination_type,
                transaction_type=self.transaction_type or 'BUY',
            )

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            self.transaction_number = self.generate_transaction_number()

        if self.status == 'COMPLETED' and not self.completed_at:
            self.completed_at = timezone.now()

        # ── visible_asfi es campo derivado de transaction_category — sin override manual.
        # REPORTABLE → siempre visible para ASFI; INTERNA → siempre invisible.
        self.visible_asfi = (self.transaction_category == 'REPORTABLE')

        # ── Sincronizar campos desnormalizados de cliente ─────────────────────
        if self.customer_id:
            # Poblar nombre_cliente y carnet_identidad desde el FK si están vacíos
            if not self.nombre_cliente:
                self.nombre_cliente = self.customer.full_name
            if not self.carnet_identidad:
                self.carnet_identidad = self.customer.document_number

        # ── Legacy alias: mantener is_reportable_to_asfi == visible_asfi ─────
        self.is_reportable_to_asfi = self.visible_asfi

        super().save(*args, **kwargs)
    
    def generate_transaction_number(self):
        """Genera número único de transacción"""
        prefix = f"{self.branch.code}{timezone.now().strftime('%Y%m%d')}"
        
        # Obtener el último número del día
        last_transaction = Transaction.objects.filter(
            transaction_number__startswith=prefix
        ).order_by('-transaction_number').first()
        
        if last_transaction:
            last_number = int(last_transaction.transaction_number[-4:])
            new_number = last_number + 1
        else:
            new_number = 1
        
        return f"{prefix}{new_number:04d}"
    
    @property
    def profit_margin(self):
        """
        Calcula el margen de ganancia estimado basado en el spread típico (0.3%).
        Para el cálculo exacto se necesita la tasa oficial del BCB en el momento
        de la transacción — usar reports.services.ManagementReportService para P&L real.
        """
        try:
            from decimal import ROUND_HALF_UP
            spread_factor = Decimal('0.003')  # 0.3% spread promedio del mercado
            if self.exchange_rate is None or self.amount_from is None:
                return Decimal('0.00')
            profit_per_unit = self.exchange_rate * spread_factor
            return (profit_per_unit * self.amount_from).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        except Exception:
            return Decimal('0.00')

    @property
    def requires_supervisor(self):
        """Determina si requiere aprobación de supervisor"""
        try:
            # Montos mayores a 5000 USD equivalente
            if self.currency_from is None or self.amount_from is None:
                return False
            if self.currency_from.code == 'USD':
                return self.amount_from > 5000
            elif self.currency_from.code == 'BOB':
                return self.amount_from > 35000  # ~5000 USD
            else:
                # Convertir a USD para comparar
                return self.amount_from * (self.exchange_rate or 1) > 35000
        except Exception:
            return False
    
    def can_be_reversed(self):
        """Verifica si la transacción puede ser revertida"""
        if self.status != 'COMPLETED':
            return False
        
        # No revertir transacciones de más de 24 horas
        time_limit = timezone.now() - timezone.timedelta(hours=24)
        return self.completed_at and self.completed_at > time_limit
    
    def reverse(self, user, reason):
        """
        Revierte la transacción: crea una anti-transacción y restaura el inventario.
        Debe llamarse dentro de db_transaction.atomic() para garantizar atomicidad.
        """
        from django.db import transaction as db_tx
        if not self.can_be_reversed():
            raise ValueError("Esta transacción no puede ser revertida")

        with db_tx.atomic():
            # 1. Restaurar inventario de divisas (operación inversa exacta)
            from .services import TransactionService, reverse_transaction_effects
            svc = TransactionService()
            svc._reverse_inventory(self)

            # 2. Revertir efectos sobre el efectivo BOB
            reverse_transaction_effects(self)

            # 3. Crear transacción de reversa (registro contable)
            reversal = Transaction.objects.create(
                transaction_type     = 'SELL' if self.transaction_type == 'BUY' else 'BUY',
                transaction_category = self.transaction_category,
                customer             = self.customer,   # None si era INTERNA
                currency_from        = self.currency_to,
                currency_to          = self.currency_from,
                amount_from          = self.amount_to,
                amount_to            = self.amount_from,
                exchange_rate        = Decimal('1') / self.exchange_rate,
                payment_method       = self.payment_method,
                cashier              = user,
                branch               = self.branch,
                notes                = f"REVERSA de {self.transaction_number}. Razón: {reason}",
                status               = 'COMPLETED',
            )

            # 4. Actualizar inventario por la anti-transacción
            svc._update_inventory(reversal)

            # 5. Marcar original como REVERSED
            self.status = 'REVERSED'
            self.save(update_fields=['status', 'updated_at'])

            # 6. Audit log
            from users.models import UserActivity
            UserActivity.objects.create(
                user    = user,
                action  = 'TRANSACTION_REVERSED',
                details = {
                    'original_tx':  self.transaction_number,
                    'reversal_tx':  reversal.transaction_number,
                    'reason':       reason,
                    'amount_from':  str(self.amount_from),
                    'currency':     self.currency_from.code,
                },
            )

        return reversal

class TransactionDocument(models.Model):
    """Documentos asociados a transacciones"""
    DOCUMENT_TYPES = [
        ('ID', 'Documento de Identidad'),
        ('RECEIPT', 'Comprobante'),
        ('AUTHORIZATION', 'Autorización'),
        ('OTHER', 'Otro'),
    ]
    
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES)
    file = models.FileField(upload_to='transaction_documents/%Y/%m/')
    description = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Documento de Transacción'
        verbose_name_plural = 'Documentos de Transacción'