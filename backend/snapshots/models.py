# snapshots/models.py
"""
SystemSnapshot — registro inmutable del estado completo del sistema en un instante.

Cada snapshot captura:
  - capital (efectivo, QR, divisas, tarjetas)
  - caja BOB (desglose por denominación)
  - inventario de divisas (por sucursal)
  - inventario de tarjetas (stock + costos FIFO)

Los snapshots son APPEND-ONLY: nunca se modifican ni eliminan mediante la API.
La integridad se verifica con un checksum SHA-256 del campo data_json.
"""
import hashlib
import json

from django.conf import settings
from django.db import models
from django.utils import timezone


class SystemSnapshot(models.Model):
    # ── Módulo que originó el snapshot ───────────────────────────────────────
    MODULE_CHOICES = [
        ('capital',   'Capital / Caja'),
        ('forex',     'Transacción Forex'),
        ('tarjetas',  'Tarjetas Prepago'),
        ('gastos',    'Gasto Operativo'),
        ('caja_bob',  'Caja BOB'),
        ('inventory', 'Inventario'),
        ('manual',    'Manual / On-demand'),
        ('system',    'Sistema / Cierre de día'),
    ]

    # ── Acción que disparó el snapshot ───────────────────────────────────────
    ACTION_CHOICES = [
        ('create',      'Creación'),
        ('update',      'Actualización'),
        ('delete',      'Eliminación'),
        ('transaction', 'Transacción completada'),
        ('apertura',    'Apertura de día'),
        ('cierre',      'Cierre de día'),
        ('on_demand',   'Snapshot on-demand'),
    ]

    # ── Campos principales ────────────────────────────────────────────────────
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text='Momento exacto en que se capturó el estado.',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='system_snapshots',
        help_text='Usuario que desencadenó el cambio.',
    )
    branch = models.ForeignKey(
        'users.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='system_snapshots',
        help_text='Sucursal de contexto (NULL = todas las sucursales).',
    )

    module = models.CharField(
        max_length=20,
        choices=MODULE_CHOICES,
        db_index=True,
        help_text='Módulo del sistema que originó el snapshot.',
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        help_text='Tipo de acción que desencadenó el snapshot.',
    )

    # ── Estado completo del sistema ───────────────────────────────────────────
    data_json = models.JSONField(
        help_text=(
            'Estado completo del sistema en el momento del snapshot. '
            'Estructura: {capital, caja_bob, divisas, tarjetas}.'
        ),
    )
    metadata_json = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Contexto adicional: número de transacción, montos involucrados, '
            'sucursal, etc.'
        ),
    )

    # ── Integridad ────────────────────────────────────────────────────────────
    checksum = models.CharField(
        max_length=64,
        editable=False,
        help_text='SHA-256 de data_json (sort_keys=True). Para verificar integridad.',
    )

    class Meta:
        db_table            = 'snapshots_system'
        ordering            = ['-timestamp']
        verbose_name        = 'Snapshot del Sistema'
        verbose_name_plural = 'Snapshots del Sistema'
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['module', '-timestamp']),
            models.Index(fields=['branch', '-timestamp']),
            models.Index(fields=['user', '-timestamp']),
        ]

    def __str__(self) -> str:
        branch_str = self.branch.code if self.branch_id else 'ALL'
        return (
            f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] "
            f"{self.get_module_display()} / {self.get_action_display()} "
            f"— {branch_str}"
        )

    def save(self, *args, **kwargs):
        # Calcular checksum antes de guardar (o en primera inserción)
        if not self.checksum and self.data_json is not None:
            self.checksum = self._compute_checksum(self.data_json)
        super().save(*args, **kwargs)

    # ── Métodos de instancia ──────────────────────────────────────────────────

    @staticmethod
    def _compute_checksum(data: dict) -> str:
        """SHA-256 de data_json con claves ordenadas para reproducibilidad."""
        serialized = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

    def verify_integrity(self) -> bool:
        """
        Verifica que data_json no haya sido modificado comparando el checksum.
        Retorna True si el snapshot está íntegro.
        """
        return self.checksum == self._compute_checksum(self.data_json)

    @property
    def capital_total_bob(self) -> str:
        """Acceso rápido al total de capital del snapshot."""
        try:
            return self.data_json.get('capital', {}).get('total_bob', '0.00')
        except Exception:
            return '0.00'

    @property
    def is_stale(self) -> bool:
        """True si el snapshot tiene más de 24 horas."""
        return (timezone.now() - self.timestamp).total_seconds() > 86400
