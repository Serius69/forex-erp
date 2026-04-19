from django.urls import path
from rates.consumers import RateConsumer, AlertConsumer
from data_migration.consumers import MigrationConsumer

# Path strips the leading '/' — Django Channels URLRouter receives scope['path']
# which starts with '/'. Using path() handles this correctly.
websocket_urlpatterns = [
    path('ws/rates/',  RateConsumer.as_asgi()),
    path('ws/alerts/', AlertConsumer.as_asgi()),
    path('ws/migration/<uuid:migration_id>/', MigrationConsumer.as_asgi()),
]
