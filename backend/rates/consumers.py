import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.cache import cache

class RateConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add('rates', self.channel_name)
        await self.accept()
        # Enviar tasas actuales al conectar
        rates = await self.get_current_rates()
        await self.send(json.dumps({
            'type': 'rates_update',
            'rates': rates,
        }))
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard('rates', self.channel_name)
    
    async def receive(self, text_data):
        pass  # El cliente no envía datos en este canal
    
    async def rates_update(self, event):
        """Recibe broadcast del grupo y lo envía al cliente."""
        await self.send(json.dumps({
            'type':  'rates_update',
            'rates': event.get('rates', {}),
        }))
    
    @database_sync_to_async
    def get_current_rates(self):
        try:
            from .models import ExchangeRate, Currency
            bob   = Currency.objects.get(code='BOB')
            rates = {}
            for r in (ExchangeRate.objects
                      .filter(currency_to=bob, valid_until__isnull=True)
                      .select_related('currency_from')):
                rates[r.currency_from.code] = {
                    'buy':      float(r.buy_rate),
                    'sell':     float(r.sell_rate),
                    'official': float(r.official_rate),
                }
            return rates
        except Exception:
            return {}
    
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