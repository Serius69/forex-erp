from django.urls import path
from .ai_insights import AIInsightsView

urlpatterns = [
    path('insights/', AIInsightsView.as_view(), name='ai-insights'),
]
