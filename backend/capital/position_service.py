# capital/position_service.py
"""
Servicio de posición de capital en tiempo real.

Consolida: inventario de divisas + caja BOB + transacciones pendientes.
Valoriza simultáneamente a tasa paralela Y oficial.
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.core.cache import cache
from django.db import transaction as db_tx
from django.utils import timezone

log = logging.getLogger('capital.position')

_CACHE_KEY = 'capital_position:{branch_id}'
_CACHE_TTL = 30   # segundos (configurable vía settings.CAPITAL_POSITION_CACHE_TTL)


@dataclass
class CurrencyPositionDetail:
    currency_code:        str
    net_units:            Decimal
    avg_cost_bob:         Decimal
    value_parallel_bob:   Decimal
    value_official_bob:   Decimal
    unrealized_pnl_par:   Decimal
    unrealized_pnl_off:   Decimal
    parallel_rate:        Decimal
    official_rate:        Decimal


@dataclass
class CapitalPositionSnapshot:
    branch_id:            int
    branch_name:          str
    computed_at:          str
    # BOB líquido
    cash_bob:             Decimal
    digital_bob:          Decimal
    # Divisas valorizadas
    currencies:           list[CurrencyPositionDetail]
    total_foreign_par:    Decimal   # sum de divisas a tasa paralela
    total_foreign_off:    Decimal   # sum de divisas a tasa oficial
    # Pendientes
    pending_inflow_bob:   Decimal
    pending_outflow_bob:  Decimal
    # Resumen
    total_assets_par:     Decimal
    total_assets_off:     Decimal
    liabilities_bob:      Decimal
    net_capital_par:      Decimal
    net_capital_off:      Decimal


@dataclass
class PnLReport:
    period_start:   str
    period_end:     str
    branch_id:      int
    by_currency:    list[dict] = field(default_factory=list)
    by_type:        list[dict] = field(default_factory=list)
    by_cashier:     list[dict] = field(default_factory=list)
    total_margin:   Decimal    = Decimal('0')
    total_volume:   Decimal    = Decimal('0')
    avg_margin_pct: Decimal    = Decimal('0')


class CapitalPositionService:
    """
    Calcula la posición de capital en tiempo real para una sucursal.

    Uso:
        svc = CapitalPositionService()
        snap = svc.get_real_time_position(branch_id=1)
    """

    # ── Tasas actuales ────────────────────────────────────────────────────────

    @staticmethod
    def _get_rates(currency_code: str) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """Retorna (parallel_rate, official_rate) para la divisa. official_rate == parallel_rate."""
        parallel_rate = None
        try:
            from rates.parallel_rate_service import ParallelRateService
            svc    = ParallelRateService()
            result = svc.get_rate(currency_code)
            if result.consensus_rate:
                parallel_rate = result.consensus_rate
        except Exception as exc:
            log.warning('POS_PARALLEL_RATE_ERR cur=%s err=%s', currency_code, exc)

        return parallel_rate, parallel_rate

    # ── Caja BOB ──────────────────────────────────────────────────────────────

    @staticmethod
    def _get_cash_bob(branch) -> tuple[Decimal, Decimal, Decimal]:
        """Retorna (efectivo_fisico, digital, pasivos) de la caja actual."""
        try:
            from capital.models import CashBOB, CapitalComposicion
            today = timezone.localdate()
            bob = CashBOB.objects.filter(branch=branch, fecha=today).first()
            comp = CapitalComposicion.objects.filter(branch=branch, fecha=today).first()
            efectivo = bob.total_efectivo_fisico() if bob else Decimal('0')
            digital  = bob.qr_transferencias if bob else Decimal('0')
            pasivos  = comp.pasivos if comp else Decimal('0')
            return efectivo, digital, pasivos
        except Exception:
            return Decimal('0'), Decimal('0'), Decimal('0')

    # ── Transacciones pendientes ──────────────────────────────────────────────

    @staticmethod
    def _get_pending_flows(branch) -> tuple[Decimal, Decimal]:
        """Retorna (inflow_bob, outflow_bob) de transacciones no completadas."""
        try:
            from transactions.models import Transaction
            from django.db.models import Sum
            pending = Transaction.objects.filter(
                branch=branch,
                status__in=('PENDING', 'APPROVED', 'PROCESSING', 'PENDING_RATE'),
            )
            inflow = pending.filter(transaction_type='SELL').aggregate(
                t=Sum('amount_to'))['t'] or Decimal('0')
            outflow = pending.filter(transaction_type='BUY').aggregate(
                t=Sum('amount_to'))['t'] or Decimal('0')
            return Decimal(str(inflow)), Decimal(str(outflow))
        except Exception:
            return Decimal('0'), Decimal('0')

    # ── Posición en tiempo real ───────────────────────────────────────────────

    def get_real_time_position(self, branch_id: int, force: bool = False) -> CapitalPositionSnapshot:
        """
        Consolida posición completa de capital para la sucursal.
        Cache de 30 segundos (configurable).
        """
        from django.conf import settings
        ttl = getattr(settings, 'CAPITAL_POSITION_CACHE_TTL', _CACHE_TTL)
        cache_key = _CACHE_KEY.format(branch_id=branch_id)

        if not force:
            cached = cache.get(cache_key)
            if cached:
                return CapitalPositionSnapshot(**cached)

        try:
            from users.models import Branch
            branch = Branch.objects.get(pk=branch_id)
        except Exception:
            raise ValueError(f'Branch {branch_id} no encontrada')

        cash, digital, pasivos = self._get_cash_bob(branch)
        pending_in, pending_out = self._get_pending_flows(branch)

        # Inventario de divisas
        currencies: list[CurrencyPositionDetail] = []
        total_par = Decimal('0')
        total_off = Decimal('0')

        try:
            from inventory.models import CurrencyInventory
            inventories = (
                CurrencyInventory.objects
                .select_related('currency')
                .filter(branch=branch, currency__is_base_currency=False)
            )
            for inv in inventories:
                code = inv.currency.code
                units = inv.total_balance * inv.currency.scale_factor
                par_rate, off_rate = self._get_rates(code)
                if not par_rate:
                    continue

                off_rate = off_rate or par_rate
                # P&L usando posición DB si existe
                try:
                    from capital.models import CurrencyPosition
                    pos = CurrencyPosition.objects.filter(branch=branch, currency=inv.currency).first()
                    avg_cost = pos.avg_acquisition_cost if pos else par_rate
                except Exception:
                    avg_cost = par_rate

                val_par  = (units * par_rate).quantize(Decimal('0.01'))
                val_off  = (units * off_rate).quantize(Decimal('0.01'))
                book_val = (units * avg_cost).quantize(Decimal('0.01'))
                pnl_par  = val_par - book_val
                pnl_off  = val_off - book_val

                currencies.append(CurrencyPositionDetail(
                    currency_code=code,
                    net_units=units,
                    avg_cost_bob=avg_cost,
                    value_parallel_bob=val_par,
                    value_official_bob=val_off,
                    unrealized_pnl_par=pnl_par,
                    unrealized_pnl_off=pnl_off,
                    parallel_rate=par_rate,
                    official_rate=off_rate,
                ))
                total_par += val_par
                total_off += val_off
        except Exception as exc:
            log.warning('POS_INVENTORY_ERR branch=%s err=%s', branch_id, exc)

        total_assets_par = cash + digital + total_par
        total_assets_off = cash + digital + total_off
        net_par = total_assets_par - pasivos
        net_off = total_assets_off - pasivos

        snap = CapitalPositionSnapshot(
            branch_id=branch_id,
            branch_name=str(branch),
            computed_at=timezone.now().isoformat(),
            cash_bob=cash,
            digital_bob=digital,
            currencies=currencies,
            total_foreign_par=total_par,
            total_foreign_off=total_off,
            pending_inflow_bob=pending_in,
            pending_outflow_bob=pending_out,
            total_assets_par=total_assets_par,
            total_assets_off=total_assets_off,
            liabilities_bob=pasivos,
            net_capital_par=net_par,
            net_capital_off=net_off,
        )

        # Guardar en caché (serializar dataclasses)
        try:
            snap_dict = self._serialize_snapshot(snap)
            cache.set(cache_key, snap_dict, ttl)
        except Exception as exc:
            log.warning('POS_CACHE_ERR err=%s', exc)

        return snap

    def _serialize_snapshot(self, snap: CapitalPositionSnapshot) -> dict:
        def _d(v):
            if isinstance(v, Decimal):
                return str(v)
            return v

        return {
            'branch_id':         snap.branch_id,
            'branch_name':       snap.branch_name,
            'computed_at':       snap.computed_at,
            'cash_bob':          _d(snap.cash_bob),
            'digital_bob':       _d(snap.digital_bob),
            'currencies':        [
                {k: _d(v) for k, v in c.__dict__.items()} for c in snap.currencies
            ],
            'total_foreign_par':  _d(snap.total_foreign_par),
            'total_foreign_off':  _d(snap.total_foreign_off),
            'pending_inflow_bob': _d(snap.pending_inflow_bob),
            'pending_outflow_bob':_d(snap.pending_outflow_bob),
            'total_assets_par':   _d(snap.total_assets_par),
            'total_assets_off':   _d(snap.total_assets_off),
            'liabilities_bob':    _d(snap.liabilities_bob),
            'net_capital_par':    _d(snap.net_capital_par),
            'net_capital_off':    _d(snap.net_capital_off),
        }

    def invalidate(self, branch_id: int) -> None:
        cache.delete(_CACHE_KEY.format(branch_id=branch_id))

    # ── Snapshot diario ───────────────────────────────────────────────────────

    def save_daily_snapshot(self, branch_id: int) -> None:
        """
        Guarda el snapshot de posición de capital al cierre del día.
        Llamado por Celery Beat a las 23:45.
        """
        from capital.models import CurrencyPosition, CurrencyPositionHistory
        from rates.models import ExchangeRate

        today = timezone.localdate()
        try:
            from users.models import Branch
            branch = Branch.objects.get(pk=branch_id)
        except Exception as exc:
            log.error('SNAPSHOT_BRANCH_ERR branch=%s err=%s', branch_id, exc)
            return

        positions = CurrencyPosition.objects.filter(branch=branch).select_related('currency')
        with db_tx.atomic():
            for pos in positions:
                code = pos.currency.code
                par_rate, off_rate = self._get_rates(code)
                if par_rate:
                    pos.update_unrealized_pnl(par_rate, off_rate or par_rate)
                    pos.save(update_fields=['unrealized_pnl_parallel', 'unrealized_pnl_official',
                                           'parallel_rate_used', 'official_rate_used'])

                # Historial — solo si no hay ya para hoy
                exists = CurrencyPositionHistory.objects.filter(
                    position=pos, fecha=today, snapshot_type='DAILY'
                ).exists()
                if not exists:
                    CurrencyPositionHistory.objects.create(
                        position=pos,
                        fecha=today,
                        net_position=pos.net_position,
                        avg_acquisition_cost=pos.avg_acquisition_cost,
                        unrealized_pnl_parallel=pos.unrealized_pnl_parallel,
                        unrealized_pnl_official=pos.unrealized_pnl_official,
                        parallel_rate=pos.parallel_rate_used,
                        official_rate=pos.official_rate_used,
                        snapshot_type='DAILY',
                    )

        log.info('SNAPSHOT_SAVED branch=%s date=%s positions=%d', branch_id, today, positions.count())

    # ── P&L del período ───────────────────────────────────────────────────────

    def get_pnl_period(self, branch_id: int, start, end) -> PnLReport:
        """
        Calcula P&L realizado para el período (start, end).
        Usa ProfitabilityAnalyzer internamente.
        """
        from rates.profitability import ProfitabilityAnalyzer

        try:
            from users.models import Branch
            branch = Branch.objects.get(pk=branch_id)
        except Exception:
            raise ValueError(f'Branch {branch_id} no encontrada')

        analyzer = ProfitabilityAnalyzer()
        report   = analyzer.analyze(
            company_id=branch.company_id,
            date_from=start,
            date_to=end,
            branch_id=branch_id,
        )

        return PnLReport(
            period_start=str(start),
            period_end=str(end),
            branch_id=branch_id,
            by_currency=report.by_currency_pair,
            by_type=[],
            by_cashier=report.by_cashier,
            total_margin=report.total_margin_bob,
            total_volume=report.total_volume_foreign,
            avg_margin_pct=report.avg_margin_pct,
        )
