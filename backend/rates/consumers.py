"""
WebSocket consumers para Kapitalya.

RateConsumer  — /ws/rates/
  · Autenticación JWT via ?token=<access_token>
  · Emite tasas actuales al conectar
  · Recibe broadcast del grupo 'rates_updates' cuando las tasas cambian
  · Broadcast se origina en: ExchangeRate post_save signal y Celery tasks

AlertConsumer — /ws/alerts/
  · Autenticación por scope['user'] (ya poblado por JWTAuthMiddleware)
  · Recibe alertas por sucursal
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

log = logging.getLogger('kapitalya.ws')

GROUP_RATES   = 'rates_updates'
GROUP_CAPITAL = 'capital_updates'


class RateConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        # JWTAuthMiddlewareStack already populated scope['user']
        user = self.scope.get('user')
        if user is None or not getattr(user, 'is_authenticated', False):
            log.warning('WS_RATES_REJECT anonymous connection from %s', self.scope.get('client'))
            await self.close(code=4001)
            return

        self.user = user
        await self.channel_layer.group_add(GROUP_RATES,   self.channel_name)
        await self.channel_layer.group_add(GROUP_CAPITAL, self.channel_name)
        await self.accept()
        log.info('WS_RATES_CONNECT user=%s channel=%s', user.username, self.channel_name)

        # Send current rates immediately on connect
        rates = await self._get_current_rates()
        await self.send(text_data=json.dumps({
            'type':  'rates_update',
            'rates': rates,
        }))

        # Send active system alerts
        alerts = await self._get_active_alerts()
        if alerts:
            await self.send(text_data=json.dumps({
                'type':   'system_alerts',
                'alerts': alerts,
            }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP_RATES,   self.channel_name)
        await self.channel_layer.group_discard(GROUP_CAPITAL, self.channel_name)
        log.info('WS_RATES_DISCONNECT channel=%s code=%s', self.channel_name, close_code)

    async def receive(self, text_data):
        """Client → server: ping / request_rates."""
        try:
            msg = json.loads(text_data)
        except json.JSONDecodeError:
            return

        if msg.get('type') == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))
        elif msg.get('type') == 'request_rates':
            rates = await self._get_current_rates()
            await self.send(text_data=json.dumps({'type': 'rates_update', 'rates': rates}))

    # ── Group message handlers (invoked by channel layer broadcasts) ──────────

    async def rates_update(self, event):
        """Reenvía broadcast de tasas al cliente WebSocket."""
        await self.send(text_data=json.dumps({
            'type':  'rates_update',
            'rates': event.get('rates', {}),
        }))

    async def rate_update(self, event):
        """Alias legacy — reenvía al handler principal."""
        await self.rates_update(event)

    async def system_alert(self, event):
        await self.send(text_data=json.dumps({
            'type':  'alert',
            'alert': event.get('alert', {}),
        }))

    async def capital_update(self, event):
        """Reenvía evento capital_updated al cliente WebSocket."""
        await self.send(text_data=json.dumps({
            'type':      'capital_updated',
            'branch_id': event.get('branch_id'),
        }))

    async def sheets_sync(self, event):
        """Reenvía evento sheets_sync_complete al cliente WebSocket."""
        await self.send(text_data=json.dumps({
            'type':         'sheets_sync_complete',
            'migration_id': event.get('migration_id'),
            'target_model': event.get('target_model'),
            'success_rows': event.get('success_rows'),
        }))

    async def alert_log(self, event):
        """
        Reenvía una alerta persistida (AlertLog) al cliente WebSocket.
        Emitido por GlobalAlertService._push_websocket().
        """
        await self.send(text_data=json.dumps({
            'type':  'alert_log',
            'alert': event.get('alert', {}),
        }))

    # ── DB helpers ────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _get_current_rates(self) -> dict:
        """Tasas activas (valid_until IS NULL) indexadas por código de divisa."""
        try:
            from .models import ExchangeRate, Currency
            bob = Currency.objects.filter(code='BOB').first()
            if not bob:
                return {}
            rates: dict = {}
            qs = (
                ExchangeRate.objects
                .filter(currency_to=bob, valid_until__isnull=True)
                .select_related('currency_from')
                .order_by('currency_from__code', 'market_type')
            )
            for r in qs:
                code = r.currency_from.code
                mtype = r.market_type
                key = f'{code}_{mtype}' if mtype != 'parallel' else code
                rates[key] = {
                    'code':         code,
                    'name':         r.currency_from.name,
                    'scale_factor': r.currency_from.scale_factor,
                    'market_type':  mtype,
                    'buy':          float(r.buy_rate),
                    'sell':         float(r.sell_rate),
                    'official':     float(r.official_rate),
                }
            return rates
        except Exception as exc:
            log.error('WS_GET_RATES_ERROR %s', exc)
            return {}

    @database_sync_to_async
    def _get_active_alerts(self) -> list:
        try:
            from core.alerts import SystemAlert
            return SystemAlert.get_active(limit=5)
        except Exception:
            return []


class AlertConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not getattr(user, 'is_authenticated', False):
            await self.close(code=4001)
            return

        self.user = user
        branch = getattr(user, 'branch', None)
        self.group_name = f'alerts_branch_{branch.id}' if branch else 'alerts_all'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def alert_message(self, event):
        await self.send(text_data=json.dumps({
            'type':  'alert',
            'alert': event['alert'],
        }))
