# predictions/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PredictionModelViewSet, PredictionViewSet

router = DefaultRouter()
router.register(r'models',      PredictionModelViewSet, basename='prediction-models')
router.register(r'predictions', PredictionViewSet,      basename='predictions')

urlpatterns = [
    path('', include(router.urls)),
]