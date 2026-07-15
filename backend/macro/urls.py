from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MacroIndicatorViewSet, NewsViewSet

router = DefaultRouter()
router.register(r'indicators', MacroIndicatorViewSet, basename='macro-indicators')
router.register(r'news', NewsViewSet, basename='macro-news')

urlpatterns = [
    path('', include(router.urls)),
]
