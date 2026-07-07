import logging
from django.apps import AppConfig

log = logging.getLogger('kapitalya.rates')


class RatesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rates'

    def ready(self):
        import rates.signals  # noqa — registers post_save for ExchangeRate
        from django.db.models.signals import post_migrate
        post_migrate.connect(_start_continuous_loop, sender=self)


def _start_continuous_loop(sender, **kwargs):
    """
    Inicia el loop continuo de extracción una sola vez por arranque del sistema.
    Se dispara después de que post_migrate garantice que las tablas existen.
    Usa un lock Redis para no lanzar el loop si ya hay una instancia corriendo.
    """
    try:
        from django.core.cache import cache
        from rates.tasks import _LOOP_LOCK_KEY, continuous_fx_extraction

        if cache.get(_LOOP_LOCK_KEY):
            log.info('CONTINUOUS_FX already_running — skip auto-start')
            return

        continuous_fx_extraction.apply_async(countdown=5)
        log.info('CONTINUOUS_FX auto-start enqueued (countdown=5s)')
    except Exception as exc:
        # No interrumpir el arranque del servidor si Celery/Redis no está listo
        log.warning('CONTINUOUS_FX auto-start failed (normal en tests/CI): %s', exc)
