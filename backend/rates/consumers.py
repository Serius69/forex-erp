import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.cache import cache

class RateConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = 'rates_updates'
        
        # Unirse al grupo
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Enviar tasas actuales al conectarse
        await self.send_current_rates()
    
    async def disconnect(self, close_code):
        # Salir del grupo
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        # Procesar mensajes del cliente si es necesario
        pass
    
    async def rates_update(self, event):
        """Envía actualización de tasas a WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'rates_update',
            'rates': event['rates'],
            'timestamp': event['timestamp']
        }))
    
    @database_sync_to_async
    def get_current_rates(self):
        """Obtiene tasas actuales de la base de datos"""
        from rates.services import RateService
        
        service = RateService()
        rates = {}
        
        for currency in ['USD', 'EUR', 'BRL', 'ARS']:
            rate_data = service.get_current_rates(currency)
            if rate_data:
                rates[currency] = rate_data
        
        return rates
    
    async def send_current_rates(self):
        """Envía tasas actuales al cliente"""
        rates = await self.get_current_rates()
        
        await self.send(text_data=json.dumps({
            'type': 'initial_rates',
            'rates': rates,
            'timestamp': datetime.now().isoformat()
        }))

class AlertConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        
        if self.user.is_anonymous:
            await self.close()
            return
        
        # Grupo basado en la sucursal del usuario
        if self.user.branch:
            self.room_group_name = f'alerts_branch_{self.user.branch.id}'
        else:
            self.room_group_name = 'alerts_all'
        
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def alert_message(self, event):
        """Envía alerta a WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'alert',
            'alert': event['alert']
        }))