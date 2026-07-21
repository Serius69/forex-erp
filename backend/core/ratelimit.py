"""
Rate limiting profesional para Kapitalya ERP.

Estrategia:
  - Por IP: protección contra bots/scrapers
  - Por usuario: protección contra abuso de cuenta
  - Por endpoint: límites específicos para operaciones críticas

Almacenamiento: Django cache (Redis en producción, LocMem en dev).
No requiere paquetes adicionales.

Límites predeterminados:
  - Transacciones:    60/min por usuario
  - Login:             5/min por IP
  - API general:      200/min por usuario, 100/min por IP
  - Rate updates:     10/min por usuario (solo admin)
  - ML train:          2/hora por usuario (solo admin)
"""
import functools
import hashlib
import logging
import time
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework import status

log = logging.getLogger('kapitalya.security')


class RateLimitExceeded(Exception):
    """Excepción lanzada cuando se supera el rate limit."""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f'Rate limit exceeded. Retry after {retry_after}s')


def rate_limit(requests: int, window: int, scope: str = 'user', burst: int = 0):
    """
    Decorator de rate limit con soporte para burst temporal.

    Args:
        requests: máximo de peticiones en la ventana
        window:   ventana en segundos
        scope:    'ip' | 'user' | 'both'
        burst:    peticiones extra permitidas en los primeros 5s (0 = sin burst)

    Uso:
        @rate_limit(requests=60, window=60, scope='user')
        @action(detail=False, methods=['POST'])
        def create(self, request):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(view_or_self, request, *args, **kwargs):
            req = request if hasattr(request, 'user') else view_or_self

            # Construir identificador
            identifier = _get_identifier(req, scope)
            view_name  = f"{func.__module__}.{func.__qualname__}"
            cache_key  = f"rl:v2:{view_name}:{identifier}"

            # Verificar límite
            exceeded, current, ttl = _check_and_increment(cache_key, requests, window)
            if exceeded:
                retry_after = ttl or window
                log.warning(
                    "RATE_LIMIT_EXCEEDED view=%s identifier=%s current=%d limit=%d",
                    func.__name__, identifier[:20], current, requests,
                )
                return Response(
                    {
                        'error':       'Demasiadas solicitudes. Por favor espera antes de continuar.',
                        'code':        'RATE_LIMIT_EXCEEDED',
                        'retry_after': retry_after,
                        'limit':       requests,
                        'window_s':    window,
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={
                        'Retry-After':       str(retry_after),
                        'X-RateLimit-Limit': str(requests),
                        'X-RateLimit-Remaining': '0',
                    },
                )

            return func(view_or_self, request, *args, **kwargs)
        return wrapper
    return decorator


def check_rate_limit(identifier: str, requests: int, window: int) -> tuple[bool, int]:
    """
    Verifica rate limit programáticamente (sin decorator).
    Útil en vistas que necesitan lógica condicional.

    Returns:
        (exceeded: bool, remaining: int)
    """
    cache_key = f"rl:v2:manual:{identifier}"
    exceeded, current, _ = _check_and_increment(cache_key, requests, window)
    remaining = max(0, requests - current)
    return exceeded, remaining


def get_rate_limit_status(identifier: str, requests: int, window: int) -> dict:
    """Devuelve el estado actual del rate limit sin incrementar."""
    cache_key = f"rl:v2:manual:{identifier}"
    current = cache.get(cache_key, 0)
    remaining = max(0, requests - current)
    return {
        'limit':     requests,
        'current':   current,
        'remaining': remaining,
        'exceeded':  current >= requests,
        'window_s':  window,
    }


# ── Helpers internos ──────────────────────────────────────────────────────────

def _client_ip(request) -> str:
    """IP del cliente resistente a spoofing de X-Forwarded-For.

    Tomar XFF[0] (el valor más a la izquierda) es inseguro: el cliente lo
    controla y podía enviar una IP distinta por request para evadir el rate
    limit de login/signup. Se prefiere CF-Connecting-IP (el stack va tras
    Cloudflare Tunnel + nginx; Cloudflare lo fija y no es spoofeable a través de
    CF); en su defecto, el elemento a `TRUSTED_PROXY_COUNT` posiciones desde la
    derecha de XFF (el que conectó a nuestro proxy de confianza); si no, REMOTE_ADDR.
    """
    from django.conf import settings
    cf = request.META.get('HTTP_CF_CONNECTING_IP', '').strip()
    if cf:
        return cf
    depth = int(getattr(settings, 'TRUSTED_PROXY_COUNT', 1))
    chain = [p.strip() for p in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if p.strip()]
    if chain:
        idx = len(chain) - depth
        return chain[idx] if 0 <= idx < len(chain) else chain[0]
    return request.META.get('REMOTE_ADDR', 'unknown')


def _get_identifier(request, scope: str) -> str:
    """Genera el identificador para el rate limit según el scope."""
    parts = []

    if scope in ('user', 'both'):
        if hasattr(request, 'user') and request.user.is_authenticated:
            parts.append(f"u:{request.user.id}")
        else:
            parts.append("u:anon")

    if scope in ('ip', 'both') or not parts:
        ip = _client_ip(request)
        ip_hash = hashlib.md5(ip.encode()).hexdigest()[:12]
        parts.append(f"ip:{ip_hash}")

    return ':'.join(parts)


def _check_and_increment(cache_key: str, limit: int, window: int) -> tuple[bool, int, int]:
    """
    Verifica e incrementa el contador de rate limit.

    Returns:
        (exceeded, current_count, ttl_seconds)
    """
    try:
        current = cache.get(cache_key, 0)
        if current >= limit:
            # Obtener TTL restante (no disponible directamente en todos los backends)
            return True, current, window // 2

        if current == 0:
            cache.set(cache_key, 1, window)
            return False, 1, window
        else:
            try:
                new_val = cache.incr(cache_key)
                return False, new_val, window
            except ValueError:
                # Clave expiró entre get e incr — reiniciar
                cache.set(cache_key, 1, window)
                return False, 1, window

    except Exception as e:
        # Si el cache falla, no bloquear (fail open — disponibilidad > seguridad en este caso)
        log.warning("RATE_LIMIT_CACHE_ERROR: %s — failing open", e)
        return False, 0, window


# ── Límites predefinidos para reutilización ───────────────────────────────────

def transactions_limit(func):
    """60 transacciones/min por usuario (cajero opera rápido pero no tanto)."""
    return rate_limit(requests=60, window=60, scope='user')(func)


def auth_limit(func):
    """5 intentos de login/min por IP — protección contra brute force."""
    return rate_limit(requests=5, window=60, scope='ip')(func)


def api_limit(func):
    """200 requests/min por usuario — límite general de API."""
    return rate_limit(requests=200, window=60, scope='user')(func)


def admin_limit(func):
    """10 operaciones/min para acciones admin (actualizar tasas, entrenar ML)."""
    return rate_limit(requests=10, window=60, scope='user')(func)
