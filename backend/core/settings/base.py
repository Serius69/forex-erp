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
# Firehose: avisar por Telegram CUALQUIER cambio de tasa (no solo variaciones >5%).
# Poner en False para recibir solo las alertas de variación significativa.
TELEGRAM_RATE_FIREHOSE = env.bool('TELEGRAM_RATE_FIREHOSE', default=True)
# Movimiento mínimo (%) para avisar un cambio de tasa por Telegram. Evita el ruido
# de micro-ticks: solo se avisa cuando un buy/sell se desvía ≥ este % del último
# valor notificado. Subir para menos avisos, bajar para más sensibilidad.
TELEGRAM_RATE_MIN_PCT = env.float('TELEGRAM_RATE_MIN_PCT', default=0.5)

# ── FX Engine — External API Keys ────────────────────────────────────
# Eldorado.io: Bearer token for GET https://api.eldorado.io/api/v1/rates
ELDORADO_API_TOKEN = env('ELDORADO_API_TOKEN', default='')
# Wallbit: API key for GET https://api.wallbit.io/v1/rates
WALLBIT_API_KEY    = env('WALLBIT_API_KEY',    default='')
# Umbral para considerar una transacción de "alto monto" (en BOB)
LARGE_TX_THRESHOLD_BOB = env.int('LARGE_TX_THRESHOLD_BOB', default=100_000)

# ── Email / Alertas ──────────────────────────────────────────────────
# Configurar SMTP para alertas de email. Ejemplo Gmail:
#   EMAIL_HOST=smtp.gmail.com
#   EMAIL_HOST_USER=tu@gmail.com
#   EMAIL_HOST_PASSWORD=app-password
# Si EMAIL_HOST está vacío, el backend usará ConsoleEmailBackend (imprime en log).
EMAIL_BACKEND     = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST        = env('EMAIL_HOST',        default='')
EMAIL_PORT        = env.int('EMAIL_PORT',    default=587)
EMAIL_USE_TLS     = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER   = env('EMAIL_HOST_USER',   default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL  = env('DEFAULT_FROM_EMAIL',  default='Kapitalya ERP <noreply@kapitalya.bo>')
# Destinatarios de alertas CRITICAL/HIGH — lista separada por comas
ALERT_EMAIL_RECIPIENTS = env.list('ALERT_EMAIL_RECIPIENTS', default=[])

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
    'tenants',
    'users',
    'rates',
    'transactions',
    'inventory',
    'predictions',
    'reports',
    'capital',
    'tarjetas',
    'analytics',
    'macro',
    'data_migration',
    'snapshots',
    'alerts',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.gzip.GZipMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Kapitalya custom middleware — orden importa
    'core.middleware.RequestIDMiddleware',       # 1. Asignar ID único al request
    'core.middleware.RequestLoggingMiddleware',  # 2. Log request + tiempo respuesta
    'core.middleware.Request400LoggerMiddleware',# 3. Loguear payload en errores 400
    'core.middleware.IdempotencyMiddleware',     # 4. Deduplicar transacciones
    'core.middleware.SecurityHeadersMiddleware', # 5. Headers de seguridad
    'core.middleware.QueryCountMiddleware',      # 6. Detectar N+1 queries
    'core.maintenance.MaintenanceModeMiddleware', # 7. Bloquear en mantenimiento
]

ROOT_URLCONF     = 'core.urls'
WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'
AUTH_USER_MODEL  = 'users.User'

AUTHENTICATION_BACKENDS = [
    # EmailOrUsername primero: evita el dummy-hash de ModelBackend en logins por email
    'users.auth_backends.EmailOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]

GOOGLE_CLIENT_ID = env('GOOGLE_CLIENT_ID', default='')

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
        'ENGINE':   env('DB_ENGINE',   default='django.db.backends.postgresql'),
        'NAME':     env('DB_NAME',     default='forex_erp'),
        'USER':     env('DB_USER',     default='postgres'),
        'PASSWORD': env('DB_PASSWORD', default=''),
        # Con pgbouncer en modo transaction: conectar al pgbouncer, no directo a postgres
        'HOST':     env('DB_HOST',     default='pgbouncer'),
        'PORT':     env('DB_PORT',     default='5432'),
        # pgbouncer transaction mode + CONN_MAX_AGE=0: Django no reutiliza conexiones,
        # deja que pgbouncer gestione el pool (evita "prepared statements" errors)
        'CONN_MAX_AGE': env.int('CONN_MAX_AGE', default=0),
        'OPTIONS': {
            'connect_timeout':  10,
            'application_name': 'kapitalya-erp',
            # Deshabilitar prepared statements (incompatibles con pgbouncer transaction mode)
            'options': '-c statement_timeout=30000',
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
    'DEFAULT_THROTTLE_CLASSES': [
        'core.throttling.ForexBurstThrottle',
        'core.throttling.ForexSustainedThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'burst':        '60/min',
        'sustained':    '1000/hour',
        'auth':         '10/min',
        'transactions': '30/min',
        'analytics':    '120/min',
        'rates':        '60/min',
        'anon':         '20/min',
        'none':         None,
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'CURSOR_PAGINATION_CLASS': 'core.pagination.KapitalyaCursorPagination',
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
}

# ── Cache TTLs (seconds) — match values in core/cache.py ─────────────────────
PARALLEL_RATE_CACHE_TTL     = 60
CAPITAL_POSITION_CACHE_TTL  = 30
SPREAD_CACHE_TTL            = 30
KPI_CACHE_TTL               = 300

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':    timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME':   timedelta(days=1),
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

# ── Django Channels — WebSocket layer ────────────────────────────────────────
# Redis-backed channel layer para soporte multi-proceso (Celery → WebSocket).
# Fallback a InMemoryChannelLayer si CHANNEL_REDIS_URL no está configurado.
_CHANNEL_REDIS_URL = env('CHANNEL_REDIS_URL', default='')

if _CHANNEL_REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [_CHANNEL_REDIS_URL],
                'capacity':      1000,
                'expiry':        60,
                'group_expiry':  86400,
            },
        }
    }
else:
    # Sin CHANNEL_REDIS_URL: InMemoryChannelLayer aísla cada proceso (Celery,
    # Daphne, gunicorn workers) en su propia cola en memoria, así que el push por
    # WebSocket entre procesos se pierde en silencio. Se permite SOLO en dev/CI/tests;
    # en producción es un fail-fast en vez de un fallback silencioso (auditoría #35).
    import sys as _sys
    _settings_module = os.environ.get('DJANGO_SETTINGS_MODULE', '')
    _running_tests = (
        _settings_module.endswith('.ci')
        or 'PYTEST_CURRENT_TEST' in os.environ
        or 'pytest' in os.path.basename(_sys.argv[0] if _sys.argv else '')
        or 'test' in _sys.argv
    )
    # DEBUG puede finalizarse en el módulo concreto DESPUÉS de este import, así que
    # también tratamos development.* como dev por el nombre del módulo de settings.
    _is_dev = DEBUG or _settings_module.endswith('.development')
    if not _is_dev and not _running_tests:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            'CHANNEL_REDIS_URL no está configurado. En producción los WebSockets '
            'requieren un channel layer Redis compartido: InMemoryChannelLayer aísla '
            'cada proceso y rompe el push multiproceso de forma silenciosa. '
            'Define CHANNEL_REDIS_URL antes de arrancar.'
        )
    # Desarrollo local o CI sin Redis: InMemoryChannelLayer (no multi-proceso)
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

# ── RabbitMQ (Celery broker) — Redis solo para caché y channel layer ──────────
RABBITMQ_URL = env(
    'RABBITMQ_URL',
    default='amqp://kapitalya:kapitalya_mq_pass@rabbitmq:5672/kapitalya',
)

CELERY_BROKER_URL                    = RABBITMQ_URL
CELERY_RESULT_BACKEND                = env('CELERY_RESULT_BACKEND', default='redis://redis:6379/1')
CELERY_ACCEPT_CONTENT                = ['json']
CELERY_TASK_SERIALIZER               = 'json'
CELERY_RESULT_SERIALIZER             = 'json'
CELERY_TIMEZONE                      = 'America/La_Paz'
CELERY_BEAT_SCHEDULER                = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_TRACK_STARTED            = True
CELERY_TASK_TIME_LIMIT               = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT          = 25 * 60
CELERY_TASK_ACKS_LATE                = True
CELERY_TASK_REJECT_ON_WORKER_LOST   = True
CELERY_WORKER_PREFETCH_MULTIPLIER   = 1
CELERY_TASK_MAX_RETRIES             = 5
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES      = 10
CELERY_TASK_ALWAYS_EAGER                  = False

# Reintentos con backoff exponencial (Celery 5+)
CELERY_TASK_AUTORETRY_FOR          = (Exception,)
CELERY_TASK_RETRY_BACKOFF          = True
CELERY_TASK_RETRY_BACKOFF_MAX      = 600   # máximo 10 minutos entre reintentos
CELERY_TASK_RETRY_JITTER           = True

# Colas kombu con exchanges dedicados para durabilidad
from kombu import Queue, Exchange

_critical_exchange = Exchange('critical', type='direct', durable=True)
_default_exchange  = Exchange('default',  type='direct', durable=True)
_low_exchange      = Exchange('low',      type='direct', durable=True)

CELERY_TASK_QUEUES = (
    Queue('critical', _critical_exchange, routing_key='critical', durable=True),
    Queue('high',     _critical_exchange, routing_key='high',     durable=True),
    Queue('default',  _default_exchange,  routing_key='default',  durable=True),
    Queue('low',      _low_exchange,      routing_key='low',      durable=True),
)
CELERY_TASK_DEFAULT_QUEUE        = 'default'
CELERY_TASK_DEFAULT_EXCHANGE     = 'default'
CELERY_TASK_DEFAULT_ROUTING_KEY = 'default'

# Rutas de tareas — 3 colas: critical (tiempo real), default, low (batch)
CELERY_TASK_ROUTES = {
    # ── critical: operaciones de negocio con impacto inmediato ────────────────
    'rates.tasks.continuous_fx_extraction':      {'queue': 'critical'},
    'rates.tasks.refresh_parallel_rates':        {'queue': 'critical'},
    'capital.tasks.update_position':             {'queue': 'critical'},
    'capital.check_capital_alerts':              {'queue': 'critical'},
    'transactions.refresh_fraud_rules_cache':    {'queue': 'critical'},
    'transactions.check_rate_lock_expirations':  {'queue': 'critical'},
    'rates.fetch_binance_p2p':                   {'queue': 'critical'},
    'rates.run_fx_engine':                       {'queue': 'critical'},
    # ── default: actualizaciones periódicas y analytics ──────────────────────
    'rates.*':          {'queue': 'default'},
    'inventory.*':      {'queue': 'default'},
    'analytics.*':      {'queue': 'default'},
    'capital.*':        {'queue': 'default'},
    'core.tasks.*':     {'queue': 'default'},
    # ── low: batch, ML, reportes, backups ────────────────────────────────────
    'predictions.tasks.generate_forecasts':      {'queue': 'low'},
    'predictions.tasks.retrain_models':          {'queue': 'low'},
    'predictions.*':    {'queue': 'low'},
    'reports.*':        {'queue': 'low'},
    'data_migration.*': {'queue': 'low'},
    'snapshots.*':      {'queue': 'low'},
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
    # DolarBlueBolivia: cada 15 minutos (referencia del mercado paralelo boliviano)
    'rates-dolar-blue-bolivia': {
        'task':     'rates.fetch_dolar_blue_bolivia',
        'schedule': 15 * 60,
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
    # ALL rates (todas las fuentes paralelas): cada 3 minutos
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
    # ── Pipeline ML de predicciones ───────────────────────────────────────────
    # OJO: DatabaseScheduler re-siembra estas entradas en BD al arrancar beat;
    # mantener en sync con rates/management/commands/sync_beat_schedule.py.
    'predictions-train-daily': {
        'task':     'predictions.train_all_prediction_models',
        'schedule': crontab(hour=2, minute=0),
        'options':  {'queue': 'low'},
    },
    'predictions-cache-hourly': {
        'task':     'predictions.cache_forecast_hourly',
        'schedule': 60 * 60,
        'options':  {'queue': 'low'},
    },
    'predictions-refresh-weights': {
        'task':     'predictions.refresh_ensemble_weights',
        'schedule': 4 * 60 * 60,
        'options':  {'queue': 'low'},
    },
    'predictions-evaluate-daily': {
        'task':     'predictions.evaluate_predictions',
        'schedule': crontab(hour=3, minute=0),
        'options':  {'queue': 'low'},
    },
    'predictions-weekly-backtest': {
        'task':     'predictions.weekly_backtest_report',
        'schedule': crontab(hour=4, minute=0, day_of_week=0),
        'options':  {'queue': 'low'},
    },
    'predictions-weekly-tuning': {
        'task':     'predictions.weekly_hyperparameter_tuning',
        'schedule': crontab(hour=5, minute=0, day_of_week=0),
        'options':  {'queue': 'low'},
    },
    # ── Tasa OFICIAL BCB (dolarapi → scrape BCB), base de la brecha ──────────
    'rates-official-daily': {
        'task':     'rates.update_exchange_rates',
        'schedule': crontab(hour=8, minute=5),
        'options':  {'queue': 'default'},
    },
    # ── Series físicas + higiene de tasas ────────────────────────────────────
    'rates-derive-empresa-daily': {
        'task':     'rates.derive_empresa_rates_daily',
        'schedule': crontab(hour=1, minute=30),
        'options':  {'queue': 'default'},
    },
    'rates-normalize-active': {
        'task':     'rates.normalize_active_rates',
        'schedule': crontab(hour=4, minute=30),
        'options':  {'queue': 'default'},
    },
    'rates-cleanup-old': {
        'task':     'rates.cleanup_old_rates',
        'schedule': crontab(hour=3, minute=30),
        'options':  {'queue': 'low'},
    },
    # ── Backup diario de PostgreSQL (dinero real: no puede faltar) ────────────
    'backup-database-daily': {
        'task':     'core.tasks.backup_database',
        'schedule': crontab(hour=3, minute=0),
        'options':  {'queue': 'default'},
    },
    # ── ETL Google Sheet operativo ───────────────────────────────────────────
    'transactions-sheet-sync': {
        'task':     'transactions.sync_sheet_transactions',
        'schedule': 30 * 60,
        'options':  {'queue': 'default'},
    },
    # ── Indicadores macro Bolivia ────────────────────────────────────────────
    'macro-daily-indicators': {
        'task':     'macro.fetch_daily_indicators',
        'schedule': crontab(hour=8, minute=30),
        'options':  {'queue': 'default'},
    },
    'macro-worldbank-weekly': {
        'task':     'macro.fetch_world_bank_indicators',
        'schedule': crontab(hour=6, minute=0, day_of_week=1),
        'options':  {'queue': 'low'},
    },
    'macro-news-4h': {
        'task':     'macro.fetch_news',
        'schedule': 4 * 60 * 60,
        'options':  {'queue': 'default'},
    },
    # Kickstart del loop continuo (Redis lock deduplica si ya corre)
    'rates-continuous-kickstart': {
        'task':     'rates.continuous_fx_extraction',
        'schedule': 15 * 60,
        'options':  {'queue': 'critical'},
    },
    # ── Auto Profit Mode — optimizador de tasas ──────────────────────────────
    # Ejecutar cada 10 minutos para detectar oportunidades de margen
    'rates-profit-optimizer': {
        'task':     'rates.run_profit_optimizer',
        'schedule': 10 * 60,
        'options':  {'queue': 'high'},
    },
    # ── Variantes de efectivo — recalcular después de cada update principal ──
    'rates-cash-variants': {
        'task':     'rates.update_cash_variants',
        'schedule': 10 * 60,
        'options':  {'queue': 'high'},
    },
    # ── Snapshot diario — cierre de operaciones 18:00 hora Bolivia ───────────
    'rates-daily-snapshot': {
        'task':     'rates.create_daily_snapshot',
        'schedule': crontab(hour=18, minute=0),
        'options':  {'queue': 'default'},
    },
    # ── Snapshot nocturno adicional — medianoche para archivado ──────────────
    'rates-midnight-snapshot': {
        'task':     'rates.create_daily_snapshot',
        'schedule': crontab(hour=0, minute=0),
        'options':  {'queue': 'default'},
    },

    # ── Tareas que estaban DEFINIDAS pero nunca agendadas (cableadas 2026-07-16).
    #    Cada una tenía su cadencia prevista en su docstring pero faltaba en el
    #    beat, así que jamás corría (rate-locks sin expirar, snapshots de capital
    #    y de apertura/cierre nunca tomados, alertas de capital mudas, caché
    #    antifraude sin refresco, detección de anomalías solo on-demand).
    # Expiración de tasas bloqueadas: cada 2 min (impacto operativo inmediato).
    'transactions-rate-lock-expire': {
        'task':     'transactions.check_rate_lock_expirations',
        'schedule': 2 * 60,
        'options':  {'queue': 'critical'},
    },
    # Refresco del caché de reglas antifraude: cada 30 min.
    'transactions-fraud-rules-refresh': {
        'task':     'transactions.refresh_fraud_rules_cache',
        'schedule': 30 * 60,
        'options':  {'queue': 'critical'},
    },
    # Alertas de capital: cada 15 min (según docstring).
    'capital-check-alerts': {
        'task':     'capital.check_capital_alerts',
        'schedule': 15 * 60,
        'options':  {'queue': 'critical'},
    },
    # P&L no realizado: cada hora (según docstring).
    'capital-update-unrealized-pnl': {
        'task':     'capital.update_unrealized_pnl',
        'schedule': 60 * 60,
        'options':  {'queue': 'default'},
    },
    # Snapshot diario de posición de capital por sucursal: cierre 23:15.
    'capital-daily-snapshots': {
        'task':     'capital.save_daily_snapshots',
        'schedule': crontab(hour=23, minute=15),
        'options':  {'queue': 'default'},
    },
    # Snapshot de sistema — apertura del día: 08:00 (según docstring).
    'snapshots-opening': {
        'task':     'snapshots.take_opening_snapshot',
        'schedule': crontab(hour=8, minute=0),
        'options':  {'queue': 'low'},
    },
    # Snapshot de sistema — cierre del día: 23:45 (según docstring).
    'snapshots-closing': {
        'task':     'snapshots.take_closing_snapshot',
        'schedule': crontab(hour=23, minute=45),
        'options':  {'queue': 'low'},
    },
    # Detección automática de anomalías (antes solo on-demand): cada hora.
    'analytics-detect-anomalies': {
        'task':     'analytics.detect_anomalies',
        'schedule': 60 * 60,
        'options':  {'queue': 'default'},
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
