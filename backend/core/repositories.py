# core/repositories.py
"""
Patrón Repository para aislar consultas DB de la lógica de negocio.

Uso:
    class TransactionRepository(BaseRepository):
        model = Transaction

        def completed_today(self, branch):
            return self.filter(
                branch=branch,
                status='COMPLETED',
                created_at__date=date.today(),
            )

    repo = TransactionRepository()
    txs  = repo.completed_today(branch)
"""
from __future__ import annotations
import logging
from typing import Any, Optional
from django.db import models
from django.db.models import QuerySet

log = logging.getLogger('kapitalya.core.repositories')


class BaseRepository:
    """
    Repository base: thin wrapper sobre Django ORM.
    Provee métodos consistentes para operaciones comunes sin acoplarse a vistas.
    """
    model: type[models.Model] = None  # Subclases DEBEN definir esto

    def __init__(self):
        if self.model is None:
            raise NotImplementedError(f'{self.__class__.__name__} must define `model`')
        self._manager = self.model._default_manager

    # ── Queries ───────────────────────────────────────────────────────────────

    def all(self) -> QuerySet:
        return self._manager.all()

    def filter(self, **kwargs) -> QuerySet:
        return self._manager.filter(**kwargs)

    def get(self, **kwargs) -> models.Model:
        return self._manager.get(**kwargs)

    def get_or_none(self, **kwargs) -> Optional[models.Model]:
        try:
            return self._manager.get(**kwargs)
        except self.model.DoesNotExist:
            return None

    def exists(self, **kwargs) -> bool:
        return self._manager.filter(**kwargs).exists()

    def count(self, **kwargs) -> int:
        return self._manager.filter(**kwargs).count()

    def first(self, **kwargs) -> Optional[models.Model]:
        return self._manager.filter(**kwargs).first()

    def last(self, **kwargs) -> Optional[models.Model]:
        return self._manager.filter(**kwargs).last()

    def select_related(self, *fields) -> QuerySet:
        return self._manager.select_related(*fields)

    def prefetch_related(self, *fields) -> QuerySet:
        return self._manager.prefetch_related(*fields)

    # ── Writes ────────────────────────────────────────────────────────────────

    def create(self, **kwargs) -> models.Model:
        instance = self._manager.create(**kwargs)
        log.debug('REPO_CREATE model=%s id=%s', self.model.__name__, instance.pk)
        return instance

    def update_or_create(self, defaults: dict, **kwargs):
        instance, created = self._manager.update_or_create(defaults=defaults, **kwargs)
        log.debug('REPO_UOC model=%s id=%s created=%s', self.model.__name__, instance.pk, created)
        return instance, created

    def bulk_create(self, objects: list, batch_size: int = 500, **kwargs) -> list:
        return self._manager.bulk_create(objects, batch_size=batch_size, **kwargs)

    def bulk_update(self, objects: list, fields: list, batch_size: int = 500) -> int:
        return self._manager.bulk_update(objects, fields, batch_size=batch_size)

    def delete(self, **kwargs) -> tuple[int, dict]:
        deleted, info = self._manager.filter(**kwargs).delete()
        log.info('REPO_DELETE model=%s count=%s filter=%s', self.model.__name__, deleted, kwargs)
        return deleted, info

    # ── Aggregations ──────────────────────────────────────────────────────────

    def aggregate(self, **kwargs) -> dict:
        return self._manager.aggregate(**kwargs)

    def values(self, *fields) -> QuerySet:
        return self._manager.values(*fields)

    def values_list(self, *fields, **kwargs) -> QuerySet:
        return self._manager.values_list(*fields, **kwargs)

    def annotate(self, **kwargs) -> QuerySet:
        return self._manager.annotate(**kwargs)

    # ── Raw SQL (escape hatch) ────────────────────────────────────────────────

    def raw(self, query: str, params: Any = None) -> models.query.RawQuerySet:
        log.debug('REPO_RAW model=%s', self.model.__name__)
        return self._manager.raw(query, params)


# ─────────────────────────────────────────────────────────────────────────────
# Concrete repositories — importar desde las apps correspondientes
# ─────────────────────────────────────────────────────────────────────────────

class TransactionRepository(BaseRepository):
    @property
    def model(self):
        from transactions.models import Transaction
        return Transaction

    def completed_for_branch(self, branch, date_from=None, date_to=None) -> QuerySet:
        qs = self.filter(branch=branch, status='COMPLETED')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs.select_related('customer', 'currency_from', 'currency_to', 'cashier')

    def today_stats(self, branch) -> dict:
        from django.db.models import Sum, Count
        from django.utils import timezone
        today = timezone.localdate()
        qs = self.filter(branch=branch, status='COMPLETED', created_at__date=today)
        return qs.aggregate(
            count=Count('id'),
            volume_bob=Sum('amount_to'),
            volume_foreign=Sum('amount_from'),
        )


class ExchangeRateRepository(BaseRepository):
    @property
    def model(self):
        from rates.models import ExchangeRate
        return ExchangeRate

    def current_rates(self, currency_code: str = None) -> QuerySet:
        qs = self.filter(valid_until__isnull=True, is_primary=True)
        if currency_code:
            qs = qs.filter(currency_from__code=currency_code)
        return qs.select_related('currency_from', 'currency_to', 'rate_source')

    def rate_history(self, currency_code: str, days: int = 30) -> QuerySet:
        from django.utils import timezone
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=days)
        return self.filter(
            currency_from__code=currency_code,
            fetched_at__gte=cutoff,
        ).order_by('fetched_at')


class InventoryRepository(BaseRepository):
    @property
    def model(self):
        from inventory.models import CurrencyInventory
        return CurrencyInventory

    def for_branch(self, branch) -> QuerySet:
        return self.filter(branch=branch).select_related('currency', 'branch')

    def low_stock(self, branch) -> QuerySet:
        from django.db.models import F
        return self.filter(
            branch=branch,
            physical_balance__lte=F('minimum_stock'),
        ).select_related('currency')
