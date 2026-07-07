"""
Middleware stack profesional de Kapitalya ERP.

Orden en settings.MIDDLEWARE (de afuera hacia adentro):
  1. RequestIDMiddleware       — asigna X-Request-ID único
  2. RequestLoggingMiddleware  — loguea request + response time
  3. IdempotencyMiddleware     — deduplica POSTs financieros
  4. SecurityHeadersMiddleware — headers de seguridad HTTP
  5. QueryCountMiddleware      — detecta N+1 queries
"""
import hashlib
import json
import logging
import time
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse

log_requests  = logging.getLogger('kapitalya.requests')
log_security  = logging.getLogger('kapitalya.security')
log_perf      = logging.getLogger('kapitalya.requests')
audit_log     = logging.getLogger('audit')

# Rutas que no se loguean en detalle (reduce ruido)
_SILENT_PATHS = {'/health/', '/api/health/', '/favicon.ico', '/static/'}


class RequestIDMiddleware:
    """
    Asigna un ID único a cada request HTTP.
    El ID se propaga en:
      - request.request_id  (disponible en vistas)
      - X-Request-ID header (devuelto al cliente)
      - thread local de logging
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Respetar X-Request-ID del cliente si viene (para tracing distribuido)
        request_id = request.META.get('HTTP_X_REQUEST_ID', '').strip()
        if not request_id or len(request_id) > 64:
            request_id = str(uuid.uuid4())
        request.request_id = request_id

        response = self.get_response(request)
        response['X-Request-ID'] = request_id
        return response


class RequestLoggingMiddleware:
    """
    Loguea cada request HTTP con:
      - método, path, status, tiempo de respuesta
      - usuario autenticado (si existe)
      - IP del cliente
      - X-Request-ID para trazabilidad
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip rutas silenciosas
        if any(request.path.startswith(p) for p in _SILENT_PATHS):
            return self.get_response(request)

        start = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = (time.monotonic() - start) * 1000

        user_info = '-'
        if hasattr(request, 'user') and request.user.is_authenticated:
            user_info = f"{request.user.username}(id={request.user.id})"

        x_forward = request.META.get('HTTP_X_FORWARDED_FOR', '')
        ip = x_forward.split(',')[0].strip() if x_forward else request.META.get('REMOTE_ADDR', '?')

        request_id = getattr(request, 'request_id', '-')
        slow_marker = ' [SLOW]' if elapsed_ms > getattr(settings, 'SLOW_REQUEST_THRESHOLD_MS', 2000) else ''

        msg = (
            f"{request.method} {request.path} "
            f"→ {response.status_code} "
            f"{elapsed_ms:.1f}ms "
            f"user={user_info} ip={ip} "
            f"rid={request_id}{slow_marker}"
        )

        level = logging.WARNING if elapsed_ms > getattr(settings, 'SLOW_REQUEST_THRESHOLD_MS', 2000) else logging.INFO
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400:
            level = logging.WARNING

        log_requests.log(level, msg)

        # Emitir métrica de respuesta para monitoreo
        _record_response_metric(request.path, request.method, response.status_code, elapsed_ms)

        return response


class QueryCountMiddleware:
    """
    Detecta N+1 queries y consultas excesivas por request.
    En DEBUG loguea todas las queries; en producción solo las que superan el umbral.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if any(request.path.startswith(p) for p in _SILENT_PATHS):
            return self.get_response(request)

        # Resetear contador de queries
        initial_queries = len(connection.queries) if settings.DEBUG else 0

        response = self.get_response(request)

        if not settings.DEBUG:
            return response

        total_queries = len(connection.queries) - initial_queries
        max_allowed = getattr(settings, 'MAX_QUERIES_PER_REQUEST', 30)
        slow_threshold = getattr(settings, 'SLOW_QUERY_THRESHOLD_MS', 200)

        if total_queries > max_allowed:
            log_perf.warning(
                "HIGH_QUERY_COUNT path=%s method=%s queries=%d max=%d — "
                "revisar select_related/prefetch_related",
                request.path, request.method, total_queries, max_allowed,
            )

        # Detectar queries lentas individualmente
        if settings.DEBUG:
            for q in connection.queries[-total_queries:]:
                try:
                    q_time_ms = float(q.get('time', '0')) * 1000
                    if q_time_ms > slow_threshold:
                        log_perf.warning(
                            "SLOW_QUERY %.1fms path=%s sql=%.200s",
                            q_time_ms, request.path, q.get('sql', '')[:200],
                        )
                except (ValueError, TypeError):
                    pass

        response['X-Query-Count'] = str(total_queries)
        return response


class IdempotencyMiddleware:
    """
    Previene transacciones duplicadas usando un Idempotency-Key en el header.
    TTL: 24 horas (ventana de seguridad para operaciones del día).
    """
    PROTECTED_PATHS = ['/api/transactions/']
    CACHE_TTL = 86400  # 24 horas

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == 'POST' and any(
            request.path.startswith(p) for p in self.PROTECTED_PATHS
        ):
            key_header = request.META.get('HTTP_IDEMPOTENCY_KEY', '').strip()
            if key_header:
                cache_key = f"idempotency:{hashlib.sha256(key_header.encode()).hexdigest()}"
                cached = cache.get(cache_key)
                if cached is not None:
                    log_security.warning(
                        "DUPLICATE_REQUEST idempotency_key=%s... path=%s rid=%s",
                        key_header[:8], request.path,
                        getattr(request, 'request_id', '-'),
                    )
                    return JsonResponse(cached, status=200)

                response = self.get_response(request)

                if response.status_code == 201:
                    try:
                        cache.set(cache_key, json.loads(response.content), self.CACHE_TTL)
                    except Exception:
                        pass
                return response

        return self.get_response(request)


class SecurityHeadersMiddleware:
    """
    Adds production-grade HTTP security headers to all responses.
    Includes Content-Security-Policy (CSP) to prevent XSS.
    """
    _CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://accounts.google.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://accounts.google.com; "
        "frame-src https://accounts.google.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not settings.DEBUG:
            response['X-Content-Type-Options']         = 'nosniff'
            response['X-Frame-Options']                = 'DENY'
            response['X-XSS-Protection']               = '1; mode=block'
            response['Referrer-Policy']                = 'strict-origin-when-cross-origin'
            response['Permissions-Policy']             = 'geolocation=(), microphone=(), camera=()'
            response['Content-Security-Policy']        = self._CSP
            response['Cache-Control']                  = 'no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma']                         = 'no-cache'
            response['Cross-Origin-Opener-Policy']     = 'same-origin'
            response['Cross-Origin-Embedder-Policy']   = 'require-corp'

        if '/api/auth/' in request.path:
            response['Cache-Control'] = 'no-store'
            response['Pragma']        = 'no-cache'

        return response


# ── Métricas simples en memoria ───────────────────────────────────────────────

_metrics: dict = {
    'requests_total':    0,
    'requests_5xx':      0,
    'requests_4xx':      0,
    'response_times_ms': [],  # últimas 1000 muestras
}


def _record_response_metric(path: str, method: str, status: int, elapsed_ms: float):
    """Almacena métricas en memoria para el endpoint /health/."""
    try:
        _metrics['requests_total'] += 1
        if status >= 500:
            _metrics['requests_5xx'] += 1
        elif status >= 400:
            _metrics['requests_4xx'] += 1

        times = _metrics['response_times_ms']
        times.append(elapsed_ms)
        if len(times) > 1000:
            _metrics['response_times_ms'] = times[-1000:]
    except Exception:
        pass  # nunca romper el request por métricas


class Request400LoggerMiddleware:
    """
    Loguea el payload y los errores de validación de todas las respuestas 400.
    Facilita el diagnóstico de formularios que fallan silenciosamente.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 400:
            try:
                body_raw = request.body[:2000].decode('utf-8', errors='replace')
            except Exception:
                body_raw = '<unreadable>'

            user_info = '-'
            if hasattr(request, 'user') and request.user.is_authenticated:
                user_info = f"{request.user.username}(id={request.user.id})"

            try:
                import json as _json
                resp_data = _json.loads(response.content)[:500] if response.content else {}
            except Exception:
                resp_data = response.content[:200].decode('utf-8', errors='replace')

            log_requests.warning(
                'HTTP_400 method=%s path=%s user=%s rid=%s payload=%s errors=%s',
                request.method,
                request.path,
                user_info,
                getattr(request, 'request_id', '-'),
                body_raw,
                resp_data,
            )
        return response


def get_metrics_snapshot() -> dict:
    """Devuelve snapshot de métricas actuales."""
    times = _metrics['response_times_ms']
    avg_ms = sum(times) / len(times) if times else 0
    p95_ms = sorted(times)[int(len(times) * 0.95)] if len(times) >= 20 else 0

    return {
        'requests_total': _metrics['requests_total'],
        'requests_4xx':   _metrics['requests_4xx'],
        'requests_5xx':   _metrics['requests_5xx'],
        'avg_response_ms': round(avg_ms, 1),
        'p95_response_ms': round(p95_ms, 1),
    }
