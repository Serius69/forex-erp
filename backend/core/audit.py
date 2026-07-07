# core/audit.py
"""
Sistema de auditoría financiera completa.

AuditLog: registra cada cambio (CREATE/UPDATE/DELETE) en cualquier modelo Django
con snapshots before/after en JSON, usuario y IP.

Uso en views/services:
    from core.audit import audit_log
    audit_log(instance, action='UPDATE', before=before_dict, after=after_dict,
              user=request.user, ip=request.META.get('REMOTE_ADDR'))

Uso automático con mixin:
    class MyModel(AuditableMixin, models.Model):
        ...  # guarda automáticamente en save() y delete()
"""
from __future__ import annotations
import logging
from decimal import Decimal

log = logging.getLogger('kapitalya.audit')


def _serialize(obj) -> dict:
    """Serializa un model instance a dict de valores primitivos."""
    if obj is None:
        return {}
    data = {}
    for field in obj._meta.get_fields():
        try:
            if hasattr(field, 'attname'):
                val = getattr(obj, field.attname, None)
                if isinstance(val, Decimal):
                    val = str(val)
                elif hasattr(val, 'isoformat'):
                    val = val.isoformat()
                elif hasattr(val, 'pk'):
                    val = val.pk
                data[field.attname] = val
        except Exception:
            pass
    return data


# AuditLog model lives in users app (users/migrations/0003_add_audit_log.py)
# Import here for convenience:
# from users.models import AuditLog  (done lazily inside audit_log() to avoid circular)

ACTION_CREATE  = 'CREATE'
ACTION_UPDATE  = 'UPDATE'
ACTION_DELETE  = 'DELETE'
ACTION_REVERSE = 'REVERSE'


# ── Función auxiliar pública ──────────────────────────────────────────────────

def audit_log(
    instance,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    user=None,
    ip_address: str | None = None,
    user_agent: str = '',
    extra: dict | None = None,
) -> AuditLog | None:
    """
    Crea un registro de auditoría. Nunca lanza excepción (fire-and-forget).

    Args:
        instance:    Instancia del modelo afectado.
        action:      'CREATE', 'UPDATE', 'DELETE', 'REVERSE'.
        before/after: Snapshots JSON (si None, se serializa el instance actual).
        user:        Usuario que realizó el cambio.
        ip_address:  IP del cliente.
        extra:       Metadatos adicionales (ej: {'task': 'apply_transaction_effects'}).
    """
    try:
        from django.contrib.contenttypes.models import ContentType
        from users.models import AuditLog

        if before is None:
            before = {}
        if after is None and action != ACTION_DELETE:
            after = _serialize(instance)
        elif after is None:
            after = {}

        # Detectar campos cambiados
        changed = [k for k in set(list(before.keys()) + list(after.keys()))
                   if before.get(k) != after.get(k)]

        ct = ContentType.objects.get_for_model(instance.__class__)
        record = AuditLog(
            content_type   = ct,
            object_id      = str(instance.pk),
            object_repr    = str(instance)[:300],
            action         = action,
            before_json    = before,
            after_json     = after,
            changed_fields = changed,
            user           = user,
            ip_address     = ip_address,
            user_agent     = user_agent,
            extra          = extra or {},
        )
        record.save()
        return record
    except Exception as exc:
        log.warning('audit_log failed (non-critical): %s', exc)
        return None


# ── Mixin para modelos ────────────────────────────────────────────────────────

class AuditableMixin:
    """
    Mixin para modelos Django que registra automáticamente CREATE/UPDATE/DELETE.

    class Transaction(AuditableMixin, models.Model):
        _audit_user = None  # Asignar antes de save() si quieres tracking de usuario

    Para pasar el usuario:
        transaction._audit_user = request.user
        transaction._audit_ip   = request.META.get('REMOTE_ADDR')
        transaction.save()
    """
    _audit_user = None
    _audit_ip   = None
    _audit_extra = None

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        before = {} if is_new else _serialize(self.__class__.objects.filter(pk=self.pk).first())
        super().save(*args, **kwargs)
        after  = _serialize(self)
        action = AuditLog.ACTION_CREATE if is_new else AuditLog.ACTION_UPDATE
        audit_log(self, action=action, before=before, after=after,
                  user=self._audit_user, ip_address=self._audit_ip,
                  extra=self._audit_extra or {})

    def delete(self, *args, **kwargs):
        before = _serialize(self)
        audit_log(self, action=AuditLog.ACTION_DELETE, before=before, after={},
                  user=self._audit_user, ip_address=self._audit_ip,
                  extra=self._audit_extra or {})
        super().delete(*args, **kwargs)
