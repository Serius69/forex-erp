"""
Branch-level comparative statistics API.

GET /api/analytics/branch-stats/?period=today|week|month[&branch=<id>]

Returns array of per-branch stats scoped to request.user.company.
"""
from django.utils import timezone
from datetime import timedelta, date
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count, Q

from tenants.permissions import IsCompanyMember


def _date_range(period: str):
    today = timezone.now().date()
    if period == 'today':
        return today, today
    if period == 'week':
        return today - timedelta(days=7), today
    # month
    return today.replace(day=1), today


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsCompanyMember])
def branch_stats(request):
    user    = request.user
    company = user.company
    period  = request.query_params.get('period', 'today')
    branch_filter = request.query_params.get('branch')

    start, end = _date_range(period)

    from users.models import Branch, User as UserModel
    from transactions.models import Transaction
    from analytics.models import PnLDailySnapshot

    # Build base branch queryset
    branch_qs = Branch.objects.filter(company=company, is_active=True)
    if branch_filter:
        branch_qs = branch_qs.filter(id=branch_filter)
    if user.role == 'CASHIER' and user.branch_id:
        branch_qs = branch_qs.filter(id=user.branch_id)

    results = []
    for branch in branch_qs:
        tx_qs = Transaction.objects.filter(
            branch=branch,
            created_at__date__gte=start,
            created_at__date__lte=end,
            status='COMPLETED',
        )
        tx_agg = tx_qs.aggregate(
            cnt=Count('id'),
            vol=Sum('amount_to'),
        )

        pnl_agg = PnLDailySnapshot.objects.filter(
            branch=branch,
            fecha__gte=start,
            fecha__lte=end,
        ).aggregate(
            profit=Sum('ganancia_neta_bob'),
            revenue=Sum('ingreso_ventas_bob'),
        )

        profit  = float(pnl_agg['profit']  or 0)
        revenue = float(pnl_agg['revenue'] or 0)
        margin  = (profit / revenue * 100) if revenue > 0 else 0.0

        cashier_cnt = UserModel.objects.filter(
            company=company,
            branch=branch,
            role='CASHIER',
            is_active=True,
        ).count()

        results.append({
            'branch_id':     branch.id,
            'branch_name':   branch.name,
            'branch_code':   branch.code,
            'city':          branch.city,
            'is_main':       branch.is_main,
            'tx_count':      tx_agg['cnt'] or 0,
            'tx_volume_bob': float(tx_agg['vol'] or 0),
            'profit_bob':    profit,
            'revenue_bob':   revenue,
            'margin_pct':    round(margin, 2),
            'cashier_count': cashier_cnt,
        })

    # Sort by tx_count desc
    results.sort(key=lambda x: x['tx_count'], reverse=True)

    return Response(results)
