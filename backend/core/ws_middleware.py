"""
JWT authentication middleware for Django Channels WebSockets.

Usage in asgi.py:
    from core.ws_middleware import JWTAuthMiddlewareStack
    'websocket': JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns))

Clients connect with: ws://host/ws/rates/?token=<access_token>
The middleware populates scope['user'] before the consumer is called,
so both RateConsumer and AlertConsumer can use self.scope['user'] directly.
"""
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user_from_token(token: str):
    """Return User instance or AnonymousUser. Never raises."""
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from rest_framework_simplejwt.exceptions import TokenError
        from users.models import User

        payload = AccessToken(token)
        return User.objects.select_related('branch').get(id=payload['user_id'])
    except Exception:
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    Intercepts WebSocket handshakes and injects scope['user'] from a
    JWT token passed as ?token= query parameter.

    Falls back to Django session auth (AuthMiddlewareStack) when no token
    is provided so existing session-based flows keep working.
    """

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            qs = parse_qs(scope.get('query_string', b'').decode())
            token = (qs.get('token') or [''])[0].strip()
            if token:
                scope['user'] = await _get_user_from_token(token)
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    """
    Drop-in replacement for AuthMiddlewareStack that adds JWT support.
    Wraps with JWTAuthMiddleware first, then falls through to session auth.
    """
    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
