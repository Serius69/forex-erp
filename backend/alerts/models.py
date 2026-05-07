"""
AlertLog — registro persistente unificado de todas las alertas del sistema.

Centraliza alertas provenientes de:
  SNAPSHOT    — comparación de snapshots (AlertEngine)
  TRANSACTION — anomalías en transacciones forex
  ANOMALY     — detector de anomalías financieras (AnomalyDetector)
  SYSTEM      — salud de infraestructura (Celery, DB, ML, tasas)
  INVENTORY   — stock de divisas e inventario
  RATES       — variaciones anómalas de tasas

Cada alerta se persiste en BD, se emite por WebSocket y opcionalmente
escala por severity al sistema de cache (SystemAlert).
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AlertLog(models.Model):
    # ── Fuente ────────────────────────────────────────────────────────────────
    SOURCE_SNAPSHOT    = 'SNAPSHOT'
    SOURCE_TRANSACTION = 'TRANSACTION'
    SOURCE_ANOMALY     = 'ANOMALY'
    SOURCE_SYSTEM      = 'SYSTEM'
    SOURCE_INVENTORY   = 'INVENTORY'
    SOURCE_RATES       = 'RATES'
    # Categorías del motor de alertas inteligente (AlertGenerator)
    SOURCE_PRECIO      = 'PRECIO'
    SOURCE_RIESGO      = 'RIESGO'
    SOURCE_OPERATIVO   = 'OPERATIVO'
    SOURCE_OPORTUNIDAD = 'OPORTUNIDAD'

    SOURCE_CHOICES = [
        (SOURCE_SNAPSHOT,    'Comparación de Snapshot'),
        (SOURCE_TRANSACTION, 'Transacción Forex'),
        (SOURCE_ANOMALY,     'Detector de Anomalías'),
        (SOURCE_SYSTEM,      'Infraestructura del Sistema'),
        (SOURCE_INVENTORY,   'Inventario'),
        (SOURCE_RATES,       'Tasas de Cambio'),
        (SOURCE_PRECIO,      'Movimiento de Precio'),
        (SOURCE_RIESGO,      'Riesgo de Mercado'),
        (SOURCE_OPERATIVO,   'Operativo'),
        (SOURCE_OPORTUNIDAD, 'Oportunidad de Mercado'),
    ]

    # ── Severidad (unificada entre todos los subsistemas) ─────────────────────
    SEV_CRITICAL = 'CRITICAL'
    SEV_HIGH     = 'HIGH'
    SEV_MEDIUM   = 'MEDIUM'
    SEV_LOW      = 'LOW'

    SEVERITY_CHOICES = [
        (SEV_CRITICAL, 'Crítica'),
        (SEV_HIGH,     'Alta'),
        (SEV_MEDIUM,   'Media'),
        (SEV_LOW,      'Baja'),
    ]

    SEVERITY_ORDER = {SEV_CRITICAL: 0, SEV_HIGH: 1, SEV_MEDIUM: 2, SEV_LOW: 3}

    # ── Campos ────────────────────────────────────────────────────────────────
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    source     = models.CharField(max_length=20, choices=SOURCE_CHOICES, db_index=True)
    alert_type = models.CharField(max_length=60, db_index=True)
    severity   = models.CharField(max_length=10, choices=SEVERITY_CHOICES, db_index=True)

    title             = models.CharField(max_length=200)
    message           = models.TextField()
    accion_sugerida   = models.TextField(
        blank=True, default='',
        help_text='Acción concreta recomendada para resolver o aprovechar la alerta.',
    )
    data    = models.JSONField(default=dict, blank=True,
                               help_text='Contexto adicional: deltas, valores, umbrales, etc.')

    branch = models.ForeignKey(
        'users.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='alert_logs',
        help_text='Sucursal involucrada (NULL = sistema global).',
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='alertlog_triggered',
    )

    is_acknowledged  = models.BooleanField(default=False, db_index=True)
    acknowledged_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='alertlog_acknowledged',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table            = 'alerts_log'
        ordering            = ['-created_at']
        verbose_name        = 'Alerta'
        verbose_name_plural = 'Alertas'
        indexes = [
            models.Index(fields=['is_acknowledged', '-created_at'],
                         name='alerts_unack_recent_idx'),
            models.Index(fields=['severity', '-created_at'],
                         name='alerts_severity_recent_idx'),
            models.Index(fields=['source', '-created_at'],
                         name='alerts_source_recent_idx'),
        ]

    def __str__(self) -> str:
        ack = '✓' if self.is_acknowledged else '!'
        return f'[{ack}] {self.severity} {self.source}/{self.alert_type} — {self.title[:60]}'

    def acknowledge(self, user=None) -> None:
        """Marca la alerta como reconocida."""
        self.is_acknowledged = True
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        self.save(update_fields=['is_acknowledged', 'acknowledged_by', 'acknowledged_at'])


class FrontendErrorLog(models.Model):
    """Errores del frontend capturados por Error Boundaries y apiClient."""

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    error_id        = models.CharField(max_length=64, db_index=True)
    error_type      = models.CharField(max_length=64, default='UnknownError', db_index=True)
    message         = models.TextField()
    stack           = models.TextField(blank=True)
    component_stack = models.TextField(blank=True)
    url             = models.CharField(max_length=500, blank=True)
    user_agent      = models.CharField(max_length=300, blank=True)
    user_id         = models.IntegerField(null=True, blank=True, db_index=True)
    company_id      = models.IntegerField(null=True, blank=True)
    extra           = models.JSONField(default=dict, blank=True)
    ip_address      = models.GenericIPAddressField(null=True, blank=True)
    created_at      = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table            = 'alerts_frontend_error_log'
        ordering            = ['-created_at']
        verbose_name        = 'Error Frontend'
        verbose_name_plural = 'Errores Frontend'
        indexes = [
            models.Index(fields=['error_type', '-created_at'], name='fe_err_type_recent_idx'),
        ]

    def __str__(self) -> str:
        return f"[{self.error_type}] {self.message[:80]} ({self.error_id})"
