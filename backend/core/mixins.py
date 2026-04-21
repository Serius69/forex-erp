# core/mixins.py
"""
Mixins de modelo para patrones comunes: soft-delete, timestamps, versionado.
"""
import logging
from django.db import models
from django.utils import timezone

log = logging.getLogger('kapitalya.core.mixins')


# ─────────────────────────────────────────────────────────────────────────────
# SoftDeleteQuerySet / SoftDeleteManager
# ─────────────────────────────────────────────────────────────────────────────

class SoftDeleteQuerySet(models.QuerySet):
    def delete(self, deleted_by=None):
        """Soft-delete en bulk: marca is_deleted=True en lugar de DROP."""
        return self.update(
            is_deleted=True,
            deleted_at=timezone.now(),
            deleted_by_id=deleted_by.id if deleted_by and hasattr(deleted_by, 'id') else None,
        )

    def hard_delete(self):
        """Borrado físico real — solo para tareas de limpieza autorizadas."""
        return super().delete()

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def only_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=True)


# ─────────────────────────────────────────────────────────────────────────────
# SoftDeleteMixin
# ─────────────────────────────────────────────────────────────────────────────

class SoftDeleteMixin(models.Model):
    """
    Soft-delete para modelos críticos — nunca borra físicamente el registro.

    Uso:
        class Transaction(SoftDeleteMixin, models.Model):
            ...

        Transaction.objects.all()          # solo activos
        Transaction.objects.with_deleted() # todos
        tx.delete(deleted_by=request.user) # soft-delete
        tx.restore()                       # restaurar
    """
    is_deleted  = models.BooleanField(default=False, db_index=True)
    deleted_at  = models.DateTimeField(null=True, blank=True)
    deleted_by  = models.ForeignKey(
        'users.User',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    objects       = SoftDeleteManager()
    all_objects   = models.Manager()  # sin filtro — acceso explícito

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, deleted_by=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if deleted_by:
            self.deleted_by = deleted_by
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        log.info('SOFT_DELETE model=%s id=%s by=%s', self.__class__.__name__, self.pk, deleted_by)

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        log.info('SOFT_RESTORE model=%s id=%s', self.__class__.__name__, self.pk)

    def hard_delete(self):
        super().delete()


# ─────────────────────────────────────────────────────────────────────────────
# TimestampMixin
# ─────────────────────────────────────────────────────────────────────────────

class TimestampMixin(models.Model):
    """Añade created_at / updated_at automáticos."""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ─────────────────────────────────────────────────────────────────────────────
# VersionedMixin — Historial inmutable de cambios en campos críticos
# ─────────────────────────────────────────────────────────────────────────────

class VersionedMixin(models.Model):
    """
    Versionado automático de registros críticos (tasas, transacciones).
    Guarda un snapshot JSON antes de cada save() con campos que cambiaron.

    La tabla de versiones vive en <app_label>_<model_name>_version.
    """
    version      = models.PositiveIntegerField(default=1, editable=False)
    version_hash = models.CharField(max_length=40, blank=True, editable=False)

    class Meta:
        abstract = True

    def _compute_hash(self, data: dict) -> str:
        import hashlib, json
        return hashlib.sha1(
            json.dumps(data, sort_keys=True, default=str).encode()
        ).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk:
            self.version += 1
        # Compute hash of tracked fields if subclass declares _version_fields
        tracked = getattr(self, '_version_fields', [])
        if tracked:
            snapshot = {f: getattr(self, f, None) for f in tracked}
            self.version_hash = self._compute_hash(snapshot)
        super().save(*args, **kwargs)
