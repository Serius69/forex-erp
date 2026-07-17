from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from django.db.models import Sum, Count, F
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta

CACHE_TTL = 180  # segundos — datos de dashboard levemente stale son aceptables

# Ventana del histórico de capital que se grafica (evita escanear toda la tabla).
CAPITAL_TIMELINE_DAYS = 90


class DashboardChartsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Clave por rol/sucursal (multi-tenant: branch_id es único global; ADMIN='all',
        # mismo alcance que las agregaciones de _base_qs). `?refresh=true` fuerza recálculo.
        force = request.query_params.get('refresh', '').lower() == 'true'
        if request.user.role == 'ADMIN':
            scope = 'all'
        else:
            scope = f'branch:{request.user.branch_id}'
        cache_key = f'dashboard_charts:{scope}'

        if not force:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

        today = timezone.now().date()
        days_30_ago = today - timedelta(days=30)
        month_start = today.replace(day=1)

        revenue_30d = self._revenue_30d(request, days_30_ago)
        volume_by_currency = self._volume_by_currency(request, month_start)
        self._enrich_with_profit(volume_by_currency, revenue_30d, month_start, days_30_ago)
        capital_timeline = self._capital_timeline()
        income_distribution = [
            {'name': item['currency'], 'value': item['volume']}
            for item in volume_by_currency
            if item.get('currency') and item['currency'] not in ('?', '')
        ]
        alerts = self._inventory_alerts()

        data = {
            'revenue_30d': revenue_30d,
            'volume_by_currency': volume_by_currency,
            'capital_timeline': capital_timeline,
            'income_distribution': income_distribution,
            'alerts': alerts,
        }
        cache.set(cache_key, data, CACHE_TTL)
        return Response(data)

    # ── private helpers ───────────────────────────────────────────────────────

    def _base_qs(self, request):
        from transactions.models import Transaction
        qs = Transaction.objects.filter(status='COMPLETED')
        if request.user.role != 'ADMIN':
            qs = qs.filter(branch=request.user.branch)
        return qs

    def _revenue_30d(self, request, days_30_ago):
        try:
            rows = (
                self._base_qs(request)
                .filter(created_at__date__gte=days_30_ago)
                .annotate(day=TruncDate('created_at'))
                .values('day')
                .annotate(revenue=Sum('amount_to'), transactions=Count('id'))
                .order_by('day')
            )
            return [
                {
                    'date': str(r['day']),
                    'revenue': int(r['revenue'] or 0),
                    'transactions': int(r['transactions'] or 0),
                }
                for r in rows
            ]
        except Exception:
            return []

    def _volume_by_currency(self, request, month_start):
        try:
            rows = (
                self._base_qs(request)
                .filter(created_at__date__gte=month_start)
                .values('currency_from__code')
                .annotate(volume=Sum('amount_to'), count=Count('id'))
                .order_by('-volume')
            )
            # Agrupar variantes de caja bajo su divisa base: USD_CASH_LOOSE y
            # USD_SMALL_BILLS son productos operativos de USD, no divisas — antes
            # aparecían como "divisas" separadas en los gráficos del dashboard.
            merged: dict[str, int] = {}
            for r in rows:
                code = (r['currency_from__code'] or '?').split('_')[0]
                merged[code] = merged.get(code, 0) + int(r['volume'] or 0)
            ordered = sorted(merged.items(), key=lambda kv: -kv[1])[:8]
            return [
                {'currency': code, 'volume': vol, 'profit': 0}
                for code, vol in ordered
            ]
        except Exception:
            return []

    def _enrich_with_profit(self, volume_by_currency, revenue_30d, month_start, days_30_ago):
        try:
            from analytics.models import TransactionProfitLedger

            # Profit per currency (month)
            cur_profit = (
                TransactionProfitLedger.objects
                .filter(fecha__gte=month_start)
                .values('currency_code')
                .annotate(profit=Sum('profit_bob'))
            )
            # Agregar profit por divisa BASE (las variantes de caja suman al padre)
            cur_map: dict = {}
            for r in cur_profit:
                base = (r['currency_code'] or '?').split('_')[0]
                cur_map[base] = cur_map.get(base, 0.0) + float(r['profit'] or 0)
            for item in volume_by_currency:
                item['profit'] = cur_map.get(item['currency'], 0)

            # Replace revenue_30d amounts with real profit
            day_profit = (
                TransactionProfitLedger.objects
                .filter(fecha__gte=days_30_ago)
                .values('fecha')
                .annotate(profit=Sum('profit_bob'))
            )
            day_map = {str(r['fecha']): float(r['profit'] or 0) for r in day_profit}
            for item in revenue_30d:
                if item['date'] in day_map:
                    item['revenue'] = day_map[item['date']]
        except Exception:
            pass

    def _capital_timeline(self):
        try:
            from capital.models import CapitalSnapshot
            # OJO: el campo es total_bob (Sum('total_capital') lanzaba FieldError
            # silencioso → el gráfico salía siempre "Sin datos"). Puede haber
            # varios snapshots por fecha → quedarse con el ÚLTIMO de cada día,
            # no sumarlos (doble conteo).
            # Acotado a los últimos N días para no escanear todo el histórico.
            cutoff = timezone.now().date() - timedelta(days=CAPITAL_TIMELINE_DAYS)
            rows = (
                CapitalSnapshot.objects
                .filter(fecha__gte=cutoff)
                .order_by('fecha', 'created_at')
                .values('fecha', 'total_bob')
            )
            by_date: dict = {}
            for r in rows:                       # el último de cada fecha gana
                by_date[str(r['fecha'])] = float(r['total_bob'] or 0)
            return [
                {'date': d, 'capital': v}
                for d, v in sorted(by_date.items())
            ]
        except Exception:
            return []

    def _inventory_alerts(self):
        alerts = []
        try:
            from inventory.models import CurrencyInventory
            low = (
                CurrencyInventory.objects
                .filter(physical_balance__lt=F('minimum_stock'))
                .select_related('currency')[:5]
            )
            for inv in low:
                alerts.append({
                    'id': f'inv-{inv.id}',
                    'message': f'Stock bajo: {inv.currency.code}',
                    'severity': 'warning',
                    'category': 'inventory',
                })
        except Exception:
            pass
        return alerts
