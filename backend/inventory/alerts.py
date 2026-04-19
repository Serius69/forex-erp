# backend/inventory/alerts.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import json

User = get_user_model()

class InventoryAlert(models.Model):
    ALERT_TYPES = [
        ('LOW_STOCK', 'Stock Bajo'),
        ('OVERSTOCK', 'Exceso de Stock'),
        ('SIGNIFICANT_ADJUSTMENT', 'Ajuste Significativo'),
        ('TRANSFER_PENDING', 'Transferencia Pendiente'),
        ('RECOUNT_NEEDED', 'Reconteo Necesario'),
    ]
    
    SEVERITY_LEVELS = [
        ('LOW', 'Baja'),
        ('MEDIUM', 'Media'),
        ('HIGH', 'Alta'),
        ('CRITICAL', 'Crítica'),
    ]
    
    inventory = models.ForeignKey(
        'CurrencyInventory',
        on_delete=models.CASCADE,
        related_name='alerts'
    )
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPES)
    severity = models.CharField(max_length=10, choices=SEVERITY_LEVELS, default='MEDIUM')
    message = models.TextField()
    data = models.JSONField(default=dict)
    
    triggered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='inventoryalert_triggered'
    )
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventoryalert_resolved'
    )
    
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Alerta de Inventario'
        verbose_name_plural = 'Alertas de Inventario'
        indexes = [
            models.Index(fields=['is_resolved', '-created_at']),
            models.Index(fields=['alert_type', '-created_at']),
        ]
    
    def save(self, *args, **kwargs):
        # Generar mensaje automático si no existe
        if not self.message:
            self.message = self._generate_message()
        
        # Determinar severidad
        if not self.severity:
            self.severity = self._calculate_severity()
        
        # Guardar
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Enviar notificaciones si es nueva
        if is_new and self.severity in ['HIGH', 'CRITICAL']:
            self._send_notifications()
    
    def _generate_message(self):
        """Genera mensaje según el tipo de alerta"""
        messages = {
            'LOW_STOCK': f"El stock de {self.inventory.currency.code} en {self.inventory.branch.name} está por debajo del mínimo. Balance actual: {self.inventory.total_balance}",
            'OVERSTOCK': f"El stock de {self.inventory.currency.code} en {self.inventory.branch.name} excede el máximo permitido. Balance actual: {self.inventory.total_balance}",
            'SIGNIFICANT_ADJUSTMENT': f"Se realizó un ajuste significativo en {self.inventory.currency.code} en {self.inventory.branch.name}",
            'TRANSFER_PENDING': f"Hay una transferencia pendiente de {self.inventory.currency.code}",
            'RECOUNT_NEEDED': f"Se requiere reconteo de {self.inventory.currency.code} en {self.inventory.branch.name}"
        }
        return messages.get(self.alert_type, "Alerta de inventario")
    
    def _calculate_severity(self):
        """Calcula la severidad según el tipo y datos"""
        if self.alert_type == 'LOW_STOCK':
            percentage = (self.inventory.total_balance / self.inventory.minimum_stock) * 100
            if percentage < 25:
                return 'CRITICAL'
            elif percentage < 50:
                return 'HIGH'
            else:
                return 'MEDIUM'
        
        elif self.alert_type == 'SIGNIFICANT_ADJUSTMENT':
            difference_percentage = abs(self.data.get('percentage', 0))
            if difference_percentage > 5:
                return 'CRITICAL'
            elif difference_percentage > 2:
                return 'HIGH'
            else:
                return 'MEDIUM'
        
        return 'MEDIUM'
    
    def _send_notifications(self):
        """Envía notificaciones por email y Telegram."""
        recipients = []

        # Determinar destinatarios según severidad
        if self.severity == 'CRITICAL':
           # Notificar a todos los administradores
           recipients = User.objects.filter(
               role='ADMIN',
               is_active=True
           ).values_list('email', flat=True)
        elif self.severity == 'HIGH':
           # Notificar a supervisores de la sucursal
           recipients = User.objects.filter(
               role__in=['ADMIN', 'SUPERVISOR'],
               branch=self.inventory.branch,
               is_active=True
           ).values_list('email', flat=True)

        if recipients:
           send_mail(
               f'[{self.get_severity_display()}] {self.get_alert_type_display()}',
               self.message,
               settings.DEFAULT_FROM_EMAIL,
               list(recipients),
               fail_silently=True,
           )

        # Telegram: alerta en tiempo real para severidades HIGH y CRITICAL
        try:
            from services.notifications.telegram import alert_inventory_critical
            alert_inventory_critical(
                alert_type=self.get_alert_type_display(),
                currency=self.inventory.currency.code,
                branch=str(self.inventory.branch),
                severity=self.severity,
                message=self.message,
            )
        except Exception:
            pass
   
    def resolve(self, user, notes=''):
       """Marca la alerta como resuelta"""
       self.is_resolved = True
       self.resolved_by = user
       self.resolved_at = timezone.now()
       
       if notes:
           self.data['resolution_notes'] = notes
       
       self.save()


class InventoryAlertService:
   """Servicio para gestión de alertas de inventario"""
   
   @staticmethod
   def check_all_inventories():
       """Verifica todos los inventarios y genera alertas"""
       from .models import CurrencyInventory
       
       alerts_created = []
       
       for inventory in CurrencyInventory.objects.select_related('currency', 'branch').all():
           # Verificar stock bajo
           if inventory.needs_replenishment:
               alert, created = InventoryAlert.objects.get_or_create(
                   inventory=inventory,
                   alert_type='LOW_STOCK',
                   is_resolved=False,
                   defaults={
                       'data': {
                           'current_balance': float(inventory.total_balance),
                           'minimum_stock': float(inventory.minimum_stock),
                           'percentage': float(inventory.stock_level_percentage)
                       }
                   }
               )
               if created:
                   alerts_created.append(alert)
           
           # Verificar exceso de stock
           if inventory.is_overstocked:
               alert, created = InventoryAlert.objects.get_or_create(
                   inventory=inventory,
                   alert_type='OVERSTOCK',
                   is_resolved=False,
                   defaults={
                       'data': {
                           'current_balance': float(inventory.total_balance),
                           'maximum_stock': float(inventory.maximum_stock),
                           'excess': float(inventory.total_balance - inventory.maximum_stock)
                       }
                   }
               )
               if created:
                   alerts_created.append(alert)
           
           # Verificar si necesita reconteo (más de 30 días)
           if inventory.last_recount:
               days_since_recount = (timezone.now() - inventory.last_recount).days
               if days_since_recount > 30:
                   alert, created = InventoryAlert.objects.get_or_create(
                       inventory=inventory,
                       alert_type='RECOUNT_NEEDED',
                       is_resolved=False,
                       defaults={
                           'data': {
                               'days_since_last_recount': days_since_recount,
                               'last_recount_date': inventory.last_recount.isoformat()
                           }
                       }
                   )
                   if created:
                       alerts_created.append(alert)
       
       # Verificar inventario negativo (saldo físico o digital < 0)
       for inventory in CurrencyInventory.objects.select_related('currency', 'branch').all():
           if inventory.physical_balance < 0 or inventory.digital_balance < 0:
               try:
                   from services.notifications.telegram import alert_negative_inventory
                   balance = min(float(inventory.physical_balance), float(inventory.digital_balance))
                   alert_negative_inventory(
                       currency=inventory.currency.code,
                       branch=str(inventory.branch),
                       balance=f'{balance:,.2f}',
                   )
               except Exception:
                   pass

       return alerts_created

   @staticmethod
   def get_active_alerts(branch=None, severity=None):
       """Obtiene alertas activas con filtros opcionales"""
       queryset = InventoryAlert.objects.filter(is_resolved=False)
       
       if branch:
           queryset = queryset.filter(inventory__branch=branch)
       
       if severity:
           queryset = queryset.filter(severity=severity)
       
       return queryset.select_related('inventory__currency', 'inventory__branch')