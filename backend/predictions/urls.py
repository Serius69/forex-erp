# predictions/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PredictionModelViewSet, PredictionViewSet, PredictionsDashboardView, ForecastView, ModelHealthView

router = DefaultRouter()
router.register(r'models',      PredictionModelViewSet, basename='prediction-models')
router.register(r'predictions', PredictionViewSet,      basename='predictions')

urlpatterns = [
    path('dashboard/',            PredictionsDashboardView.as_view(), name='predictions-dashboard'),
    # Nuevo endpoint mejorado
    path('forecast/<str:currency_pair>/', ForecastView.as_view(), name='forecast'),
    path('health/',               ModelHealthView.as_view(),         name='model-health'),
    path('', include(router.urls)),
]