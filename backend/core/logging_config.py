"""
Configuración de logging profesional para Kapitalya ERP.

Niveles:
  - CRITICAL: sistema caído, pérdida de datos posible
  - ERROR:    operación falló, requiere intervención
  - WARNING:  anomalía detectada, sistema continúa
  - INFO:     eventos de negocio (transacciones, logins, etc.)
  - DEBUG:    diagnóstico técnico detallado

Destinos:
  - consola:          todos los niveles (desarrollo)
  - archivo app:      INFO+ (producción)
  - archivo errores:  ERROR+ con stack trace completo
  - archivo audit:    transacciones financieras inmutables
  - archivo celery:   tareas asíncronas
"""
import logging
import logging.config
import os
from pathlib import Path


def get_logging_config(base_dir: Path, debug: bool = False) -> dict:
    log_dir = base_dir / 'logs'
    log_dir.mkdir(exist_ok=True)

    level = 'DEBUG' if debug else 'INFO'

    return {
        'version': 1,
        'disable_existing_loggers': False,

        # ── Formatters ────────────────────────────────────────────────────────
        'formatters': {
            # Formato humano para consola en desarrollo
            'console': {
                'format': (
                    '\033[36m%(asctime)s\033[0m '
                    '%(levelcolor)s%(levelname)-8s\033[0m '
                    '\033[90m%(name)s\033[0m '
                    '%(message)s'
                ),
                '()': 'core.logging_config.ColoredFormatter',
                'datefmt': '%H:%M:%S',
            },
            # Formato estructurado para archivos (parseable por Loki/ELK)
            'structured': {
                'format': (
                    '%(asctime)s | %(levelname)-8s | %(name)-20s | '
                    'pid=%(process)d | %(message)s'
                ),
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
            # Formato JSON para producción — parseable por cualquier stack de observabilidad
            'json': {
                '()': 'core.logging_config.JsonFormatter',
            },
            # Formato para audit log financiero — NO cambiar estructura
            'audit': {
                'format': '%(asctime)s | AUDIT | %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
            # Formato mínimo para consola simple (producción)
            'simple': {
                'format': '[%(levelname)s] %(name)s: %(message)s',
            },
        },

        # ── Filters ───────────────────────────────────────────────────────────
        'filters': {
            'require_debug_false': {
                '()': 'django.utils.log.RequireDebugFalse',
            },
            'require_debug_true': {
                '()': 'django.utils.log.RequireDebugTrue',
            },
        },

        # ── Handlers ──────────────────────────────────────────────────────────
        'handlers': {
            # Consola — siempre activa
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'console' if debug else 'simple',
                'level': level,
            },

            # Archivo principal — todos los eventos INFO+
            'file_app': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': str(log_dir / 'kapitalya.log'),
                'when': 'midnight',
                'backupCount': 30,
                'encoding': 'utf-8',
                'formatter': 'structured',
                'level': 'INFO',
            },

            # Archivo de errores — solo ERROR y CRITICAL con traceback completo
            'file_errors': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': str(log_dir / 'errors.log'),
                'when': 'midnight',
                'backupCount': 90,
                'encoding': 'utf-8',
                'formatter': 'structured',
                'level': 'ERROR',
            },

            # Audit log financiero — transacciones e immutable trail
            'file_audit': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': str(log_dir / 'audit.log'),
                'when': 'midnight',
                'backupCount': 365,  # 1 año de historial
                'encoding': 'utf-8',
                'formatter': 'audit',
                'level': 'INFO',
            },

            # Archivo de tareas Celery
            'file_celery': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': str(log_dir / 'celery.log'),
                'when': 'midnight',
                'backupCount': 30,
                'encoding': 'utf-8',
                'formatter': 'structured',
                'level': 'INFO',
            },

            # Archivo de ML/predicciones
            'file_ml': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': str(log_dir / 'ml.log'),
                'when': 'midnight',
                'backupCount': 30,
                'encoding': 'utf-8',
                'formatter': 'structured',
                'level': 'INFO',
            },

            # Archivo de requests HTTP
            'file_requests': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': str(log_dir / 'requests.log'),
                'when': 'midnight',
                'backupCount': 14,
                'encoding': 'utf-8',
                'formatter': 'structured',
                'level': 'INFO',
            },

            # Archivo de errores frontend (Error Boundaries, apiClient)
            'file_frontend_errors': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': str(log_dir / 'frontend_errors.log'),
                'when': 'midnight',
                'backupCount': 30,
                'encoding': 'utf-8',
                'formatter': 'json' if not debug else 'structured',
                'level': 'WARNING',
            },

            # Archivo de seguridad — rate limits, accesos denegados
            'file_security': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': str(log_dir / 'security.log'),
                'when': 'midnight',
                'backupCount': 90,
                'encoding': 'utf-8',
                'formatter': 'structured',
                'level': 'WARNING',
            },

            # Null handler para silenciar loggers ruidosos
            'null': {
                'class': 'logging.NullHandler',
            },
        },

        # ── Loggers ───────────────────────────────────────────────────────────
        'loggers': {
            # Django core
            'django': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': 'WARNING',
                'propagate': False,
            },
            'django.request': {
                'handlers': ['console', 'file_requests', 'file_errors'],
                'level': 'WARNING',
                'propagate': False,
            },
            'django.security': {
                'handlers': ['console', 'file_security', 'file_errors'],
                'level': 'WARNING',
                'propagate': False,
            },
            'django.db.backends': {
                'handlers': ['file_app'] if not debug else ['console'],
                'level': 'WARNING',  # cambiar a DEBUG para ver SQL
                'propagate': False,
            },

            # Apps de negocio
            'transactions': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': level,
                'propagate': False,
            },
            'rates': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': level,
                'propagate': False,
            },
            'inventory': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': level,
                'propagate': False,
            },
            'capital': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': level,
                'propagate': False,
            },
            'tarjetas': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': level,
                'propagate': False,
            },
            'reports': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': level,
                'propagate': False,
            },
            'users': {
                'handlers': ['console', 'file_app', 'file_security', 'file_errors'],
                'level': level,
                'propagate': False,
            },

            # Audit financiero — logger especial inmutable
            'audit': {
                'handlers': ['file_audit', 'console'],
                'level': 'INFO',
                'propagate': False,
            },

            # Requests HTTP (middleware)
            'kapitalya.requests': {
                'handlers': ['console', 'file_requests'],
                'level': 'INFO',
                'propagate': False,
            },

            # Seguridad
            'kapitalya.security': {
                'handlers': ['console', 'file_security', 'file_errors'],
                'level': 'WARNING',
                'propagate': False,
            },

            # Monitoreo y salud del sistema
            'kapitalya.health': {
                'handlers': ['console', 'file_app'],
                'level': 'INFO',
                'propagate': False,
            },

            # ML / predicciones
            'predictions': {
                'handlers': ['console', 'file_ml', 'file_errors'],
                'level': level,
                'propagate': False,
            },
            'kapitalya.ml': {
                'handlers': ['console', 'file_ml', 'file_errors'],
                'level': 'INFO',
                'propagate': False,
            },

            # Celery
            'celery': {
                'handlers': ['console', 'file_celery', 'file_errors'],
                'level': 'INFO',
                'propagate': False,
            },
            'celery.task': {
                'handlers': ['console', 'file_celery', 'file_errors'],
                'level': 'INFO',
                'propagate': False,
            },
            'kapitalya.tasks': {
                'handlers': ['console', 'file_celery', 'file_errors'],
                'level': 'INFO',
                'propagate': False,
            },

            # Frontend errors — capturados por Error Boundaries
            'kapitalya.frontend_errors': {
                'handlers': ['console', 'file_frontend_errors'],
                'level': 'WARNING',
                'propagate': False,
            },

            # Circuit breaker / fetchers de tasas
            'kapitalya.rates.fetcher': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': 'WARNING',
                'propagate': False,
            },

            # Analytics
            'analytics': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': level,
                'propagate': False,
            },

            # Alerts
            'alerts': {
                'handlers': ['console', 'file_app', 'file_errors'],
                'level': level,
                'propagate': False,
            },

            # Silenciar librerías ruidosas
            'PIL':             {'handlers': ['null'], 'propagate': False},
            'tensorflow':      {'handlers': ['null'], 'propagate': False},
            'prophet':         {'handlers': ['null'], 'propagate': False},
            'cmdstanpy':       {'handlers': ['null'], 'propagate': False},
            'numexpr':         {'handlers': ['null'], 'propagate': False},
            'matplotlib':      {'handlers': ['null'], 'propagate': False},
        },

        # ── Root logger ───────────────────────────────────────────────────────
        'root': {
            'handlers': ['console', 'file_app', 'file_errors'],
            'level': level,
        },
    }


class JsonFormatter(logging.Formatter):
    """Formatter JSON para producción — facilita parseo en Loki/ELK/CloudWatch."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        import traceback
        from datetime import datetime, timezone

        payload = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level':     record.levelname,
            'logger':    record.name,
            'message':   record.getMessage(),
            'pid':       record.process,
            'module':    record.module,
        }
        if record.exc_info:
            payload['exception'] = traceback.format_exception(*record.exc_info)
        # Incluir campos extra si los hay (error_id, user_id, etc.)
        for key in ('error_id', 'user_id', 'company_id', 'request_id', 'task_id'):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    """Formatter con colores ANSI para consola en desarrollo."""

    COLORS = {
        'DEBUG':    '\033[94m',   # Azul
        'INFO':     '\033[92m',   # Verde
        'WARNING':  '\033[93m',   # Amarillo
        'ERROR':    '\033[91m',   # Rojo
        'CRITICAL': '\033[95m',   # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        record.levelcolor = self.COLORS.get(record.levelname, '')
        return super().format(record)
