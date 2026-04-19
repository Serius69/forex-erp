import os
import uuid
from pathlib import Path
from datetime import timedelta
import environ
import warnings

os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
warnings.filterwarnings('ignore', category=DeprecationWarning)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY    = env('SECRET_KEY', default='insecure-fallback-key-cambiar')
DEBUG         = env.bool('DEBUG', default=False)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', '0.0.0.0', '10.0.2.2'])

# ── Telegram Bot ─────────────────────────────────────────────────────
# Dejar vacíos para deshabilitar notificaciones Telegram en dev/CI.
TELEGRAM_BOT_TOKEN = env('TELEGRAM_BOT_TOKEN', default='')
TELEGRAM_CHAT_ID   = env('TELEGRAM_CHAT_ID',   default='')
# Umbral para considerar una transacción de "alto monto" (en BOB)
LARGE_TX_THRESHOLD_BOB = env.int('LARGE_TX_THRESHOLD_BOB', default=100_000)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'channels',
    'django_filters',
    'django_celery_beat',
    'django_celery_results',
    'users',
    'rates',
    'transactions',
    'inventory',
    'predictions',
    'reports',
    'capital',
    'tarjetas',
    'analytics',
    'data_migration',
    'snapshots',
    'alerts',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Kapitalya custom middleware — orden importa
    'core.middleware.RequestIDMiddleware',       # 1. Asignar ID único al request
    'core.middleware.RequestLoggingMiddleware',  # 2. Log request + tiempo respuesta
    'core.middleware.IdempotencyMiddleware',     # 3. Deduplicar transacciones
    'core.middleware.SecurityHeadersMiddleware', # 4. Headers de seguridad
    'core.middleware.QueryCountMiddleware',      # 5. Detectar N+1 queries
    'core.maintenance.MaintenanceModeMiddleware', # 6. Bloquear en mantenimiento
]

ROOT_URLCONF     = 'core.urls'
WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'
AUTH_USER_MODEL  = 'users.User'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

DATABASES = {
    'default': {
        'ENGINE':       env('DB_ENGINE',   default='django.db.backends.postgresql'),
        'NAME':         env('DB_NAME',     default='forex_erp'),
        'USER':         env('DB_USER',     default='postgres'),
        'PASSWORD':     env('DB_PASSWORD', default=''),
        'HOST':         env('DB_HOST',     default='127.0.0.1'),
        'PORT':         env('DB_PORT',     default='5432'),
        'CONN_MAX_AGE': 60,
        'OPTIONS': {
            'connect_timeout': 10,
            'application_name': 'kapitalya-erp',
        },
        'TEST': {
            'NAME': 'test_forex_erp',
        },
    }
}

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':    timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME':   timedelta(days=7),
    'ROTATE_REFRESH_TOKENS':    True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN':        True,
    'ALGORITHM':                'HS256',
    'AUTH_HEADER_TYPES':        ('Bearer',),
    'AUTH_HEADER_NAME':         'HTTP_AUTHORIZATION',
    'USER_ID_FIELD':            'id',
    'USER_ID_CLAIM':            'user_id',
}

CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    'http://localhost:3000',
    'http://localhost:3001',
])
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'accept', 'accept-encoding', 'authorization',
    'content-type', 'dnt', 'origin', 'user-agent',
    'x-csrftoken', 'x-requested-with',
    'idempotency-key',
]

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

CELERY_BROKER_URL                    = env('CELERY_BROKER_URL',     default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND                = env('CELERY_RESULT_BACKEND', default='redis://localhost:6379/1')
CELERY_ACCEPT_CONTENT                = ['json']
CELERY_TASK_SERIALIZER               = 'json'
CELERY_RESULT_SERIALIZER             = 'json'
CELERY_TIMEZONE                      = 'America/La_Paz'
CELERY_BEAT_SCHEDULER                = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_TRACK_STARTED            = True
CELERY_TASK_TIME_LIMIT               = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT          = 25 * 60  # warn before hard kill
CELERY_TASK_ACKS_LATE                = True      # ack after task succeeds
CELERY_TASK_REJECT_ON_WORKER_LOST   = True      # requeue if worker dies
CELERY_WORKER_PREFETCH_MULTIPLIER   = 1         # no prefetch — fair scheduling
CELERY_TASK_MAX_RETRIES             = 5
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES      = 10
CELERY_TASK_ALWAYS_EAGER                  = False  # siempre async

# Rutas de tareas por prioridad
CELERY_TASK_ROUTES = {
    'transactions.*':   {'queue': 'critical'},
    'rates.*':          {'queue': 'high'},
    'inventory.*':      {'queue': 'high'},
    'analytics.*':      {'queue': 'default'},
    'predictions.*':    {'queue': 'low'},
    'reports.*':        {'queue': 'low'},
    'core.tasks.*':     {'queue': 'default'},
}

# Guardar resultados de tareas 24h
CELERY_RESULT_EXPIRES = 86400

# ── Celery Beat — Schedule de analytics ──────────────────────────────────────
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # Spreads: cada 15 min durante horario de operación
    'analytics-snapshot-spreads': {
        'task':     'analytics.snapshot_spreads',
        'schedule': 15 * 60,   # cada 15 minutos
        'options':  {'queue': 'default'},
    },
    # Exposición: cada 30 min
    'analytics-snapshot-exposure': {
        'task':     'analytics.snapshot_exposure',
        'schedule': 30 * 60,
        'options':  {'queue': 'default'},
    },
    # P&L diario: recálculo cada hora
    'analytics-recalculate-pnl': {
        'task':     'analytics.recalculate_pnl_daily',
        'schedule': 60 * 60,
        'options':  {'queue': 'default'},
    },
    # Limpieza snapshots: cada noche a las 02:00
    'analytics-cleanup-snapshots': {
        'task':     'analytics.cleanup_old_snapshots',
        'schedule': crontab(hour=2, minute=0),
        'options':  {'queue': 'default'},
    },
    # Binance P2P: cada 5 minutos
    'rates-binance-p2p': {
        'task':     'rates.fetch_binance_p2p',
        'schedule': 5 * 60,
        'options':  {'queue': 'high'},
    },
    # AI Pricing Engine: cada 15 minutos (después de Binance)
    'rates-ai-pricing': {
        'task':     'rates.update_ai_pricing',
        'schedule': 15 * 60,
        'options':  {'queue': 'default'},
    },
    # Smart Alerts: cada 10 minutos
    'rates-smart-alerts': {
        'task':     'rates.check_smart_alerts',
        'schedule': 10 * 60,
        'options':  {'queue': 'default'},
    },
    # BCB rates: cada 30 minutos
    'rates-bcb-update': {
        'task':     'rates.update_bcb_rates',
        'schedule': 30 * 60,
        'options':  {'queue': 'high'},
    },
    # ALL rates (todas las fuentes incluyendo DolarApi, BCP, externos): cada 3 minutos
    'rates-all-update': {
        'task':     'rates.update_all_rates',
        'schedule': 3 * 60,
        'options':  {'queue': 'high'},
    },
    # Digital rates (Takenos, Airtm): cada 5 minutos
    'rates-digital-update': {
        'task':     'rates.update_digital_rates',
        'schedule': 5 * 60,
        'options':  {'queue': 'high'},
    },
    # Parallel market: cada 5 minutos
    'rates-parallel-update': {
        'task':     'rates.update_parallel_rates',
        'schedule': 5 * 60,
        'options':  {'queue': 'high'},
    },
    # Mark primary rates: cada 2 minutos (después de cualquier update)
    'rates-mark-primary': {
        'task':     'rates.mark_primary_rates',
        'schedule': 2 * 60,
        'options':  {'queue': 'high'},
    },
    # Divergence check: cada 10 minutos
    'rates-divergence-check': {
        'task':     'rates.check_source_divergence',
        'schedule': 10 * 60,
        'options':  {'queue': 'default'},
    },
    # Predicciones ML: diario a las 01:00
    'predictions-daily-forecast': {
        'task':     'predictions.generate_daily_forecast',
        'schedule': crontab(hour=1, minute=0),
        'options':  {'queue': 'low'},
    },
}

# ── Performance settings ──────────────────────────────────────────────────────
# Detectar queries lentas (>200ms en desarrollo, >500ms en producción)
SLOW_QUERY_THRESHOLD_MS = env.int('SLOW_QUERY_THRESHOLD_MS', default=500)

# Número máximo de queries por request antes de emitir WARNING
MAX_QUERIES_PER_REQUEST = env.int('MAX_QUERIES_PER_REQUEST', default=30)

# Tiempo máximo de respuesta esperado (ms) — por encima se loguea como slow
SLOW_REQUEST_THRESHOLD_MS = env.int('SLOW_REQUEST_THRESHOLD_MS', default=2000)

# ── Monitoring ────────────────────────────────────────────────────────────────
KAPITALYA_VERSION = '1.0.1'
KAPITALYA_ENV = env('ENVIRONMENT', default='development')

# ── Contabilidad de caja ──────────────────────────────────────────────────────
# Si False (default), apply_transaction_effects rechaza operaciones que resulten
# en un campo de CapitalComposicion negativo (fuertes, qr_transferencias, etc.).
# Poner True solo en ambientes de prueba o cuando el negocio lo permita explícitamente.
KAPITALYA_ALLOW_NEGATIVE_EFECTIVO = env.bool('KAPITALYA_ALLOW_NEGATIVE_EFECTIVO', default=False)

# ── Google Sheets — importación y exportación bidireccional ──────────────────
GOOGLE_SHEETS_CREDENTIALS_PATH = env(
    'GOOGLE_SHEETS_CREDENTIALS_PATH',
    default=str(BASE_DIR / 'google_sheets_credentials.json'),
)
MIGRATION_BATCH_SIZE = env.int('MIGRATION_BATCH_SIZE', default=100)

# URL del spreadsheet para auto-sync periódico (vacío = deshabilitado)
GOOGLE_SHEETS_AUTO_SYNC_URL = env('GOOGLE_SHEETS_AUTO_SYNC_URL', default='')
# Intervalos en minutos para el cron de auto-sync
GOOGLE_SHEETS_AUTO_SYNC_INTERVAL = env.int('GOOGLE_SHEETS_AUTO_SYNC_INTERVAL', default=30)
# Targets del auto-sync: capital, inventory, rates
GOOGLE_SHEETS_AUTO_SYNC_TARGETS = env.list(
    'GOOGLE_SHEETS_AUTO_SYNC_TARGETS', default=['capital', 'inventory', 'rates']
)
# Habilitar escritura (push_snapshot). Requiere que la cuenta de servicio
# tenga permiso de edición en el spreadsheet destino.
GOOGLE_SHEETS_WRITABLE = env.bool('GOOGLE_SHEETS_WRITABLE', default=False)

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-bo'
TIME_ZONE     = 'America/La_Paz'
USE_TZ        = True
USE_I18N      = True
USE_L10N      = True

STATIC_URL  = '/static/'
STATIC_ROOT = env('STATIC_ROOT', default=str(BASE_DIR / 'staticfiles'))
MEDIA_URL   = '/media/'
MEDIA_ROOT  = env('MEDIA_ROOT',  default=str(BASE_DIR / 'media'))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
