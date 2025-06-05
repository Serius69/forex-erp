import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('core')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Configurar tareas programadas
app.conf.beat_schedule = {
    'update-exchange-rates': {
        'task': 'rates.tasks.update_exchange_rates',
        'schedule': crontab(minute='*/30'),  # Cada 30 minutos
    },
    'train-prediction-models': {
        'task': 'predictions.tasks.train_prediction_models',
        'schedule': crontab(hour=2, minute=0),  # 2 AM diario
    },
    'check-inventory-levels': {
        'task': 'inventory.tasks.check_inventory_levels',
        'schedule': crontab(minute='*/15'),  # Cada 15 minutos
    },
    'generate-daily-report': {
        'task': 'reports.tasks.generate_daily_report',
        'schedule': crontab(hour=23, minute=30),  # 11:30 PM
    },
    'backup-database': {
        'task': 'core.tasks.backup_database',
        'schedule': crontab(hour='*/6'),  # Cada 6 horas
    },
}