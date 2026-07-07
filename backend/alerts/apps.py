from django.apps import AppConfig


class AlertsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'alerts'
    label = 'alerts'
    verbose_name = 'Sistema de Alertas'

    def ready(self):
        import alerts.signals  # noqa — registers post_save WebSocket broadcast
