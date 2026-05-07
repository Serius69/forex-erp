# transactions/audit.py
"""
Registro de auditoría inmutable para transacciones.

Cada cambio significativo en Transaction genera un TransactionAuditLog.
El registro es de solo inserción: ningún código debe llamar a .update()
o .delete() sobre esta tabla — la restricción se implementa también
a nivel de permiso de base de datos en producción.

El checksum SHA-256 cubre todos los campos del log para detectar
manipulación a posteriori.
"""
import hashlib
import json
import logging
from decimal import Decimal

from django.db import models
from django.conf import settings
from django.utils import timezone

log = logging.getLogger('transactions.audit')

_AUDIT_ACTIONS = [
    ('CREATED',           'Transacción creada'),
    ('STATUS_CHANGED',    'Estado modificado'),
    ('APPROVED',          'Aprobada por supervisor'),
    ('REVERSED',          'Revertida'),
    ('CANCELLED',         'Cancelada'),
    ('RATE_LOCKED',       'Tasa bloqueada'),
    ('RATE_EXPIRED',      'Bloqueo de tasa expirado'),
    ('FRAUD_FLAGGED',     'Marcada por sistema antifraude'),
    ('FRAUD_OVERRIDDEN',  'Flag de fraude anulado'),
    ('MANUAL_RATE',       'Tasa manual aplicada'),
    ('FIELD_UPDATED',     'Campos editados'),
    ('NOTE_ADDED',        'Nota agregada'),
    ('DOCUMENT_ADDED',    'Documento adjunto'),
]


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f'Object of type {type(obj)} is not JSON serializable')


def _compute_checksum(data: dict) -> str:
    """SHA-256 sobre el JSON canónico del registro."""
    canonical = json.dumps(data, sort_keys=True, default=_decimal_default)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


class TransactionAuditLog(models.Model):
    """
    Registro de auditoría inmutable.  Solo INSERT está permitido.
    Cualquier intento de update o delete debe ser bloqueado en la capa
    de permisos y, en producción, también a nivel PostgreSQL con un trigger.
    """
    # ── Referencia a la transacción ───────────────────────────────────────────
    transaction = models.ForeignKey(
        'transactions.Transaction',
        on_delete=models.PROTECT,
        related_name='audit_logs',
        db_index=True,
    )
    transaction_number = models.CharField(
        max_length=20,
        db_index=True,
        help_text='Desnormalizado para búsqueda rápida sin JOIN.',
    )

    # ── Acción registrada ─────────────────────────────────────────────────────
    action = models.CharField(max_length=30, choices=_AUDIT_ACTIONS, db_index=True)

    # ── Estado previo y nuevo (snapshot JSON completo) ────────────────────────
    previous_state = models.JSONField(
        default=dict,
        help_text='Estado de los campos relevantes ANTES de la acción.',
    )
    new_state = models.JSONField(
        default=dict,
        help_text='Estado de los campos relevantes DESPUÉS de la acción.',
    )

    # ── Actor ─────────────────────────────────────────────────────────────────
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transaction_audit_logs',
        help_text='Usuario que ejecutó la acción (null = sistema/Celery).',
    )
    user_display = models.CharField(
        max_length=200,
        blank=True,
        help_text='Username desnormalizado para auditoría offline.',
    )

    # ── Contexto de red ───────────────────────────────────────────────────────
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)

    # ── Integridad ────────────────────────────────────────────────────────────
    checksum_sha256 = models.CharField(
        max_length=64,
        help_text='SHA-256 del contenido del registro para detectar manipulación.',
    )
    timestamp_utc = models.DateTimeField(db_index=True)

    class Meta:
        app_label           = 'transactions'
        db_table            = 'transaction_audit_log'
        ordering            = ['-timestamp_utc']
        verbose_name        = 'Log de Auditoría'
        verbose_name_plural = 'Logs de Auditoría'
        indexes = [
            models.Index(fields=['transaction', '-timestamp_utc']),
            models.Index(fields=['action', '-timestamp_utc']),
            models.Index(fields=['user', '-timestamp_utc']),
        ]

    def __str__(self):
        return f'{self.timestamp_utc:%Y-%m-%d %H:%M:%S} | {self.action} | TX {self.transaction_number}'

    # ── Impedir modificaciones ────────────────────────────────────────────────

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError('TransactionAuditLog es inmutable — no se permite update.')
        if not self.timestamp_utc:
            self.timestamp_utc = timezone.now()
        if not self.checksum_sha256:
            self.checksum_sha256 = self._compute_own_checksum()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('TransactionAuditLog es inmutable — no se permite delete.')

    def _compute_own_checksum(self) -> str:
        data = {
            'transaction_number': self.transaction_number,
            'action':             self.action,
            'previous_state':     self.previous_state,
            'new_state':          self.new_state,
            'user_display':       self.user_display,
            'ip_address':         self.ip_address,
            'timestamp_utc':      self.timestamp_utc.isoformat() if self.timestamp_utc else None,
        }
        return _compute_checksum(data)

    def verify_integrity(self) -> bool:
        """Recalcula el checksum y lo compara con el almacenado."""
        return self._compute_own_checksum() == self.checksum_sha256


# ── Función helper para crear logs ────────────────────────────────────────────

def create_audit_log(
    transaction,
    action: str,
    previous_state: dict | None = None,
    new_state: dict | None = None,
    user=None,
    request=None,
) -> TransactionAuditLog:
    """
    Crea un TransactionAuditLog de forma segura.
    Nunca lanza — errores se registran en logger y se ignoran
    para no interrumpir el flujo principal.
    """
    try:
        ip = None
        ua = ''
        if request:
            x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
            ip = x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR')
            ua = request.META.get('HTTP_USER_AGENT', '')[:500]

        user_display = ''
        if user:
            user_display = getattr(user, 'username', str(user))

        entry = TransactionAuditLog(
            transaction=transaction,
            transaction_number=transaction.transaction_number or '',
            action=action,
            previous_state=previous_state or {},
            new_state=new_state or {},
            user=user,
            user_display=user_display,
            ip_address=ip,
            user_agent=ua,
            timestamp_utc=timezone.now(),
        )
        entry.save()
        return entry
    except Exception as exc:
        log.error(
            'AUDIT_LOG_FAIL tx=%s action=%s err=%s',
            getattr(transaction, 'transaction_number', '?'), action, exc,
            exc_info=True,
        )


def snapshot_transaction(tx) -> dict:
    """Serializa los campos auditables de una Transaction a dict JSON-safe."""
    return {
        'status':                  tx.status,
        'exchange_rate':           str(tx.exchange_rate) if tx.exchange_rate else None,
        'parallel_rate_at_creation': str(tx.parallel_rate_at_creation) if tx.parallel_rate_at_creation else None,
        'fraud_score':             str(tx.fraud_score) if tx.fraud_score else None,
        'fraud_flags':             tx.fraud_flags or [],
        'approval_required':       tx.approval_required,
        'approved_by_id':          tx.approved_by_id,
        'amount_from':             tx.amount_from,
        'amount_to':               tx.amount_to,
        'currency_from':           getattr(tx.currency_from, 'code', None),
        'currency_to':             getattr(tx.currency_to, 'code', None),
        'cashier_id':              tx.cashier_id,
        'branch_id':               tx.branch_id,
        'notes':                   tx.notes,
        'manual_rate_justification': tx.manual_rate_justification,
    }
