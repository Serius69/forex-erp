from .base import *
from datetime import timedelta
from core.logging_config import get_logging_config

DEBUG = True
ENVIRONMENT = 'development'
KAPITALYA_ENV = 'development'

CORS_ALLOW_ALL_ORIGINS = True

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

CACHES = {
    'default': {
        'BACKEND':  'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'kapitalya-dev-cache',
        'TIMEOUT':  300,
        'OPTIONS': {
            'MAX_ENTRIES': 1000,
        },
    }
}

STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

SIMPLE_JWT = {
    **SIMPLE_JWT,
    'ACCESS_TOKEN_LIFETIME':  timedelta(hours=24),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
}

# ── Performance thresholds más bajos en dev para detectar problemas antes ─────
SLOW_QUERY_THRESHOLD_MS   = 200
MAX_QUERIES_PER_REQUEST   = 20
SLOW_REQUEST_THRESHOLD_MS = 1000

# ── Logging profesional ───────────────────────────────────────────────────────
LOGGING = get_logging_config(BASE_DIR, debug=True)

# En desarrollo también mostrar SQL lento si DEBUG_SQL=1 en .env
if env.bool('DEBUG_SQL', default=False):
    LOGGING['loggers']['django.db.backends'] = {
        'handlers': ['console'],
        'level': 'DEBUG',
        'propagate': False,
    }
