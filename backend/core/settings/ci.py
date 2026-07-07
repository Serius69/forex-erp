from .base import *

DEBUG = False
ENVIRONMENT = 'ci'

# Use in-memory channel layer — no Redis dependency for unit tests
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

# Fast password hasher for tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# In-memory cache
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# Disable email
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'

# Suppress staticfiles warnings
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# Silence system checks that are irrelevant in CI
SILENCED_SYSTEM_CHECKS = ['security.W004', 'security.W008', 'security.W012']
