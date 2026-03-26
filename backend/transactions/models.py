# transactions/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from decimal import Decimal
import uuid
from django.utils import timezone

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
        )['total'] or Decimal('0')

class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('BUY', 'Compra'),
        ('SELL', 'Venta'),
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
    
    # Tipo y estado
    transaction_type = models.CharField(max_length=4, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')
    
    # Cliente
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='transactions'
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
    amount_from = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    amount_to = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))]
    )
    
    # Método de pago
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS)
    payment_reference = models.CharField(max_length=100, blank=True)
    
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
    
    def save(self, *args, **kwargs):
        if not self.transaction_number:
            self.transaction_number = self.generate_transaction_number()
        
        if self.status == 'COMPLETED' and not self.completed_at:
            self.completed_at = timezone.now()
        
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
        """Calcula el margen de ganancia"""
        if self.transaction_type == 'BUY':
            # Casa compra divisas
            official_rate = self.exchange_rate * Decimal('1.003')  # Estimado
            return (official_rate - self.exchange_rate) * self.amount_from
        else:
            # Casa vende divisas
            official_rate = self.exchange_rate * Decimal('0.997')  # Estimado
            return (self.exchange_rate - official_rate) * self.amount_from
    
    @property
    def requires_supervisor(self):
        """Determina si requiere aprobación de supervisor"""
        # Montos mayores a 5000 USD equivalente
        if self.currency_from.code == 'USD':
            return self.amount_from > 5000
        elif self.currency_from.code == 'BOB':
            return self.amount_from > 35000  # ~5000 USD
        else:
            # Convertir a USD para comparar
            return self.amount_from * self.exchange_rate > 35000
    
    def can_be_reversed(self):
        """Verifica si la transacción puede ser revertida"""
        if self.status != 'COMPLETED':
            return False
        
        # No revertir transacciones de más de 24 horas
        time_limit = timezone.now() - timezone.timedelta(hours=24)
        return self.completed_at and self.completed_at > time_limit
    
    def reverse(self, user, reason):
        """Revierte la transacción"""
        if not self.can_be_reversed():
            raise ValueError("Esta transacción no puede ser revertida")
        
        # Crear transacción de reversa
        reversal = Transaction.objects.create(
            transaction_type='SELL' if self.transaction_type == 'BUY' else 'BUY',
            customer=self.customer,
            currency_from=self.currency_to,
            currency_to=self.currency_from,
            amount_from=self.amount_to,
            amount_to=self.amount_from,
            exchange_rate=Decimal('1') / self.exchange_rate,
            payment_method=self.payment_method,
            cashier=user,
            branch=self.branch,
            notes=f"Reversa de transacción {self.transaction_number}. Razón: {reason}",
            status='COMPLETED'
        )
        
        self.status = 'REVERSED'
        self.save()
        
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