# Production settings for Kapitalya backend.
from .base import *
from datetime import timedelta
import os
from core.logging_config import get_logging_config

DEBUG = False
ENVIRONMENT = 'production'
KAPITALYA_ENV = 'production'

TAILSCALE_IP   = env('TAILSCALE_IP', default='100.x.x.x')
TAILSCALE_MODE = env.bool('TAILSCALE_MODE', default=True)  # HTTP en red privada Tailscale

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[TAILSCALE_IP, 'localhost', '127.0.0.1'])

# Django 4+ requiere CSRF_TRUSTED_ORIGINS para cualquier host que no sea localhost
CSRF_TRUSTED_ORIGINS = env.list(
    'CSRF_TRUSTED_ORIGINS',
    default=[f'http://{TAILSCALE_IP}', f'https://{TAILSCALE_IP}'],
)

CORS_ALLOWED_ORIGINS   = env.list('CORS_ALLOWED_ORIGINS', default=[f'http://{TAILSCALE_IP}'])
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True

# REDIS_URL     → DB 1 (Celery results + Channels)
# REDIS_URL_CACHE → DB 2 (Django cache)
_redis_channels = env('REDIS_URL',       default='redis://127.0.0.1:6379/1')
_redis_cache    = env('REDIS_URL_CACHE', default='redis://127.0.0.1:6379/2')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts':    [_redis_channels],
            'capacity': 1500,
            'expiry':   10,
        },
    }
}

CACHES = {
    'default': {
        'BACKEND':  'django.core.cache.backends.redis.RedisCache',
        'LOCATION': _redis_cache,
    }
}

MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DATABASES['default']['CONN_MAX_AGE'] = 120

SECURE_BROWSER_XSS_FILTER   = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS             = 'DENY'
SECURE_REFERRER_POLICY      = 'same-origin'
SESSION_COOKIE_HTTPONLY     = True
CSRF_COOKIE_HTTPONLY        = True
SESSION_COOKIE_SAMESITE     = 'Lax'

# En Tailscale el tráfico es HTTP (WireGuard cifra a nivel de red, no TLS)
# Cuando TAILSCALE_MODE=True: desactivar redirecciones HTTPS y cookies Secure
SECURE_SSL_REDIRECT            = False  # Tailscale maneja el cifrado
SECURE_HSTS_SECONDS            = 0 if TAILSCALE_MODE else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not TAILSCALE_MODE
SECURE_HSTS_PRELOAD            = not TAILSCALE_MODE
SESSION_COOKIE_SECURE          = not TAILSCALE_MODE  # False en HTTP Tailscale
CSRF_COOKIE_SECURE             = not TAILSCALE_MODE  # False en HTTP Tailscale

SIMPLE_JWT = {
    **SIMPLE_JWT,
    'ACCESS_TOKEN_LIFETIME':  timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
}

EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST          = env('EMAIL_HOST',          default='smtp.gmail.com')
EMAIL_PORT          = env.int('EMAIL_PORT',      default=587)
EMAIL_USE_TLS       = True
EMAIL_HOST_USER     = env('EMAIL_HOST_USER',     default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL  = env('DEFAULT_FROM_EMAIL',  default='noreply@kapitalya.bo')

# ── Performance thresholds producción ────────────────────────────────────────
SLOW_QUERY_THRESHOLD_MS   = 500
MAX_QUERIES_PER_REQUEST   = 30
SLOW_REQUEST_THRESHOLD_MS = 3000

# ── Logging profesional producción ────────────────────────────────────────────
LOGGING = get_logging_config(BASE_DIR, debug=False)