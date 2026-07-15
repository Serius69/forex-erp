# tarjetas/consumers.py
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

log = logging.getLogger('tarjetas')


class TarjetasInventarioConsumer(AsyncWebsocketConsumer):
    """
    WebSocket en tiempo real para el inventario de tarjetas telefónicas.

    Ruta: ws://<host>/ws/tarjetas/inventario/

    Al conectar: envía un snapshot del inventario DE LA EMPRESA del usuario.
    Al publicar (group_send type=inventario_update): reenvía a los clientes
    del grupo de esa empresa (aislamiento multi-tenant).
    """

    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        from .services import ws_group_inventario
        self.ws_group = ws_group_inventario(getattr(user, 'company_id', None))
        await self.channel_layer.group_add(self.ws_group, self.channel_name)
        await self.accept()

        snapshot = await self._get_snapshot()
        await self.send(text_data=json.dumps({
            'type': 'inventario_snapshot',
            'data': snapshot,
        }))
        log.debug('WS tarjetas connect user=%s', self.scope['user'])

    async def disconnect(self, close_code):
        if hasattr(self, 'ws_group'):
            await self.channel_layer.group_discard(self.ws_group, self.channel_name)

    # Recibe mensajes del cliente (no requerido, pero aceptamos ping)
    async def receive(self, text_data=None, bytes_data=None):
        try:
            msg = json.loads(text_data or '{}')
        except json.JSONDecodeError:
            return
        if msg.get('type') == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))
        elif msg.get('type') == 'request_snapshot':
            snapshot = await self._get_snapshot()
            await self.send(text_data=json.dumps({
                'type': 'inventario_snapshot',
                'data': snapshot,
            }))

    # Handler para mensajes del grupo (enviados por TarjetaService)
    async def inventario_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'inventario_update',
            'data': event['data'],
        }))

    @database_sync_to_async
    def _get_snapshot(self):
        from .services import TarjetaService
        company_id = getattr(self.scope.get('user'), 'company_id', None)
        return TarjetaService.get_posicion_inventario(company_id=company_id)
