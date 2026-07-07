"""
Recepción y persistencia de errores del frontend.

Endpoint: POST /api/logs/frontend-error/
Modelo:   alerts.FrontendErrorLog
Límite:   100 req/min por IP.
"""
from __future__ import annotations
import json
import logging
import uuid

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

log = logging.getLogger('kapitalya.frontend_errors')

_SENSITIVE_TERMS = ('bearer ', 'token=', 'password', 'refresh', 'authorization')


def _is_rate_limited(ip: str) -> bool:
    try:
        from django.core.cache import cache
        key   = f'fe_err_rl:{ip}'
        count = int(cache.get(key) or 0)
        if count >= 100:
            return True
        cache.set(key, count + 1, timeout=60)
        return False
    except Exception:
        return False


def _get_client_ip(request) -> str:
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return (xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', ''))


def _sanitize_stack(stack: str) -> str:
    lower = stack.lower()
    for term in _SENSITIVE_TERMS:
        if term in lower:
            return '[stack sanitizado por seguridad]'
    return stack[:5000]


@csrf_exempt
@require_http_methods(['POST', 'OPTIONS'])
def receive_frontend_error(request):
    if request.method == 'OPTIONS':
        return JsonResponse({}, status=204)

    ip = _get_client_ip(request)
    if _is_rate_limited(ip):
        return JsonResponse({'error': 'rate_limit'}, status=429)

    try:
        body = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    try:
        from alerts.models import FrontendErrorLog
        entry = FrontendErrorLog.objects.create(
            error_id        = str(body.get('error_id', uuid.uuid4()))[:64],
            error_type      = str(body.get('error_type', 'UnknownError'))[:64],
            message         = str(body.get('message', ''))[:2000],
            stack           = _sanitize_stack(str(body.get('stack', ''))),
            component_stack = str(body.get('component_stack', ''))[:3000],
            url             = str(body.get('url', ''))[:500],
            user_agent      = str(body.get('user_agent', ''))[:300],
            user_id         = body.get('user_id'),
            company_id      = body.get('company_id'),
            extra           = body.get('extra') if isinstance(body.get('extra'), dict) else {},
            ip_address      = ip or None,
        )
        log.warning(
            "FRONTEND_ERROR id=%s type=%s msg=%s url=%s",
            entry.error_id, entry.error_type, entry.message[:100], entry.url,
        )
        return JsonResponse({'received': True, 'id': str(entry.id)}, status=201)
    except Exception as exc:
        log.error("FRONTEND_ERROR_SAVE_FAILED: %s", exc, exc_info=True)
        return JsonResponse({'received': False}, status=500)
