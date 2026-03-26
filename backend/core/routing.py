from django.urls import re_path
from rates.consumers import RateConsumer

websocket_urlpatterns = [
    re_path(r'^ws/rates/$', RateConsumer.as_asgi()),
]