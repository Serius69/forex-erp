# Este archivo hace que Django cargue la app Celery al iniciar.
from .celery import app as celery_app

__all__ = ('celery_app',)
