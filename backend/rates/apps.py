from django.apps import AppConfig


class RatesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rates'

    def ready(self):
        import rates.signals  # noqa — registers post_save for ExchangeRate
