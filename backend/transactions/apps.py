from django.apps import AppConfig


class TransactionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'transactions'

    def ready(self):
        # Registrar señales de transacciones — importar para que los
        # @receiver decoradores queden activos durante toda la vida del proceso.
        import transactions.signals  # noqa: F401
