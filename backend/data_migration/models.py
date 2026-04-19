# data_migration/models.py
"""
Modelos para el sistema de migración de datos desde Google Sheets.

MigrationLog      — registro de cada migración ejecutada
MigrationCheckpoint — punto de control para resume después de falla
ColumnMapping     — mapeo de columnas Google Sheets → modelo Django
"""
from __future__ import annotations
import uuid
from django.db import models
from django.conf import settings


class MigrationLog(models.Model):
    """Registro de cada ejecución de migración."""

    STATUS_PENDING    = 'PENDING'
    STATUS_RUNNING    = 'RUNNING'
    STATUS_PAUSED     = 'PAUSED'
    STATUS_COMPLETED  = 'COMPLETED'
    STATUS_FAILED     = 'FAILED'
    STATUS_VALIDATED  = 'VALIDATED'

    STATUS_CHOICES = [
        (STATUS_PENDING,   'Pendiente'),
        (STATUS_RUNNING,   'Ejecutando'),
        (STATUS_PAUSED,    'Pausado'),
        (STATUS_COMPLETED, 'Completado'),
        (STATUS_FAILED,    'Fallido'),
        (STATUS_VALIDATED, 'Validado'),
    ]

    TARGET_CHOICES = [
        ('transactions', 'Transacciones'),
        ('rates',        'Tasas de cambio'),
        ('inventory',    'Inventario'),
        ('customers',    'Clientes'),
        ('capital',      'Capital / Gastos'),
        ('users',        'Usuarios'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name            = models.CharField(max_length=200, help_text='Nombre descriptivo de la migración')
    spreadsheet_id  = models.CharField(max_length=200, help_text='ID del Google Spreadsheet')
    sheet_name      = models.CharField(max_length=200, help_text='Nombre de la hoja (tab)')
    target_model    = models.CharField(max_length=50, choices=TARGET_CHOICES, db_index=True)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                       default=STATUS_PENDING, db_index=True)

    # Contadores
    total_rows      = models.IntegerField(default=0)
    processed_rows  = models.IntegerField(default=0)
    success_rows    = models.IntegerField(default=0)
    error_rows      = models.IntegerField(default=0)
    skipped_rows    = models.IntegerField(default=0)

    # Opciones de ejecución
    dry_run         = models.BooleanField(default=False, help_text='Si True, no persiste cambios')
    skip_errors     = models.BooleanField(default=False, help_text='Continuar si hay errores de fila')
    batch_size      = models.IntegerField(default=100)

    # Resultados
    error_log       = models.JSONField(default=list, blank=True)
    summary         = models.JSONField(default=dict, blank=True)

    # Auditoría
    created_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='migrations_created',
    )
    started_at      = models.DateTimeField(null=True, blank=True)
    finished_at     = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'data_migration_log'
        ordering  = ['-created_at']
        verbose_name        = 'Log de migración'
        verbose_name_plural = 'Logs de migración'

    def __str__(self):
        return f'{self.name} [{self.status}] {self.processed_rows}/{self.total_rows}'

    @property
    def progress_pct(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return round(self.processed_rows / self.total_rows * 100, 1)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class MigrationCheckpoint(models.Model):
    """
    Punto de control para reanudar migraciones interrumpidas.
    Almacena el último batch procesado y el estado intermedio.
    """
    migration       = models.OneToOneField(
        MigrationLog, on_delete=models.CASCADE, related_name='checkpoint',
    )
    last_row_index  = models.IntegerField(default=0, help_text='Índice de la última fila procesada (0-based)')
    last_batch_num  = models.IntegerField(default=0)
    state_snapshot  = models.JSONField(default=dict, blank=True,
                                       help_text='Estado intermedio (WAC, saldos, etc.)')
    saved_at        = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'data_migration_checkpoint'
        verbose_name        = 'Checkpoint de migración'
        verbose_name_plural = 'Checkpoints de migración'

    def __str__(self):
        return f'Checkpoint [{self.migration.name}] row={self.last_row_index}'


class ColumnMapping(models.Model):
    """
    Mapeo de una columna del Google Sheet a un campo del modelo Django.
    Permite configurar transformaciones y validaciones por columna.
    """
    TRANSFORM_CHOICES = [
        ('none',         'Sin transformación'),
        ('upper',        'MAYÚSCULAS'),
        ('lower',        'minúsculas'),
        ('strip',        'Quitar espacios'),
        ('date_bo',      'Fecha formato boliviano (dd/mm/yyyy)'),
        ('date_iso',     'Fecha ISO (yyyy-mm-dd)'),
        ('decimal',      'Decimal (coma → punto)'),
        ('boolean',      'Booleano (si/no, 1/0, true/false)'),
        ('currency_code','Código de moneda (normalizar a USD/EUR/etc.)'),
        ('lookup_branch','Buscar sucursal por nombre'),
        ('lookup_user',  'Buscar usuario por username'),
    ]

    migration       = models.ForeignKey(
        MigrationLog, on_delete=models.CASCADE, related_name='column_mappings',
    )
    sheet_column    = models.CharField(max_length=100, help_text='Nombre de columna en el sheet')
    model_field     = models.CharField(max_length=100, help_text='Nombre del campo en el modelo Django')
    transform       = models.CharField(max_length=20, choices=TRANSFORM_CHOICES, default='none')
    is_required     = models.BooleanField(default=False)
    default_value   = models.CharField(max_length=200, blank=True,
                                       help_text='Valor por defecto si la celda está vacía')
    validation_regex = models.CharField(max_length=300, blank=True,
                                        help_text='Regex de validación (opcional)')
    order           = models.PositiveSmallIntegerField(default=0, help_text='Orden de procesamiento')

    class Meta:
        db_table  = 'data_migration_column_mapping'
        ordering  = ['order', 'sheet_column']
        unique_together = [('migration', 'sheet_column')]
        verbose_name        = 'Mapeo de columna'
        verbose_name_plural = 'Mapeos de columnas'

    def __str__(self):
        return f'{self.sheet_column} → {self.model_field} [{self.transform}]'
