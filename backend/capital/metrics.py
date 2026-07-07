# capital/metrics.py
"""
KPIs de negocio para la casa de cambio.

Todos los KPIs se cachean en Redis para servir dashboards en tiempo real.
TTL: 300 s (5 min) por defecto, configurable vía settings.CAPITAL_KPI_CACHE_TTL.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.core.cache import cache
from django.db.models import Sum, Avg, Count, F, Q
from django.utils import timezone

log = logging.getLogger('capital.metrics')

_CACHE_KEY = 'capital_kpis:{branch_id}:{today}'
_CACHE_TTL = 300


class CapitalKPIService:
    """
    Calcula y cachea KPIs financieros de la casa de cambio.

    Uso:
        svc  = CapitalKPIService()
        kpis = svc.get_kpis(branch_id=1)
    """

    def get_kpis(self, branch_id: int, force: bool = False) -> dict:
        from django.conf import settings
        ttl = getattr(settings, 'CAPITAL_KPI_CACHE_TTL', _CACHE_TTL)
        today = timezone.localdate()
        cache_key = _CACHE_KEY.format(branch_id=branch_id, today=today)

        if not force:
            cached = cache.get(cache_key)
            if cached:
                return cached

        kpis = self._compute(branch_id)
        try:
            cache.set(cache_key, kpis, ttl)
        except Exception:
            pass
        return kpis

    def invalidate(self, branch_id: int) -> None:
        today = timezone.localdate()
        cache.delete(_CACHE_KEY.format(branch_id=branch_id, today=today))

    def _compute(self, branch_id: int) -> dict:
        kpis: dict = {}
        today = timezone.localdate()

        # ── Métricas de transacciones ─────────────────────────────────────────
        try:
            from transactions.models import Transaction
            from django.db.models import Sum

            base_qs = Transaction.objects.filter(
                branch_id=branch_id, status='COMPLETED'
            )
            # Hoy
            today_qs = base_qs.filter(created_at__date=today)
            kpis['tx_count_today']      = today_qs.count()
            kpis['volume_bob_today']    = str(today_qs.aggregate(t=Sum('amount_to'))['t'] or 0)

            # Últimos 30 días
            since_30d = today - timezone.timedelta(days=30)
            m30_qs = base_qs.filter(created_at__date__gte=since_30d)
            kpis['tx_count_30d']        = m30_qs.count()
            kpis['volume_bob_30d']      = str(m30_qs.aggregate(t=Sum('amount_to'))['t'] or 0)
        except Exception as exc:
            log.warning('KPI_TX_ERR err=%s', exc)
            kpis.update({'tx_count_today': 0, 'volume_bob_today': '0',
                         'tx_count_30d': 0,   'volume_bob_30d':   '0'})

        # ── Rotación de inventario ────────────────────────────────────────────
        try:
            from inventory.models import CurrencyInventory
            inventories = CurrencyInventory.objects.filter(branch_id=branch_id).select_related('currency')
            inv_details = []
            for inv in inventories:
                code = inv.currency.code
                bal  = float(inv.total_balance)
                # Días de inventario = balance / volumen_diario_promedio
                since = today - timezone.timedelta(days=30)
                from transactions.models import Transaction
                from django.db.models import Sum as DSum
                vol_30d = (
                    Transaction.objects
                    .filter(branch_id=branch_id, currency_from__code=code,
                            status='COMPLETED', created_at__date__gte=since)
                    .aggregate(t=DSum('amount_from'))['t'] or 0
                )
                daily_avg = float(vol_30d) / 30 if vol_30d else 0
                days_inv  = round(bal / daily_avg, 1) if daily_avg > 0 else None
                inv_details.append({
                    'currency':      code,
                    'balance':       str(inv.total_balance),
                    'daily_avg_30d': str(round(daily_avg, 2)),
                    'days_inventory': days_inv,
                    'stock_pct':     str(inv.stock_level_percentage),
                })
            kpis['inventory_rotation'] = inv_details
        except Exception as exc:
            log.warning('KPI_INV_ERR err=%s', exc)
            kpis['inventory_rotation'] = []

        # ── P&L del día y margen ──────────────────────────────────────────────
        try:
            from rates.profitability import ProfitabilityAnalyzer
            from users.models import Branch
            branch = Branch.objects.get(pk=branch_id)
            analyzer = ProfitabilityAnalyzer()
            rpt = analyzer.analyze(
                company_id=branch.company_id,
                date_from=today,
                date_to=today,
                branch_id=branch_id,
            )
            kpis['margin_bob_today']     = str(rpt.total_margin_bob)
            kpis['avg_margin_pct_today'] = str(rpt.avg_margin_pct)
            kpis['margin_alerts']        = len(rpt.alerts)
        except Exception as exc:
            log.warning('KPI_PNL_ERR err=%s', exc)
            kpis.update({'margin_bob_today': '0', 'avg_margin_pct_today': '0', 'margin_alerts': 0})

        # ── Break-even spread ─────────────────────────────────────────────────
        try:
            # break_even_spread = costos_fijos_diarios / volumen_diario_esperado
            from capital.models import Gasto
            costs = Gasto.objects.filter(branch_id=branch_id, fecha=today)
            costos_hoy = costs.aggregate(t=Sum('monto_bob'))['t'] or Decimal('0')
            vol_hoy = Decimal(kpis.get('volume_bob_today', '0'))
            if vol_hoy > 0:
                kpis['break_even_spread_pct'] = str(
                    (costos_hoy / vol_hoy * 100).quantize(Decimal('0.0001'))
                )
            else:
                kpis['break_even_spread_pct'] = '0'
            kpis['operating_costs_today'] = str(costos_hoy)
        except Exception as exc:
            log.warning('KPI_BREAKEVEN_ERR err=%s', exc)
            kpis.update({'break_even_spread_pct': '0', 'operating_costs_today': '0'})

        # ── ROE diario (simplificado) ─────────────────────────────────────────
        try:
            from capital.position_service import CapitalPositionService
            svc  = CapitalPositionService()
            snap = svc.get_real_time_position(branch_id)
            net_capital = Decimal(str(snap.net_capital_par))
            margin_today = Decimal(kpis.get('margin_bob_today', '0'))
            if net_capital > 0:
                roe_daily = (margin_today / net_capital * 100).quantize(Decimal('0.0001'))
                # Anualizar: × 365 (simplificado, no compuesto)
                roe_annual = roe_daily * 365
                kpis['roe_daily_pct']  = str(roe_daily)
                kpis['roe_annual_pct'] = str(roe_annual)
            else:
                kpis['roe_daily_pct']  = '0'
                kpis['roe_annual_pct'] = '0'
            kpis['net_capital_bob_par'] = str(snap.net_capital_par)
            kpis['net_capital_bob_off'] = str(snap.net_capital_off)
        except Exception as exc:
            log.warning('KPI_ROE_ERR err=%s', exc)
            kpis.update({'roe_daily_pct': '0', 'roe_annual_pct': '0',
                         'net_capital_bob_par': '0', 'net_capital_bob_off': '0'})

        # ── WACC de divisas ───────────────────────────────────────────────────
        try:
            from capital.models import CurrencyPosition
            positions = CurrencyPosition.objects.filter(branch_id=branch_id).select_related('currency')
            total_cost = Decimal('0')
            total_value = Decimal('0')
            for pos in positions:
                from rates.parallel_rate_service import ParallelRateService
                par_rate = ParallelRateService().get_cached_rate(pos.currency.code) or pos.avg_acquisition_cost
                pos_val = pos.net_position * par_rate
                if pos_val > 0:
                    total_cost  += pos.net_position * pos.avg_acquisition_cost
                    total_value += pos_val
            wacc = (total_cost / total_value).quantize(Decimal('0.0001')) if total_value > 0 else Decimal('0')
            kpis['wacc_currencies'] = str(wacc)
        except Exception as exc:
            log.warning('KPI_WACC_ERR err=%s', exc)
            kpis['wacc_currencies'] = '0'

        kpis['computed_at'] = timezone.now().isoformat()
        kpis['branch_id']   = branch_id
        return kpis
