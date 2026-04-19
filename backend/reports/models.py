from django.db import models
from django.conf import settings
from decimal import Decimal


class CashTransactionReport(models.Model):
    """RTE — Registro de Transacciones en Efectivo >= $1,000"""
    STATUS_CHOICES = [
        ('PENDING',   'Pendiente'),
        ('SUBMITTED', 'Enviado a ASFI'),
        ('ACCEPTED',  'Aceptado'),
        ('REJECTED',  'Rechazado'),
    ]
    transaction           = models.OneToOneField('transactions.Transaction',
                                                  on_delete=models.PROTECT,
                                                  related_name='rte_report')
    report_number         = models.CharField(max_length=30, unique=True, editable=False)
    report_date           = models.DateField()
    amount_usd_equiv      = models.DecimalField(max_digits=15, decimal_places=2)
    currency_code         = models.CharField(max_length=5)
    original_amount       = models.DecimalField(max_digits=15, decimal_places=2)
    exchange_rate_usd     = models.DecimalField(max_digits=10, decimal_places=6)
    customer_full_name    = models.CharField(max_length=200)
    customer_document_type= models.CharField(max_length=20)
    customer_document_num = models.CharField(max_length=50)
    customer_nationality  = models.CharField(max_length=50, default='Boliviana')
    customer_is_pep       = models.BooleanField(default=False)
    status                = models.CharField(max_length=15, choices=STATUS_CHOICES,
                                              default='PENDING')
    asfi_reference        = models.CharField(max_length=50, blank=True)
    submitted_at          = models.DateTimeField(null=True, blank=True)
    submitted_by          = models.ForeignKey(settings.AUTH_USER_MODEL,
                                               on_delete=models.PROTECT,
                                               related_name='rte_submitted',
                                               null=True, blank=True)
    notes                 = models.TextField(blank=True)
    created_at            = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'reports_rte'
        verbose_name        = 'RTE — Transacción en Efectivo'
        verbose_name_plural = 'RTE — Transacciones en Efectivo'
        ordering            = ['-report_date', '-created_at']
        indexes = [
            models.Index(fields=['report_date']),
            models.Index(fields=['status']),
            models.Index(fields=['customer_document_num']),
        ]

    def save(self, *args, **kwargs):
        if not self.report_number:
            from django.utils import timezone
            from django.db import transaction as _tx
            prefix = f"RTE{timezone.now().strftime('%Y%m%d')}"
            with _tx.atomic():
                last = (CashTransactionReport.objects
                        .select_for_update()
                        .filter(report_number__startswith=prefix)
                        .order_by('-report_number')
                        .first())
                seq = int(last.report_number[-4:]) + 1 if last else 1
                self.report_number = f"{prefix}{seq:04d}"
        super().save(*args, **kwargs)

    @classmethod
    def should_report(cls, amount_usd_equiv: Decimal) -> bool:
        return amount_usd_equiv >= Decimal('1000.00')


class SuspiciousActivityReport(models.Model):
    """ROUE — Operaciones Inusuales o Sospechosas"""
    REPORT_TYPE_CHOICES = [
        ('UNUSUAL',    'Operación Inusual'),
        ('SUSPICIOUS', 'Operación Sospechosa'),
    ]
    RISK_CHOICES  = [('LOW','Bajo'),('MEDIUM','Medio'),('HIGH','Alto'),('CRITICAL','Crítico')]
    STATUS_CHOICES= [('DRAFT','Borrador'),('REVIEW','En Revisión'),
                     ('SUBMITTED','Enviado'),('CLOSED','Cerrado')]

    report_number     = models.CharField(max_length=30, unique=True, editable=False)
    report_type       = models.CharField(max_length=15, choices=REPORT_TYPE_CHOICES)
    risk_level        = models.CharField(max_length=10, choices=RISK_CHOICES, default='MEDIUM')
    status            = models.CharField(max_length=15, choices=STATUS_CHOICES, default='DRAFT')
    customer          = models.ForeignKey('transactions.Customer', on_delete=models.PROTECT,
                                           related_name='sar_reports')
    transactions      = models.ManyToManyField('transactions.Transaction',
                                                related_name='sar_reports', blank=True)
    description       = models.TextField()
    indicators        = models.JSONField(default=list)
    amount_involved   = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    currency_involved = models.CharField(max_length=5, default='USD')
    detected_by       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                           related_name='sar_detected')
    reviewed_by       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                           related_name='sar_reviewed', null=True, blank=True)
    submitted_by      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                           related_name='sar_submitted', null=True, blank=True)
    asfi_reference    = models.CharField(max_length=50, blank=True)
    internal_notes    = models.TextField(blank=True)
    detected_at       = models.DateTimeField(auto_now_add=True)
    reviewed_at       = models.DateTimeField(null=True, blank=True)
    submitted_at      = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'reports_roue'
        ordering = ['-detected_at']
        indexes  = [models.Index(fields=['status', 'risk_level'])]

    def save(self, *args, **kwargs):
        if not self.report_number:
            from django.utils import timezone
            from django.db import transaction as _tx
            prefix = f"ROUE{timezone.now().strftime('%Y%m')}"
            with _tx.atomic():
                last = (SuspiciousActivityReport.objects
                        .select_for_update()
                        .filter(report_number__startswith=prefix)
                        .order_by('-report_number')
                        .first())
                seq = int(last.report_number[-4:]) + 1 if last else 1
                self.report_number = f"{prefix}{seq:04d}"
        super().save(*args, **kwargs)


class PEPRegistry(models.Model):
    """Personas Expuestas Políticamente"""
    RISK_CHOICES = [('LOW','Bajo'),('MEDIUM','Medio'),('HIGH','Alto')]

    customer    = models.OneToOneField('transactions.Customer', on_delete=models.PROTECT,
                                        related_name='pep_registry')
    position    = models.CharField(max_length=200)
    institution = models.CharField(max_length=200)
    since_date  = models.DateField()
    until_date  = models.DateField(null=True, blank=True)
    risk_level  = models.CharField(max_length=10, choices=RISK_CHOICES, default='HIGH')
    enhanced_dd = models.BooleanField(default=True)
    review_date = models.DateField()
    notes       = models.TextField(blank=True)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                       related_name='pep_registered')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reports_pep'
        ordering = ['-created_at']

    @property
    def is_active(self):
        from datetime import date
        return self.until_date is None or self.until_date >= date.today()


class DailyOperationLog(models.Model):
    """Libro Diario de Operaciones — ASFI Art. 14"""
    STATUS_CHOICES = [('OPEN','Abierto'),('CLOSED','Cerrado'),('LOCKED','Bloqueado')]

    log_date            = models.DateField()
    branch              = models.ForeignKey('users.Branch', on_delete=models.PROTECT,
                                             related_name='daily_logs')
    status              = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN')
    total_transactions  = models.IntegerField(default=0)
    total_buy_bob       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_sell_bob      = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_profit_bob    = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    rte_count           = models.IntegerField(default=0)
    opening_balance_bob = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    closing_balance_bob = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    excel_file          = models.CharField(max_length=500, blank=True)
    pdf_file            = models.CharField(max_length=500, blank=True)
    closed_by           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                             null=True, blank=True, related_name='logs_closed')
    closed_at           = models.DateTimeField(null=True, blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    notes               = models.TextField(blank=True)

    class Meta:
        db_table        = 'reports_daily_log'
        unique_together = ['log_date', 'branch']
        ordering        = ['-log_date']


class GeneratedReport(models.Model):
    """Registro central de todos los informes generados"""
    REPORT_TYPE_CHOICES = [
        ('RTE_MONTHLY',   'RTE Mensual ASFI'),
        ('ROUE_REPORT',   'ROUE ASFI'),
        ('PEP_LIST',      'Listado PEP ASFI'),
        ('DAILY_LOG',     'Libro Diario ASFI'),
        ('PNL_DAILY',     'P&G Diario'),
        ('PNL_MONTHLY',   'P&G Mensual'),
        ('PROFITABILITY', 'Rentabilidad Divisa/Sucursal'),
        ('CASHFLOW',      'Proyección Flujo de Caja'),
        ('COMPARATIVE',   'Comparativo Período Anterior'),
        ('CLIENT_RANKING','Ranking de Clientes'),
    ]
    FORMAT_CHOICES = [('EXCEL','Excel'),('PDF','PDF')]

    report_type  = models.CharField(max_length=30, choices=REPORT_TYPE_CHOICES)
    format       = models.CharField(max_length=10, choices=FORMAT_CHOICES)
    date_from    = models.DateField()
    date_to      = models.DateField()
    file_path    = models.CharField(max_length=500)
    file_size_kb = models.IntegerField(default=0)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                      related_name='reports_generated')
    generated_at = models.DateTimeField(auto_now_add=True)
    parameters   = models.JSONField(default=dict)

    class Meta:
        db_table = 'reports_generated'
        ordering = ['-generated_at']