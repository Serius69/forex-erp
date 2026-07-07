# core/throttling.py
"""
Rate limiting personalizado para Kapitalya ERP.

Clases:
    ForexAuthThrottle        — 10 req/min para login (brute-force protection)
    ForexBurstThrottle       — 60 req/min burst por usuario
    ForexSustainedThrottle   — 1000 req/hora por usuario
    ForexTransactionThrottle — 30 transacciones/min por cajero
    ForexAnalyticsThrottle   — 120 req/min para analytics (lectura intensiva)
    ForexRatesThrottle       — 60 req/min para actualización de tasas
    ForexAnonThrottle        — 20 req/min para endpoints públicos (health)

Configurar en settings:
    REST_FRAMEWORK = {
        'DEFAULT_THROTTLE_CLASSES': [
            'core.throttling.ForexBurstThrottle',
            'core.throttling.ForexSustainedThrottle',
        ],
        'DEFAULT_THROTTLE_RATES': {
            'burst': '60/min',
            'sustained': '1000/hour',
            'auth': '10/min',
            'transactions': '30/min',
            'analytics': '120/min',
            'rates': '60/min',
            'anon': '20/min',
        },
    }
"""
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle, SimpleRateThrottle


# ─────────────────────────────────────────────────────────────────────────────
# User-scoped throttles
# ─────────────────────────────────────────────────────────────────────────────

class ForexBurstThrottle(UserRateThrottle):
    """60 requests/minute — burst para operación normal de caja."""
    scope = 'burst'


class ForexSustainedThrottle(UserRateThrottle):
    """1000 requests/hour — límite sostenido de largo plazo."""
    scope = 'sustained'


class ForexAuthThrottle(AnonRateThrottle):
    """
    10 requests/minute para endpoint de login.
    Protege contra ataques de fuerza bruta.
    """
    scope = 'auth'

    def get_cache_key(self, request, view):
        # Limitar por IP en lugar de usuario (aún no autenticado)
        ident = self.get_ident(request)
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }


class ForexTransactionThrottle(UserRateThrottle):
    """
    30 transacciones/minute por cajero.
    Previene registro masivo accidental o automatizado.
    ADMIN y SUPERVISOR están exentos.
    """
    scope = 'transactions'

    def allow_request(self, request, view):
        role = getattr(getattr(request, 'user', None), 'role', None)
        if role in ('ADMIN', 'SUPERVISOR'):
            return True
        return super().allow_request(request, view)


class ForexAnalyticsThrottle(UserRateThrottle):
    """120 requests/minute para endpoints de analytics y dashboard."""
    scope = 'analytics'


class ForexRatesThrottle(UserRateThrottle):
    """
    60 requests/minute para actualización manual de tasas.
    Actualizaciones automáticas (Celery) no pasan por esta capa.
    """
    scope = 'rates'


# ─────────────────────────────────────────────────────────────────────────────
# Anonymous throttle (health endpoints, docs)
# ─────────────────────────────────────────────────────────────────────────────

class ForexAnonThrottle(AnonRateThrottle):
    """20 requests/minute para endpoints públicos."""
    scope = 'anon'


# ─────────────────────────────────────────────────────────────────────────────
# Admin bypass — sin límite para superusers
# ─────────────────────────────────────────────────────────────────────────────

class NoThrottle(SimpleRateThrottle):
    """Desactiva throttling (para vistas que lo necesiten explícitamente)."""
    scope = 'none'

    def allow_request(self, request, view):
        return True

    def get_cache_key(self, request, view):
        return None
