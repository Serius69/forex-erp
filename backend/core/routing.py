from django.urls import path
from rates.consumers import RateConsumer, RatesConsumer, AlertConsumer
from data_migration.consumers import MigrationConsumer
from tarjetas.consumers import TarjetasInventarioConsumer

# Path strips the leading '/' — Django Channels URLRouter receives scope['path']
# which starts with '/'. Using path() handles this correctly.
websocket_urlpatterns = [
    path('ws/rates/',      RateConsumer.as_asgi()),
    path('ws/rates-live/', RatesConsumer.as_asgi()),
    path('ws/alerts/',     AlertConsumer.as_asgi()),
    path('ws/migration/<uuid:migration_id>/', MigrationConsumer.as_asgi()),
    path('ws/tarjetas/inventario/', TarjetasInventarioConsumer.as_asgi()),
]
