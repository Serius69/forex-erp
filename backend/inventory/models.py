# inventory/models.py
from django.db import models
from django.db.models import F, Sum
from django.contrib.auth import get_user_model
from decimal import Decimal
from django.utils import timezone
from core.finance import quantize_amount, quantize_rate, calculate_wac

User = get_user_model()

class CurrencyInventory(models.Model):
    currency = models.ForeignKey(
        'rates.Currency',
        on_delete=models.CASCADE,
        related_name='inventories'
    )
    branch = models.ForeignKey(
        'users.Branch',
        on_delete=models.CASCADE,
        related_name='inventories'
    )
    
    # Balances
    physical_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0')
    )
    digital_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0')
    )
    
    # Límites
    minimum_stock = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('1000')
    )
    maximum_stock = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('50000')
    )
    reorder_point = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('2000')
    )
    
    # Costo promedio ponderado
    weighted_average_cost = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal('0')
    )
    
    # Timestamps
    last_updated = models.DateTimeField(auto_now=True)
    last_recount = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ['currency', 'branch']
        verbose_name = 'Inventario de Divisa'
        verbose_name_plural = 'Inventarios de Divisas'
        indexes = [
            models.Index(fields=['currency', 'branch']),
        ]
    
    def __str__(self):
        return f"{self.currency.code} - {self.branch.name}"
    
    @property
    def total_balance(self):
        return self.physical_balance + self.digital_balance

    @property
    def real_physical_balance(self):
        """Saldo físico en unidades reales (total_balance × scale_factor).
        Para CLP/ARS (scale=1000): 680 unidades → 680,000 pesos reales."""
        return self.physical_balance * self.currency.scale_factor

    @property
    def real_total_balance(self):
        """Saldo total en unidades reales (total_balance × scale_factor)."""
        return self.total_balance * self.currency.scale_factor

    @property
    def needs_replenishment(self):
        return self.total_balance <= self.reorder_point
    
    @property
    def is_overstocked(self):
        return self.total_balance > self.maximum_stock
    
    @property
    def stock_level_percentage(self):
        if self.maximum_stock:
            return (self.total_balance / self.maximum_stock) * 100
        return 0
    
    def add_currency(self, amount, rate, user=None):
        """Aumenta el saldo físico (casa compra divisas). Thread-safe con select_for_update."""
        amount = quantize_amount(amount)
        rate   = quantize_rate(rate)

        # Calcular WAC antes de modificar el balance
        new_wac = calculate_wac(
            self.physical_balance, self.weighted_average_cost, amount, rate
        )
        balance_before = self.physical_balance

        self.physical_balance      += amount
        self.weighted_average_cost  = new_wac
        self.save(update_fields=['physical_balance', 'weighted_average_cost'])

        InventoryMovement.objects.create(
            inventory      = self,
            movement_type  = 'IN',
            amount         = amount,
            rate           = rate,
            balance_before = balance_before,
            balance_after  = self.physical_balance,
            notes          = f"Compra de divisa TC={rate}",
            user           = user if isinstance(user, User) else None,
        )
    
    def remove_currency(self, amount, user):
        """
        Retira divisas del inventario. Thread-safe: debe llamarse desde dentro de
        un bloque select_for_update() para garantizar consistencia.
        """
        amount = quantize_amount(amount)

        if amount > self.total_balance:
            raise ValueError(
                f"Saldo insuficiente de {self.currency.code}. "
                f"Disponible: {self.total_balance:.4f}, solicitado: {amount:.4f}"
            )

        balance_before = self.total_balance

        # Retirar primero del balance físico
        if amount <= self.physical_balance:
            self.physical_balance -= amount
        else:
            remainder            = amount - self.physical_balance
            self.physical_balance = Decimal('0')
            self.digital_balance -= remainder

        self.save(update_fields=['physical_balance', 'digital_balance'])

        InventoryMovement.objects.create(
            inventory      = self,
            movement_type  = 'OUT',
            amount         = amount,
            rate           = self.weighted_average_cost,
            balance_before = balance_before,
            balance_after  = self.total_balance,
            user           = user if isinstance(user, User) else None,
            reference      = "Venta de divisas",
        )

        if self.needs_replenishment:
            self._create_alert('LOW_STOCK', user)
    
    def transfer_to_branch(self, target_branch, amount, user):
        """Transfiere divisas a otra sucursal"""
        if amount > self.total_balance:
            raise ValueError("Saldo insuficiente para transferencia")
        
        # Obtener o crear inventario destino
        target_inventory, created = CurrencyInventory.objects.get_or_create(
            currency=self.currency,
            branch=target_branch,
            defaults={
                'minimum_stock': self.minimum_stock,
                'maximum_stock': self.maximum_stock,
                'weighted_average_cost': self.weighted_average_cost
            }
        )
        
        # Realizar transferencia
        self.remove_currency(amount, user)
        target_inventory.add_currency(amount, self.weighted_average_cost, user)
        
        # Registrar transferencia
        InventoryTransfer.objects.create(
            currency=self.currency,
            source_branch=self.branch,
            target_branch=target_branch,
            amount=amount,
            rate=self.weighted_average_cost,
            authorized_by=user,
            status='COMPLETED'
        )
    
    def adjust_inventory(self, physical_count, digital_count, user, reason):
        """Ajusta el inventario según conteo físico"""
        physical_diff = physical_count - self.physical_balance
        digital_diff = digital_count - self.digital_balance
        total_diff = physical_diff + digital_diff
        
        if total_diff != 0:
            # Registrar ajuste
            InventoryMovement.objects.create(
                inventory=self,
                movement_type='ADJUSTMENT',
                amount=abs(total_diff),
                rate=self.weighted_average_cost,
                balance_before=self.total_balance,
                balance_after=physical_count + digital_count,
                user=user,
                notes=f"Ajuste por {reason}. Diferencia: {total_diff}"
            )
            
            # Actualizar balances
            self.physical_balance = physical_count
            self.digital_balance = digital_count
            self.last_recount = timezone.now()
            self.save()
            
            # Alerta si la diferencia es significativa (>1%)
            if abs(total_diff) > self.total_balance * Decimal('0.01'):
                self._create_alert('SIGNIFICANT_ADJUSTMENT', user, {
                    'difference': float(total_diff),
                    'percentage': float((total_diff / self.total_balance) * 100)
                })
    
    def _create_alert(self, alert_type, user, extra_data=None):
        """Crea una alerta de inventario"""
        from .alerts import InventoryAlert
        
        InventoryAlert.objects.create(
            inventory=self,
            alert_type=alert_type,
            triggered_by=user,
            data=extra_data or {}
        )

class InventoryCard(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE',   'Activa'),
        ('INACTIVE', 'Inactiva'),
        ('BLOCKED',  'Bloqueada'),
    ]

    currency   = models.CharField(max_length=10)
    amount     = models.DecimalField(max_digits=15, decimal_places=2)
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Tarjeta de Inventario'
        verbose_name_plural = 'Tarjetas de Inventario'

    def __str__(self):
        return f"{self.currency} - {self.amount} ({self.status})"


class InventoryMovement(models.Model):
    MOVEMENT_TYPES = [
        ('IN', 'Entrada'),
        ('OUT', 'Salida'),
        ('ADJUSTMENT', 'Ajuste'),
        ('TRANSFER_IN', 'Transferencia Entrada'),
        ('TRANSFER_OUT', 'Transferencia Salida'),
    ]
    
    inventory = models.ForeignKey(
        CurrencyInventory,
        on_delete=models.CASCADE,
        related_name='movements'
    )
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    balance_before = models.DecimalField(max_digits=15, decimal_places=2)
    balance_after = models.DecimalField(max_digits=15, decimal_places=2)
    reference = models.CharField(max_length=100, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Movimiento de Inventario'
        verbose_name_plural = 'Movimientos de Inventario'
        indexes = [
            models.Index(fields=['inventory', '-created_at']),
            models.Index(fields=['movement_type', '-created_at']),
        ]
    
    @property
    def value(self):
        return self.amount * self.rate

class InventoryTransfer(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pendiente'),
        ('IN_TRANSIT', 'En Tránsito'),
        ('COMPLETED', 'Completada'),
        ('CANCELLED', 'Cancelada'),
    ]
    
    transfer_number = models.CharField(max_length=20, unique=True)
    currency = models.ForeignKey('rates.Currency', on_delete=models.PROTECT)
    source_branch = models.ForeignKey(
        'users.Branch',
        on_delete=models.PROTECT,
        related_name='transfers_sent'
    )
    target_branch = models.ForeignKey(
        'users.Branch',
        on_delete=models.PROTECT,
        related_name='transfers_received'
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # Personal involucrado
    requested_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='transfers_requested'
    )
    authorized_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='transfers_authorized',
        null=True,
        blank=True
    )
    received_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='transfers_received_by_me',
        null=True,
        blank=True
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Transferencia de Inventario'
        verbose_name_plural = 'Transferencias de Inventario'
    
    def save(self, *args, **kwargs):
        if not self.transfer_number:
            self.transfer_number = self.generate_transfer_number()
        super().save(*args, **kwargs)
    
    def generate_transfer_number(self):
        prefix = f"TRF{timezone.now().strftime('%Y%m%d')}"
        last_transfer = InventoryTransfer.objects.filter(
            transfer_number__startswith=prefix
        ).order_by('-transfer_number').first()
        
        if last_transfer:
            last_number = int(last_transfer.transfer_number[-4:])
            new_number = last_number + 1
        else:
            new_number = 1
        
        return f"{prefix}{new_number:04d}"