# settings/development.py
from .base import *

DEBUG = True

# CORS abierto en dev — acepta cualquier origen
CORS_ALLOW_ALL_ORIGINS = True

# Email en consola (no necesita servidor SMTP)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Cache en memoria (no necesita Redis para cache)
CACHES = {
    'default': {
        'BACKEND':  'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'forex-dev-cache',
    }
}

# Logging simple para dev
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '[%(levelname)s] %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class':     'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level':    'INFO',
    },
    'loggers': {
        'django.db.backends': {
            'handlers':  ['console'],
            'level':     'WARNING',  # cambiar a DEBUG para ver todas las queries SQL
            'propagate': False,
        },
        'reports':      {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
        'transactions': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
        'rates':        {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
    },
}


CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}