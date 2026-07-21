# core/executive_dashboard.py
"""
Dashboard ejecutivo nivel CEO.

Endpoint: GET /api/dashboard/executive/

Agrega en una sola respuesta cacheada (TTL=60s):
- Capital total en tiempo real
- P&L hoy / semana / mes
- Volumen de transacciones (conteo + BOB) hoy/semana/mes
- Mejor y peor divisa por ganancia neta
- Exposición de riesgo actual
- Tasas paralelas actuales
- Alertas activas
"""
from __future__ import annotations
import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from django.core.cache import cache
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

log = logging.getLogger('kapitalya.dashboard.executive')

CACHE_TTL = 60  # segundos


def _safe_float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


class ExecutiveDashboardView(APIView):
    """GET /api/dashboard/executive/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        force    = request.query_params.get('refresh', '').lower() == 'true'
        # Aislamiento multi-tenant: sin company_id el dashboard agregaba capital,
        # P&L, transacciones, exposición e inventario de TODAS las empresas.
        company_id = getattr(request.user, 'company_id', None)
        branch_id  = request.query_params.get('branch_id')
        if branch_id:
            from users.models import Branch
            bqs = Branch.objects.all()
            if company_id:
                bqs = bqs.filter(company_id=company_id)
            try:
                branch_id = bqs.get(pk=branch_id).id  # valida empresa
            except (Branch.DoesNotExist, ValueError):
                return Response({'error': 'Sucursal no encontrada'}, status=404)
        cache_key = f'executive_dashboard:{company_id or "all"}:{branch_id or "all"}'

        if not force:
            cached = cache.get(cache_key)
            if cached:
                cached['from_cache'] = True
                return Response(cached)

        try:
            data = _build_dashboard(branch_id=branch_id, company_id=company_id)
            cache.set(cache_key, data, CACHE_TTL)
            return Response(data)
        except Exception as exc:
            log.exception('Executive dashboard build failed')
            return Response({'error': str(exc)}, status=500)


def _build_dashboard(branch_id=None, company_id=None) -> dict:
    today = timezone.now().date()
    week_start  = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    return {
        'generated_at':   timezone.now().isoformat(),
        'from_cache':     False,
        'capital':        _get_capital(branch_id, company_id),
        'pnl':            _get_pnl(today, week_start, month_start, branch_id, company_id),
        'transactions':   _get_transaction_stats(today, week_start, month_start, branch_id, company_id),
        'currencies':     _get_currency_performance(month_start, branch_id, company_id),
        'exposure':       _get_exposure_summary(branch_id, company_id),
        'rates':          _get_current_rates(),
        'ai_pricing':     _get_ai_pricing_summary(),
        'alerts':         _get_active_alerts(),
        'inventory':      _get_inventory_summary(branch_id, company_id),
    }


def _scope_company(qs, company_id, path='branch__company_id'):
    """Aísla un queryset por empresa (aislamiento multi-tenant)."""
    return qs.filter(**{path: company_id}) if company_id else qs


# ── Capital ───────────────────────────────────────────────────────────────────

def _get_capital(branch_id=None, company_id=None) -> dict:
    try:
        from capital.models import CapitalComposicion
        qs = _scope_company(CapitalComposicion.objects.all(), company_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        # CapitalComposicion es un registro DIARIO por sucursal: sumar todo el
        # histórico infla el capital (56 días ≈ Bs 14M fantasma). Se toma solo
        # la composición más reciente de cada sucursal.
        ultimas = list(qs.order_by('branch_id', '-fecha').distinct('branch_id'))

        total_bob     = sum(c.total_bob for c in ultimas)
        total_fuertes = sum(c.fuertes for c in ultimas)
        total_qr      = sum(c.qr_transferencias for c in ultimas)

        return {
            'total_bob':         _safe_float(total_bob),
            'efectivo_bob':      _safe_float(total_fuertes),
            'digital_bob':       _safe_float(total_qr),
            'branches':          len(ultimas),
        }
    except Exception as exc:
        log.debug('Capital fetch failed: %s', exc)
        return {'total_bob': None, 'efectivo_bob': None, 'digital_bob': None}


# ── P&L ───────────────────────────────────────────────────────────────────────

def _get_pnl(today: date, week_start: date, month_start: date, branch_id=None, company_id=None) -> dict:
    try:
        from analytics.models import PnLDailySnapshot
        from django.db.models import Sum

        qs = _scope_company(PnLDailySnapshot.objects.all(), company_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        def _agg(qs_filtered):
            agg = qs_filtered.aggregate(
                ganancia=Sum('ganancia_neta_bob'),
                ventas=Sum('ingreso_ventas_bob'),
                gastos=Sum('gastos_operativos_bob'),
            )
            return {
                'ganancia_neta':     _safe_float(agg['ganancia']),
                'ingreso_ventas':    _safe_float(agg['ventas']),
                'gastos_operativos': _safe_float(agg['gastos']),
            }

        return {
            'today':  _agg(qs.filter(fecha=today)),
            'week':   _agg(qs.filter(fecha__gte=week_start)),
            'month':  _agg(qs.filter(fecha__gte=month_start)),
        }
    except Exception as exc:
        log.debug('P&L fetch failed: %s', exc)
        return {'today': {}, 'week': {}, 'month': {}}


# ── Transacciones ─────────────────────────────────────────────────────────────

def _get_transaction_stats(today: date, week_start: date, month_start: date, branch_id=None, company_id=None) -> dict:
    try:
        from transactions.models import Transaction
        from django.db.models import Count, Sum

        qs = _scope_company(Transaction.objects.filter(status='COMPLETED'), company_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        def _stats(qs_period):
            agg = qs_period.aggregate(count=Count('id'), volumen=Sum('amount_from'))
            buys  = qs_period.filter(transaction_type='BUY').count()
            sells = qs_period.filter(transaction_type='SELL').count()
            return {
                'count':        agg['count'] or 0,
                'volume_bob':   _safe_float(agg['volumen']),
                'buys':         buys,
                'sells':        sells,
            }

        # Límites datetime sargables en TZ local (usan el índice (status,-created_at)
        # / tx_branch_completed_idx; created_at__date fuerza DATE(...) no-sargable).
        tz = timezone.get_current_timezone()
        day_start   = timezone.make_aware(datetime.combine(today, time.min), tz)
        day_end     = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min), tz)
        week_lo     = timezone.make_aware(datetime.combine(week_start, time.min), tz)
        month_lo    = timezone.make_aware(datetime.combine(month_start, time.min), tz)

        return {
            'today': _stats(qs.filter(created_at__gte=day_start, created_at__lt=day_end)),
            'week':  _stats(qs.filter(created_at__gte=week_lo)),
            'month': _stats(qs.filter(created_at__gte=month_lo)),
        }
    except Exception as exc:
        log.debug('Transaction stats failed: %s', exc)
        return {'today': {}, 'week': {}, 'month': {}}


# ── Rendimiento por divisa ────────────────────────────────────────────────────

def _get_currency_performance(month_start: date, branch_id=None, company_id=None) -> dict:
    try:
        from analytics.models import TransactionProfitLedger
        from django.db.models import Sum

        qs = _scope_company(TransactionProfitLedger.objects.filter(fecha__gte=month_start), company_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        by_currency = (qs.values('currency_code')
                       .annotate(ganancia=Sum('profit_bob'), count=Sum('id'))
                       .order_by('-ganancia'))

        currencies = list(by_currency)
        return {
            'best':  currencies[0] if currencies else None,
            'worst': currencies[-1] if len(currencies) > 1 else None,
            'all': [
                {'currency': c['currency_code'],
                 'ganancia_bob': _safe_float(c['ganancia'])}
                for c in currencies
            ],
        }
    except Exception as exc:
        log.debug('Currency performance failed: %s', exc)
        return {'best': None, 'worst': None, 'all': []}


# ── Exposición ────────────────────────────────────────────────────────────────

def _get_exposure_summary(branch_id=None, company_id=None) -> dict:
    try:
        from analytics.models import ExposureSnapshot
        from django.db.models import Sum
        from django.utils import timezone as tz

        cutoff = tz.now() - timedelta(hours=1)
        qs     = _scope_company(ExposureSnapshot.objects.filter(timestamp__gte=cutoff), company_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        agg = qs.aggregate(
            total_exposure=Sum('exposure_bob'),
            unrealized=Sum('unrealized_pnl_bob'),
        )
        critical  = qs.filter(alert_level='CRITICAL').count()
        warnings  = qs.filter(alert_level='WARNING').count()

        return {
            'total_exposure_bob': _safe_float(agg['total_exposure']),
            'unrealized_pnl_bob': _safe_float(agg['unrealized']),
            'critical_count':     critical,
            'warning_count':      warnings,
        }
    except Exception as exc:
        log.debug('Exposure summary failed: %s', exc)
        return {}


# ── Tasas actuales ────────────────────────────────────────────────────────────

def _get_current_rates() -> list:
    try:
        from rates.models import ExchangeRate, Currency
        from django.utils import timezone as tz

        bob        = Currency.objects.get(code='BOB')
        currencies = Currency.objects.filter(is_active=True).exclude(code='BOB')
        result     = []

        for cur in currencies:
            rate = (ExchangeRate.objects
                    .filter(currency_from=cur, currency_to=bob,
                            market_type='paralelo_fisico_empresa')
                    .order_by('-valid_from').first())
            if rate:
                result.append({
                    'currency': cur.code,
                    'buy':      _safe_float(rate.buy_rate),
                    'sell':     _safe_float(rate.sell_rate),
                    'official': _safe_float(rate.official_rate),
                    'updated':  rate.valid_from.isoformat(),
                })
        return result
    except Exception:
        return []


# ── AI Pricing ────────────────────────────────────────────────────────────────

def _get_ai_pricing_summary() -> list:
    try:
        from rates.models import ExchangeRateDecisionLog
        from django.db.models import Max

        # Última decisión por divisa
        latest_ids = (ExchangeRateDecisionLog.objects
                      .values('currency_code')
                      .annotate(latest=Max('created_at')))
        result = []
        for item in latest_ids:
            d = ExchangeRateDecisionLog.objects.filter(
                currency_code=item['currency_code'],
                created_at=item['latest']
            ).first()
            if d:
                result.append({
                    'currency':        d.currency_code,
                    'suggested_buy':   _safe_float(d.suggested_buy),
                    'suggested_sell':  _safe_float(d.suggested_sell),
                    'spread_pct':      _safe_float(d.suggested_spread_pct),
                    'recommendation':  d.recommendation,
                    'created_at':      d.created_at.isoformat(),
                })
        return result
    except Exception:
        return []


# ── Alertas activas ───────────────────────────────────────────────────────────

def _get_active_alerts() -> list:
    """Alertas de las últimas 24h desde el log de tareas."""
    try:
        from analytics.models import ExposureSnapshot
        from django.utils import timezone as tz

        cutoff  = tz.now() - timedelta(hours=24)
        alerts  = []

        critical = (ExposureSnapshot.objects
                    .filter(timestamp__gte=cutoff, alert_level='CRITICAL')
                    .values('currency_code', 'alert_level', 'exposure_bob', 'pct_of_capital')
                    .order_by('-timestamp')[:5])
        for a in critical:
            alerts.append({
                'type':      'EXPOSURE_CRITICAL',
                'severity':  'CRITICAL',
                'currency':  a['currency_code'],
                'message':   f'{a["currency_code"]}: exposición {_safe_float(a["pct_of_capital"]):.1f}% del capital',
                'value':     _safe_float(a['exposure_bob']),
            })
        return alerts
    except Exception:
        return []


# ── Inventario ────────────────────────────────────────────────────────────────

def _get_inventory_summary(branch_id=None, company_id=None) -> list:
    try:
        from inventory.models import CurrencyInventory
        qs = _scope_company(CurrencyInventory.objects.select_related('currency', 'branch'), company_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        result = []
        for inv in qs:
            stock = inv.physical_balance + inv.digital_balance
            stock_pct = float(stock / inv.maximum_stock * 100) if inv.maximum_stock > 0 else 0
            status = ('CRITICAL' if stock < inv.minimum_stock
                      else 'LOW' if stock_pct < 30
                      else 'HIGH' if stock_pct > 80
                      else 'OK')
            result.append({
                'currency':  inv.currency.code,
                'branch':    str(inv.branch) if inv.branch else None,
                'stock':     _safe_float(stock),
                'stock_pct': round(stock_pct, 1),
                'wac':       _safe_float(inv.weighted_average_cost),
                'status':    status,
            })
        return result
    except Exception as exc:
        log.debug('Inventory summary failed: %s', exc)
        return []
