from rest_framework.routers import DefaultRouter
from .views import AlertLogViewSet

router = DefaultRouter()
router.register(r'', AlertLogViewSet, basename='alerts')

urlpatterns = router.urls
