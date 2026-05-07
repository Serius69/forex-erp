"""
Health check y métricas para Kapitalya ERP.

Endpoints:
  GET /health/         — liveness probe: sistema responde
  GET /health/ready/   — readiness probe: sistema listo para tráfico
  GET /health/metrics/ — métricas básicas de rendimiento (autenticado)

Formato estándar compatible con:
  - Docker HEALTHCHECK
  - Kubernetes liveness/readiness probes
  - Uptime Kuma, Grafana
"""
import logging
import time
import platform
import os
from datetime import datetime, timezone

from django.conf import settings
from django.db import connection, DatabaseError
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response

from core.middleware import get_metrics_snapshot

log = logging.getLogger('kapitalya.health')

# Timestamp de inicio del proceso
_START_TIME = time.time()


# ── /api/health/ — estado general con circuit breakers ───────────────────────

@require_http_methods(['GET'])
def api_health(request):
    """
    Endpoint de health accesible desde el frontend.
    Retorna estado de: DB, Redis, Celery, WebSocket, fetchers (CB status).
    Nginx puede usar esto como healthcheck.
    """
    checks = {}
    overall_ok = True

    db_ok, db_msg = _check_database()
    checks['database'] = {'ok': db_ok, 'message': db_msg}
    if not db_ok:
        overall_ok = False

    cache_ok, cache_msg = _check_cache()
    checks['redis'] = {'ok': cache_ok, 'message': cache_msg}
    if not cache_ok:
        overall_ok = False

    celery_ok, celery_msg = _check_celery()
    checks['celery'] = {'ok': celery_ok, 'message': celery_msg}

    # Circuit breaker status de fetchers
    try:
        from rates.fetchers.base import cb_get_all_states
        cb_states = cb_get_all_states()
        open_count = sum(1 for s in cb_states.values() if s == 'OPEN')
        checks['fetchers'] = {
            'ok':         open_count == 0,
            'message':    f'{len(cb_states)} fetchers, {open_count} OPEN',
            'states':     cb_states,
        }
    except Exception as e:
        checks['fetchers'] = {'ok': True, 'message': f'check skipped: {e}'}

    http_status = 200 if overall_ok else 503
    return JsonResponse({
        'status':    'ok' if overall_ok else 'degraded',
        'checks':    checks,
        'uptime_s':  int(time.time() - _START_TIME),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'version':   getattr(settings, 'KAPITALYA_VERSION', '1.0.0'),
    }, status=http_status)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def api_health_detailed(request):
    """
    Health check detallado — solo ADMIN.
    Incluye: latencia DB, colas RabbitMQ, memoria Redis,
    último éxito de cada fetcher, métricas Celery.
    """
    result = {}

    # DB latency
    try:
        start = time.monotonic()
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        result['db_latency_ms'] = round((time.monotonic() - start) * 1000, 2)
    except Exception as e:
        result['db_latency_ms'] = None
        result['db_error'] = str(e)

    # Redis memory
    try:
        from django.conf import settings as s
        import redis as redis_lib
        redis_url = s.CACHES.get('default', {}).get('LOCATION', '')
        if redis_url:
            r = redis_lib.from_url(redis_url, decode_responses=True)
            info = r.info('memory')
            result['redis_used_memory_mb'] = round(info.get('used_memory', 0) / 1024 / 1024, 2)
            result['redis_peak_memory_mb'] = round(info.get('used_memory_peak', 0) / 1024 / 1024, 2)
    except Exception as e:
        result['redis_error'] = str(e)

    # Circuit breaker states
    try:
        from rates.fetchers.base import cb_get_all_states
        result['circuit_breakers'] = cb_get_all_states()
    except Exception as e:
        result['circuit_breakers'] = {'error': str(e)}

    # Celery stats
    result['celery'] = _get_celery_stats()

    # DB stats
    result['database'] = _get_db_stats()

    # Transactions today
    result['transactions_today'] = _get_today_tx_stats()

    result['timestamp'] = datetime.now(timezone.utc).isoformat()
    result['uptime_s']  = int(time.time() - _START_TIME)

    return Response(result)


@require_http_methods(['GET'])
def health_check(request):
    """
    Liveness probe: confirma que el proceso está vivo.
    Siempre devuelve 200 si el proceso corre.
    No verifica dependencias externas — eso es readiness.
    """
    uptime_s = int(time.time() - _START_TIME)
    return JsonResponse({
        'status':    'ok',
        'service':   'kapitalya-erp',
        'version':   getattr(settings, 'KAPITALYA_VERSION', '1.0.0'),
        'env':       getattr(settings, 'KAPITALYA_ENV', 'unknown'),
        'uptime_s':  uptime_s,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }, status=200)


@require_http_methods(['GET'])
def readiness_check(request):
    """
    Readiness probe: verifica que todas las dependencias están operativas.
    Devuelve 200 si listo, 503 si alguna dependencia falla.
    """
    checks = {}
    overall_ok = True

    # ── 1. Base de datos ──────────────────────────────────────────────────────
    db_ok, db_msg = _check_database()
    checks['database'] = {'ok': db_ok, 'message': db_msg}
    if not db_ok:
        overall_ok = False

    # ── 2. Cache / Redis ──────────────────────────────────────────────────────
    cache_ok, cache_msg = _check_cache()
    checks['cache'] = {'ok': cache_ok, 'message': cache_msg}
    if not cache_ok:
        overall_ok = False

    # ── 3. Celery ─────────────────────────────────────────────────────────────
    celery_ok, celery_msg = _check_celery()
    checks['celery'] = {'ok': celery_ok, 'message': celery_msg}
    # Celery degradado no impide el servicio (solo tareas programadas)

    # ── 4. ML Models ──────────────────────────────────────────────────────────
    ml_ok, ml_msg = _check_ml_models()
    checks['ml_models'] = {'ok': ml_ok, 'message': ml_msg}
    # ML degradado no impide el servicio

    # ── 5. Disco ──────────────────────────────────────────────────────────────
    disk_ok, disk_msg = _check_disk()
    checks['disk'] = {'ok': disk_ok, 'message': disk_msg}
    if not disk_ok:
        overall_ok = False

    http_status = 200 if overall_ok else 503

    if not overall_ok:
        failed = [k for k, v in checks.items() if not v['ok']]
        log.error(
            "READINESS_CHECK_FAILED failed_components=%s",
            failed,
        )

    return JsonResponse({
        'status':     'ok' if overall_ok else 'degraded',
        'ready':      overall_ok,
        'checks':     checks,
        'timestamp':  datetime.now(timezone.utc).isoformat(),
        'uptime_s':   int(time.time() - _START_TIME),
    }, status=http_status)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def metrics_view(request):
    """
    Métricas básicas del sistema (requiere autenticación).
    Solo administradores ven métricas completas.
    """
    if request.user.role not in ('ADMIN', 'SUPERVISOR'):
        return Response({'error': 'Solo administradores pueden ver métricas.'}, status=403)

    perf = get_metrics_snapshot()

    # Estadísticas de base de datos
    db_stats = _get_db_stats()

    # Estadísticas de Celery
    celery_stats = _get_celery_stats()

    # Estadísticas de transacciones del día
    tx_stats = _get_today_tx_stats()

    # Alertas del sistema
    try:
        from core.alerts import get_alerts_summary
        alerts_summary = get_alerts_summary()
    except Exception:
        alerts_summary = {}

    return Response({
        'service': {
            'name':    'kapitalya-erp',
            'version': getattr(settings, 'KAPITALYA_VERSION', '1.0.0'),
            'env':     getattr(settings, 'KAPITALYA_ENV', 'unknown'),
            'uptime_s': int(time.time() - _START_TIME),
            'debug':   settings.DEBUG,
            'python':  platform.python_version(),
        },
        'performance':        perf,
        'database':           db_stats,
        'celery':             celery_stats,
        'transactions_today': tx_stats,
        'alerts':             alerts_summary,
        'timestamp':          datetime.now(timezone.utc).isoformat(),
    })


# ── Checks individuales ───────────────────────────────────────────────────────

def _check_database() -> tuple[bool, str]:
    """Verifica conectividad con PostgreSQL."""
    try:
        start = time.monotonic()
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        elapsed_ms = (time.monotonic() - start) * 1000
        return True, f'ok ({elapsed_ms:.1f}ms)'
    except DatabaseError as e:
        log.critical("DB_HEALTH_CHECK_FAILED: %s", e)
        return False, f'database error: {type(e).__name__}'
    except Exception as e:
        log.critical("DB_HEALTH_CHECK_EXCEPTION: %s", e)
        return False, f'connection failed: {type(e).__name__}'


def _check_cache() -> tuple[bool, str]:
    """Verifica que el cache (Redis en producción) funciona."""
    try:
        test_key = '_kapitalya_health_check_'
        test_val = str(time.time())
        cache.set(test_key, test_val, timeout=10)
        retrieved = cache.get(test_key)
        if retrieved != test_val:
            return False, 'cache read/write mismatch'
        cache.delete(test_key)
        return True, 'ok'
    except Exception as e:
        log.error("CACHE_HEALTH_CHECK_FAILED: %s", e)
        return False, f'cache error: {type(e).__name__}'


def _check_celery() -> tuple[bool, str]:
    """Verifica que Celery workers están activos via ping."""
    try:
        from celery.app.control import Control
        from core.celery import app as celery_app

        ctrl = Control(app=celery_app)
        # Timeout corto para no bloquear el health check
        result = ctrl.ping(timeout=1.5)
        if result:
            worker_count = len(result)
            return True, f'{worker_count} worker(s) activo(s)'
        return False, 'sin workers respondiendo'
    except Exception as e:
        log.warning("CELERY_HEALTH_CHECK_FAILED: %s", e)
        return False, f'celery no disponible: {type(e).__name__}'


def _check_ml_models() -> tuple[bool, str]:
    """Verifica que hay modelos ML entrenados disponibles."""
    try:
        from predictions.models import PredictionModel
        active_count = PredictionModel.objects.filter(is_active=True).count()
        if active_count == 0:
            return False, 'sin modelos ML activos — ejecutar train-all'
        return True, f'{active_count} modelo(s) activo(s)'
    except Exception as e:
        log.warning("ML_HEALTH_CHECK_FAILED: %s", e)
        return False, f'ml check error: {type(e).__name__}'


def _check_disk() -> tuple[bool, str]:
    """Verifica espacio disponible en disco (directorio de logs y media)."""
    try:
        import shutil
        base = str(settings.BASE_DIR)
        total, used, free = shutil.disk_usage(base)
        free_pct = (free / total) * 100
        free_gb = free / (1024 ** 3)

        if free_pct < 5:
            log.critical("DISK_CRITICALLY_LOW free=%.1f%% (%.1fGB)", free_pct, free_gb)
            return False, f'disco crítico: {free_pct:.1f}% libre ({free_gb:.1f}GB)'
        if free_pct < 15:
            log.warning("DISK_LOW free=%.1f%% (%.1fGB)", free_pct, free_gb)
        return True, f'{free_pct:.1f}% libre ({free_gb:.1f}GB)'
    except Exception as e:
        return True, f'disk check skipped: {e}'


# ── Estadísticas para métricas ────────────────────────────────────────────────

def _get_db_stats() -> dict:
    """Estadísticas básicas de la base de datos."""
    try:
        with connection.cursor() as cursor:
            # Tamaño de la BD
            cursor.execute(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            )
            db_size = cursor.fetchone()[0]

            # Conexiones activas
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
            )
            active_conns = cursor.fetchone()[0]

        return {
            'size':              db_size,
            'active_connections': active_conns,
            'engine':            settings.DATABASES['default']['ENGINE'].split('.')[-1],
        }
    except Exception as e:
        return {'error': str(e)}


def _get_celery_stats() -> dict:
    """Estadísticas de tareas Celery."""
    try:
        from django_celery_results.models import TaskResult
        from django.utils import timezone
        from datetime import timedelta

        since = timezone.now() - timedelta(hours=24)
        total    = TaskResult.objects.filter(date_created__gte=since).count()
        success  = TaskResult.objects.filter(date_created__gte=since, status='SUCCESS').count()
        failed   = TaskResult.objects.filter(date_created__gte=since, status='FAILURE').count()
        pending  = TaskResult.objects.filter(date_created__gte=since, status='PENDING').count()

        return {
            'last_24h': {
                'total':   total,
                'success': success,
                'failed':  failed,
                'pending': pending,
                'success_rate': f'{(success/total*100):.1f}%' if total else 'N/A',
            }
        }
    except Exception as e:
        return {'error': str(e)}


def _get_today_tx_stats() -> dict:
    """Estadísticas de transacciones del día para el dashboard de métricas."""
    try:
        from transactions.models import Transaction
        from django.utils import timezone

        today = timezone.localdate()
        qs = Transaction.objects.filter(created_at__date=today)

        return {
            'total':     qs.count(),
            'completed': qs.filter(status='COMPLETED').count(),
            'pending':   qs.filter(status='PENDING').count(),
            'cancelled': qs.filter(status='CANCELLED').count(),
        }
    except Exception as e:
        return {'error': str(e)}
