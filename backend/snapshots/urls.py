# snapshots/urls.py
from rest_framework.routers import DefaultRouter
from .views import SystemSnapshotViewSet

router = DefaultRouter()
router.register(r'', SystemSnapshotViewSet, basename='snapshots')

urlpatterns = router.urls
