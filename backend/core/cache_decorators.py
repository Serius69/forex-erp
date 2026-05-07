"""
Decorador @cache_response para vistas DRF de solo lectura.

Uso:
    from core.cache_decorators import cache_response

    class MyView(APIView):
        @cache_response(ttl=60)
        def get(self, request):
            ...

    # Con key personalizada que incluye company_id (multi-tenant):
    @cache_response(ttl=30, key_prefix='capital_position')
    def get(self, request):
        ...

La key incluye automáticamente el company_id del request para
no mezclar datos entre tenants.

Invalidación: llama cache.delete(key) o usa el helper invalidate_cache_for().
"""
import hashlib
import logging
from functools import wraps

from django.core.cache import cache

log = logging.getLogger('kapitalya.cache')


def _build_cache_key(prefix: str, request, extra: str = '') -> str:
    """
    Construye una clave de caché única por:
      prefix + company_id + branch_id (si aplica) + query_string + extra
    """
    company_id = getattr(getattr(request, 'user', None), 'company_id', 'anon')
    branch_id  = getattr(getattr(request, 'user', None), 'branch_id',  'any')
    qs         = request.META.get('QUERY_STRING', '')
    raw        = f'{prefix}:{company_id}:{branch_id}:{qs}:{extra}'
    digest     = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f'api_cache:{prefix}:{digest}'


def cache_response(ttl: int = 60, key_prefix: str = '', vary_on_user: bool = False):
    """
    Decorador para cachear respuestas GET en Redis.

    Args:
        ttl:            Segundos que dura la entrada en caché.
        key_prefix:     Prefijo opcional para la clave; por defecto usa la ruta.
        vary_on_user:   Si True, la clave incluye el user_id (para respuestas
                        personalizadas por usuario, no solo por tenant).
    """
    def decorator(view_method):
        @wraps(view_method)
        def wrapper(self_or_request, request=None, *args, **kwargs):
            # Compatibilidad con métodos de clase (self, request) y funciones (request)
            if request is None:
                # Llamado como función de vista normal
                req = self_or_request
            else:
                req = request

            # Solo cachear GET
            if req.method != 'GET':
                if request is None:
                    return view_method(self_or_request, *args, **kwargs)
                return view_method(self_or_request, request, *args, **kwargs)

            prefix = key_prefix or view_method.__qualname__.replace('.', '_')
            extra  = str(req.user.pk) if vary_on_user and req.user.is_authenticated else ''
            key    = _build_cache_key(prefix, req, extra)

            cached = cache.get(key)
            if cached is not None:
                log.debug('CACHE_HIT key=%s', key)
                return cached

            if request is None:
                response = view_method(self_or_request, *args, **kwargs)
            else:
                response = view_method(self_or_request, request, *args, **kwargs)

            # Solo cachear respuestas exitosas
            try:
                if hasattr(response, 'status_code') and response.status_code == 200:
                    cache.set(key, response, ttl)
                    log.debug('CACHE_SET key=%s ttl=%ds', key, ttl)
            except Exception as exc:
                log.debug('CACHE_SET_SKIP key=%s err=%s', key, exc)

            return response

        return wrapper
    return decorator


def invalidate_cache_prefix(prefix: str) -> int:
    """
    Elimina todas las entradas de caché que comiencen con api_cache:{prefix}:.
    Usa el backend de Django (requiere Redis con soporte de scan/delete pattern).
    Retorna el número de claves eliminadas.
    """
    try:
        from django.core.cache import cache as _cache
        # Django Redis permite delete_pattern con wildcard
        pattern = f'api_cache:{prefix}:*'
        if hasattr(_cache, 'delete_pattern'):
            count = _cache.delete_pattern(pattern)
            log.debug('CACHE_INVALIDATE prefix=%s count=%d', prefix, count)
            return count
    except Exception as exc:
        log.debug('CACHE_INVALIDATE_ERR prefix=%s err=%s', prefix, exc)
    return 0
