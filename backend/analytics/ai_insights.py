"""
AI Business Intelligence — /api/ai/insights/

Returns:
  alerts        — critical issues requiring immediate attention
  recommendations — actionable suggestions
  anomalies     — statistical outliers in rates or capital
  predictions   — short-term trend summary

All results are scoped to request.user.company.
"""
from __future__ import annotations
from django.utils import timezone
from datetime import timedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from tenants.permissions import IsCompanyMember


class AIInsightsView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get(self, request):
        user    = request.user
        company = user.company
        role    = user.role

        alerts          = []
        recommendations = []
        anomalies       = []
        predictions     = []

        # ── 1. Low-inventory alerts ───────────────────────────────────────────
        try:
            from inventory.models import CurrencyInventory
            qs = CurrencyInventory.objects.filter(
                branch__company=company,
            ).select_related('currency', 'branch')
            if role == 'CASHIER' and user.branch_id:
                qs = qs.filter(branch_id=user.branch_id)

            for inv in qs:
                if inv.needs_replenishment:
                    alerts.append({
                        'type':     'LOW_INVENTORY',
                        'severity': 'HIGH',
                        'title':    f'Inventario bajo: {inv.currency.code}',
                        'message':  (
                            f'{inv.currency.code} en {inv.branch.name}: '
                            f'{float(inv.total_balance):.2f} < mínimo {float(inv.reorder_point):.2f}'
                        ),
                        'branch':   inv.branch.name,
                        'currency': inv.currency.code,
                    })
        except Exception:
            pass

        # ── 2. Rate deviation anomalies ───────────────────────────────────────
        try:
            from rates.models import ExchangeRate
            from django.db.models import Avg, StdDev, Count
            cutoff = timezone.now() - timedelta(hours=24)
            rate_stats = (
                ExchangeRate.objects
                .filter(fetched_at__gte=cutoff, is_primary=True)
                .values('currency_from__code', 'currency_to__code')
                .annotate(
                    avg=Avg('sell_rate'),
                    stddev=StdDev('sell_rate'),
                    n=Count('id'),
                )
            )
            for stat in rate_stats:
                if stat['n'] < 3 or not stat['stddev']:
                    continue
                latest = (
                    ExchangeRate.objects
                    .filter(
                        currency_from__code=stat['currency_from__code'],
                        currency_to__code=stat['currency_to__code'],
                        is_primary=True,
                    )
                    .order_by('-fetched_at')
                    .first()
                )
                if not latest:
                    continue
                deviation = abs(float(latest.sell_rate) - float(stat['avg']))
                threshold = 2 * float(stat['stddev'])
                if deviation > threshold:
                    pair = f"{stat['currency_from__code']}/{stat['currency_to__code']}"
                    anomalies.append({
                        'type':      'RATE_DEVIATION',
                        'severity':  'MEDIUM',
                        'title':     f'Tasa atípica: {pair}',
                        'message':   (
                            f'Tasa de venta {float(latest.sell_rate):.4f} se desvía '
                            f'{deviation:.4f} del promedio {float(stat["avg"]):.4f} '
                            f'(±{threshold:.4f})'
                        ),
                        'pair':      pair,
                        'current':   float(latest.sell_rate),
                        'avg_24h':   float(stat['avg']),
                        'deviation': round(deviation / float(stat['avg']) * 100, 2),
                    })
        except Exception:
            pass

        # ── 3. Capital anomalies from existing log ────────────────────────────
        try:
            from analytics.models import CapitalAnomalyLog
            recent_anomalies = (
                CapitalAnomalyLog.objects
                .filter(
                    branch__company=company,
                    resolved=False,
                    severity__in=('CRITICAL', 'WARNING'),
                )
                .select_related('branch')
                .order_by('-id')[:10]
            )
            if role == 'CASHIER' and user.branch_id:
                recent_anomalies = recent_anomalies.filter(branch_id=user.branch_id)

            for a in recent_anomalies:
                anomalies.append({
                    'type':     a.rule,
                    'severity': a.severity,
                    'title':    a.rule.replace('_', ' ').title(),
                    'message':  a.description,
                    'branch':   a.branch.name if a.branch else None,
                    'value':    a.value,
                })
        except Exception:
            pass

        # ── 4. Transaction volume trend ───────────────────────────────────────
        try:
            from transactions.models import Transaction
            from django.db.models import Count
            today = timezone.now().date()
            daily = []
            for i in range(6, -1, -1):
                d   = today - timedelta(days=i)
                cnt = Transaction.objects.filter(
                    branch__company=company,
                    created_at__date=d,
                    status='COMPLETED',
                ).count()
                daily.append({'date': str(d), 'count': cnt})

            if len(daily) >= 2:
                last = daily[-1]['count']
                prev = daily[-2]['count']
                trend = 'UP' if last > prev else ('DOWN' if last < prev else 'FLAT')
                predictions.append({
                    'type':    'TRANSACTION_TREND',
                    'title':   'Tendencia de Transacciones',
                    'trend':   trend,
                    'daily':   daily,
                    'message': (
                        f"Hoy: {last} transacciones. "
                        f"Ayer: {prev}. "
                        f"Tendencia: {trend}."
                    ),
                })
        except Exception:
            pass

        # ── 5. High-value transaction warnings ────────────────────────────────
        try:
            from transactions.models import Transaction
            from django.conf import settings as djconf
            threshold = getattr(djconf, 'LARGE_TX_THRESHOLD_BOB', 100_000)
            cutoff    = timezone.now() - timedelta(hours=4)
            large_txs = Transaction.objects.filter(
                branch__company=company,
                created_at__gte=cutoff,
                amount_to__gte=threshold,
                status='COMPLETED',
            ).count()
            if large_txs > 0:
                alerts.append({
                    'type':     'LARGE_TRANSACTIONS',
                    'severity': 'MEDIUM',
                    'title':    'Transacciones de alto monto',
                    'message':  (
                        f'{large_txs} transacción(es) ≥ '
                        f'BOB {threshold:,} en las últimas 4 horas.'
                    ),
                    'count': large_txs,
                })
        except Exception:
            pass

        # ── 6. Profitability recommendation ───────────────────────────────────
        try:
            from analytics.models import PnLDailySnapshot
            from django.db.models import Sum
            today  = timezone.now().date()
            week   = today - timedelta(days=7)
            pnl_qs = PnLDailySnapshot.objects.filter(
                branch__company=company,
                fecha__gte=week,
            )
            agg = pnl_qs.aggregate(
                total_profit=Sum('ganancia_neta_bob'),
                total_revenue=Sum('ingreso_ventas_bob'),
            )
            total_p = float(agg['total_profit'] or 0)
            total_r = float(agg['total_revenue'] or 0)
            if total_r > 0:
                margin = total_p / total_r * 100
                if margin < 1.0:
                    recommendations.append({
                        'type':    'LOW_MARGIN',
                        'title':   'Margen bajo esta semana',
                        'message': (
                            f'Margen neto últimos 7 días: {margin:.2f}%. '
                            'Revisar spreads de venta y costos operativos.'
                        ),
                        'margin_pct': round(margin, 2),
                    })
                elif margin > 5.0:
                    recommendations.append({
                        'type':    'STRONG_MARGIN',
                        'title':   'Buen rendimiento',
                        'message': (
                            f'Margen neto de {margin:.2f}% esta semana. '
                            'Sistema operando eficientemente.'
                        ),
                        'margin_pct': round(margin, 2),
                    })
        except Exception:
            pass

        return Response({
            'company':         company.name if company else None,
            'generated_at':    timezone.now().isoformat(),
            'alerts':          alerts,
            'recommendations': recommendations,
            'anomalies':       anomalies,
            'predictions':     predictions,
            'summary': {
                'alert_count':          len(alerts),
                'anomaly_count':        len(anomalies),
                'recommendation_count': len(recommendations),
            },
        })
