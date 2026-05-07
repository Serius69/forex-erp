from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/rates/$',      consumers.RateConsumer.as_asgi()),
    re_path(r'ws/rates-live/$', consumers.RatesConsumer.as_asgi()),
    re_path(r'ws/alerts/$',     consumers.AlertConsumer.as_asgi()),
]