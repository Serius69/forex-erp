from django.urls import path
from .views import (
    analytics_pnl, analytics_exposure, analytics_spread,
    analytics_history, analytics_decision, analytics_evaluar,
    analytics_decision_history, analytics_snapshot,
    analytics_overview, analytics_trends, analytics_anomalies,
)
from .branch_stats import branch_stats

urlpatterns = [
    # ── Aggregated / dashboard endpoints ─────────────────────────────────────
    path('overview/',             analytics_overview,           name='analytics-overview'),
    path('trends/',               analytics_trends,             name='analytics-trends'),
    path('anomalies/',            analytics_anomalies,          name='analytics-anomalies'),

    # ── Detailed analytics ────────────────────────────────────────────────────
    path('pnl/',                  analytics_pnl,               name='analytics-pnl'),
    path('exposure/',             analytics_exposure,           name='analytics-exposure'),
    path('spread/',               analytics_spread,             name='analytics-spread'),
    path('history/',              analytics_history,            name='analytics-history'),

    # ── Decision engine — specific paths before generic ───────────────────────
    path('decision/history/',     analytics_decision_history,   name='analytics-decision-history'),
    path('decision/',             analytics_decision,           name='analytics-decision'),
    path('evaluar/',              analytics_evaluar,            name='analytics-evaluar'),

    # ── Manual snapshots ──────────────────────────────────────────────────────
    path('snapshot/',             analytics_snapshot,           name='analytics-snapshot'),

    # ── Multi-branch comparative stats ───────────────────────────────────────
    path('branch-stats/',         branch_stats,                 name='analytics-branch-stats'),
]
