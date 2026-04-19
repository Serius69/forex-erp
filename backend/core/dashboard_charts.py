from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, F
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta


class DashboardChartsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
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

        return Response({
            'revenue_30d': revenue_30d,
            'volume_by_currency': volume_by_currency,
            'capital_timeline': capital_timeline,
            'income_distribution': income_distribution,
            'alerts': alerts,
        })

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
                .order_by('-volume')[:8]
            )
            return [
                {
                    'currency': r['currency_from__code'] or '?',
                    'volume': int(r['volume'] or 0),
                    'profit': 0,
                }
                for r in rows
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
            cur_map = {r['currency_code']: float(r['profit'] or 0) for r in cur_profit}
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
            rows = (
                CapitalSnapshot.objects
                .values('fecha')
                .annotate(capital=Sum('total_capital'))
                .order_by('fecha')
            )
            return [
                {'date': str(r['fecha']), 'capital': float(r['capital'] or 0)}
                for r in rows
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
