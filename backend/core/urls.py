# core/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from users.views import ForexTokenView           # ← tu view customizada
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/login/',   ForexTokenView.as_view(),   name='token_obtain_pair'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/',         include('users.urls')),
    path('api/rates/',        include('rates.urls')),
    path('api/transactions/', include('transactions.urls')),
    path('api/inventory/',    include('inventory.urls')),
    path('api/predictions/',  include('predictions.urls')),
    path('api/reports/',      include('reports.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)