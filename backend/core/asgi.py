import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from core.routing import websocket_urlpatterns  # noqa
from core.ws_middleware import JWTAuthMiddlewareStack  # noqa

application = ProtocolTypeRouter({
    'http':      get_asgi_application(),
    'websocket': JWTAuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})