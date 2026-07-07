# data_migration/urls.py
from rest_framework.routers import DefaultRouter
from .views import MigrationViewSet

router = DefaultRouter()
router.register(r'', MigrationViewSet, basename='migration')

urlpatterns = router.urls
