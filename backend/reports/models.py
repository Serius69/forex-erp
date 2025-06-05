from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class Report(models.Model):
    REPORT_TYPES = [
        ('DAILY', 'Reporte Diario'),
        ('WEEKLY', 'Reporte Semanal'),
        ('MONTHLY', 'Reporte Mensual'),
        ('CUSTOM', 'Reporte Personalizado'),
        ('REGULATORY', 'Reporte Regulatorio'),
        ('TAX', 'Reporte Fiscal'),
    ]
    
    report_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Período del reporte
    start_date = models.DateField()
    end_date = models.DateField()
    
    # Archivos generados
    pdf_file = models.FileField(upload_to='reports/pdf/', null=True, blank=True)
    excel_file = models.FileField(upload_to='reports/excel/', null=True, blank=True)
    
    # Metadatos
    parameters = models.JSONField(default=dict)
    summary_data = models.JSONField(default=dict)
    
    # Usuario y timestamps
    generated_by = models.ForeignKey(User, on_delete=models.PROTECT)
    generated_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-generated_at']
        verbose_name = 'Reporte'
        verbose_name_plural = 'Reportes'
        indexes = [
            models.Index(fields=['report_type', '-generated_at']),
            models.Index(fields=['start_date', 'end_date']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.start_date} - {self.end_date})"

class ReportSchedule(models.Model):
    """Programación de reportes automáticos"""
    FREQUENCY_CHOICES = [
        ('DAILY', 'Diario'),
        ('WEEKLY', 'Semanal'),
        ('MONTHLY', 'Mensual'),
    ]
    
    name = models.CharField(max_length=100)
    report_type = models.CharField(max_length=20, choices=Report.REPORT_TYPES)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    parameters = models.JSONField(default=dict)
    
    # Configuración de envío
    send_email = models.BooleanField(default=True)
    email_recipients = models.JSONField(default=list)
    
    # Estado
    is_active = models.BooleanField(default=True)
    last_run = models.DateTimeField(null=True, blank=True)
    next_run = models.DateTimeField(null=True, blank=True)
    
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Programación de Reporte'
        verbose_name_plural = 'Programaciones de Reportes'