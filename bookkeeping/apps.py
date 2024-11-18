from django.apps import AppConfig

class BookkeepingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bookkeeping'

    def ready(self):
        import bookkeeping.signals  # Import signals
