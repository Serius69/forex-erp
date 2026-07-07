"""
Manejo global de excepciones para Kapitalya ERP.

Garantiza:
  - Respuestas JSON consistentes para todos los códigos HTTP
  - Sin stack traces en producción (seguridad)
  - Request ID en todas las respuestas de error (trazabilidad)
  - Logging apropiado por tipo de error
  - Nunca exponer información sensible (DB, tokens, paths internos)
"""
import logging
import traceback
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler
from rest_framework.exceptions import (
    AuthenticationFailed, NotAuthenticated, PermissionDenied,
    ValidationError, NotFound, Throttled, MethodNotAllowed,
    ParseError, UnsupportedMediaType,
)

log = logging.getLogger('django.request')
log_security = logging.getLogger('kapitalya.security')


# ── Mapeo de excepciones a mensajes amigables ─────────────────────────────────

_FRIENDLY_MESSAGES = {
    401: 'Autenticación requerida. Inicia sesión nuevamente.',
    403: 'No tienes permisos para realizar esta acción.',
    404: 'Recurso no encontrado.',
    405: 'Método HTTP no permitido.',
    415: 'Tipo de contenido no soportado.',
    429: 'Demasiadas solicitudes. Intenta más tarde.',
    500: 'Error interno del servidor. El equipo técnico fue notificado.',
    503: 'Servicio temporalmente no disponible.',
}


def custom_exception_handler(exc, context):
    """
    Handler global de excepciones para Django REST Framework.

    Formato de respuesta estándar:
    {
      "error": "Mensaje amigable principal",
      "code":  "ERROR_CODE",
      "details": { ... }  // solo en debug o errores de validación
      "request_id": "uuid"
    }
    """
    # Obtener request_id para trazabilidad
    request = context.get('request')
    request_id = getattr(request, 'request_id', '-') if request else '-'
    view_name = _get_view_name(context)

    # DRF maneja: 400, 401, 403, 404, 405, 415, 429
    response = exception_handler(exc, context)

    if response is not None:
        return _normalize_drf_response(exc, response, request_id, view_name)

    # Excepción no manejada por DRF → 500
    return _handle_unhandled_exception(exc, context, request_id, view_name)


def _normalize_drf_response(exc, response, request_id: str, view_name: str) -> Response:
    """Normaliza respuestas DRF al formato estándar de Kapitalya."""
    http_code = response.status_code
    data = response.data

    # ── Errores de validación (400) ────────────────────────────────────────
    if http_code == 400:
        errors, first_msg = _flatten_validation_errors(data)
        response.data = {
            'error':      first_msg,
            'code':       'VALIDATION_ERROR',
            'details':    errors,
            'request_id': request_id,
        }
        log.warning(
            "VALIDATION_ERROR view=%s errors=%s rid=%s",
            view_name, errors, request_id,
        )
        return response

    # ── Autenticación (401) ────────────────────────────────────────────────
    if http_code == 401:
        log_security.warning(
            "AUTH_FAILED view=%s detail=%s rid=%s",
            view_name, _safe_detail(data), request_id,
        )
        response.data = {
            'error':      _FRIENDLY_MESSAGES[401],
            'code':       'AUTHENTICATION_REQUIRED',
            'request_id': request_id,
        }
        return response

    # ── Permisos (403) ────────────────────────────────────────────────────
    if http_code == 403:
        log_security.warning(
            "PERMISSION_DENIED view=%s detail=%s rid=%s",
            view_name, _safe_detail(data), request_id,
        )
        response.data = {
            'error':      _safe_detail(data) or _FRIENDLY_MESSAGES[403],
            'code':       'PERMISSION_DENIED',
            'request_id': request_id,
        }
        return response

    # ── Not Found (404) ───────────────────────────────────────────────────
    if http_code == 404:
        response.data = {
            'error':      _FRIENDLY_MESSAGES[404],
            'code':       'NOT_FOUND',
            'request_id': request_id,
        }
        return response

    # ── Rate Limit (429) ──────────────────────────────────────────────────
    if http_code == 429:
        wait = getattr(exc, 'wait', None)
        log_security.warning(
            "RATE_LIMIT_HIT view=%s wait=%s rid=%s",
            view_name, wait, request_id,
        )
        response.data = {
            'error':        _FRIENDLY_MESSAGES[429],
            'code':         'RATE_LIMIT_EXCEEDED',
            'retry_after':  int(wait) if wait else 60,
            'request_id':   request_id,
        }
        return response

    # ── Resto (405, 415, etc.) ────────────────────────────────────────────
    friendly = _FRIENDLY_MESSAGES.get(http_code, _safe_detail(data) or 'Error inesperado.')
    response.data = {
        'error':      friendly,
        'code':       f'HTTP_{http_code}',
        'request_id': request_id,
    }
    return response


def _handle_unhandled_exception(exc, context, request_id: str, view_name: str) -> Response:
    """Maneja excepciones no capturadas por DRF (500)."""
    tb = traceback.format_exc()

    log.error(
        "UNHANDLED_EXCEPTION view=%s type=%s msg=%s rid=%s\n%s",
        view_name, type(exc).__name__, str(exc)[:200], request_id, tb,
    )

    # En desarrollo mostrar el error; en producción mensaje genérico
    detail = str(exc)[:500] if settings.DEBUG else None

    data = {
        'error':      _FRIENDLY_MESSAGES[500],
        'code':       'INTERNAL_SERVER_ERROR',
        'request_id': request_id,
    }
    if detail:
        data['detail'] = detail

    return Response(data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Handlers para 404 y 500 de Django (fuera de DRF) ─────────────────────────

def handler_404(request, exception=None):
    """Handler 404 para vistas no-DRF."""
    from django.http import JsonResponse
    request_id = getattr(request, 'request_id', '-')
    return JsonResponse({
        'error':      'Ruta no encontrada.',
        'code':       'NOT_FOUND',
        'path':       request.path,
        'request_id': request_id,
    }, status=404)


def handler_500(request):
    """Handler 500 para vistas no-DRF."""
    from django.http import JsonResponse
    request_id = getattr(request, 'request_id', '-')
    log.error("DJANGO_500 path=%s rid=%s", request.path, request_id)
    return JsonResponse({
        'error':      _FRIENDLY_MESSAGES[500],
        'code':       'INTERNAL_SERVER_ERROR',
        'request_id': request_id,
    }, status=500)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flatten_validation_errors(data) -> tuple[dict, str]:
    """Aplana errores de validación anidados a un dict plano y extrae el primer mensaje."""
    if isinstance(data, dict):
        flat = {}
        first_msg = None
        for field, msgs in data.items():
            if isinstance(msgs, list):
                msg = str(msgs[0]) if msgs else ''
            elif isinstance(msgs, dict):
                msg = str(next(iter(msgs.values()), ''))
            else:
                msg = str(msgs)
            flat[field] = msg
            if first_msg is None and msg:
                first_msg = f"{field}: {msg}" if field != 'non_field_errors' else msg
        return flat, first_msg or 'Error de validación.'
    if isinstance(data, list):
        msg = str(data[0]) if data else 'Error de validación.'
        return {'error': msg}, msg
    msg = str(data)
    return {'error': msg}, msg


def _safe_detail(data) -> str:
    """Extrae el campo 'detail' de los datos de respuesta de forma segura."""
    if isinstance(data, dict):
        return str(data.get('detail', '') or data.get('error', ''))
    return str(data) if data else ''


def _get_view_name(context) -> str:
    """Extrae el nombre de la vista del contexto de forma segura."""
    view = context.get('view')
    if view is None:
        return 'unknown'
    return type(view).__name__
