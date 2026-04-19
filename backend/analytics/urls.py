from django.urls import path
from .views import (
    analytics_pnl, analytics_exposure, analytics_spread,
    analytics_history, analytics_decision, analytics_evaluar,
    analytics_decision_history, analytics_snapshot,
)

urlpatterns = [
    path('pnl/',                  analytics_pnl,               name='analytics-pnl'),
    path('exposure/',             analytics_exposure,           name='analytics-exposure'),
    path('spread/',               analytics_spread,             name='analytics-spread'),
    path('history/',              analytics_history,            name='analytics-history'),
    # Decision endpoints — order matters: specific paths before generic
    path('decision/history/',     analytics_decision_history,   name='analytics-decision-history'),
    path('decision/',             analytics_decision,           name='analytics-decision'),
    path('evaluar/',              analytics_evaluar,            name='analytics-evaluar'),
    path('snapshot/',             analytics_snapshot,           name='analytics-snapshot'),
]
