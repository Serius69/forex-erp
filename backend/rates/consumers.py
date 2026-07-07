"""
WebSocket consumers para Kapitalya.

RateConsumer  — /ws/rates/
  · Autenticación JWT via ?token=<access_token>
  · Emite tasas actuales al conectar
  · Recibe broadcast del grupo 'rates_updates' cuando las tasas cambian
  · Broadcast se origina en: ExchangeRate post_save signal y Celery tasks
  · Rooms multi-tenant: company_{id} y branch_{id}

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
GROUP_RATES_LIVE = 'rates_live'


class RateConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        # JWTAuthMiddlewareStack already populated scope['user']
        user = self.scope.get('user')
        if user is None or not getattr(user, 'is_authenticated', False):
            log.warning('WS_RATES_REJECT anonymous connection from %s', self.scope.get('client'))
            await self.close(code=4001)
            return

        self.user = user
        # accept() primero para completar el handshake ASGI inmediatamente.
        # Hacer I/O (Redis group_add) antes de accept() puede causar 1001
        # si el cliente agota el handshake timeout.
        await self.accept()
        log.info('WS_RATES_CONNECT user=%s channel=%s', user.username, self.channel_name)

        try:
            await self.channel_layer.group_add(GROUP_RATES,   self.channel_name)
            await self.channel_layer.group_add(GROUP_CAPITAL, self.channel_name)

            # Multi-tenant: unirse a rooms de empresa y sucursal
            company_id = getattr(getattr(user, 'company', None), 'id', None)
            branch_id  = getattr(getattr(user, 'branch',  None), 'id', None)
            if company_id:
                await self.channel_layer.group_add(f'company_{company_id}', self.channel_name)
            if branch_id:
                await self.channel_layer.group_add(f'branch_{branch_id}', self.channel_name)

            self._company_id = company_id
            self._branch_id  = branch_id
        except Exception as exc:
            log.error('WS_RATES_GROUP_ADD_FAIL channel=%s error=%s', self.channel_name, exc)

        # Send current rates immediately on connect
        try:
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
        except Exception as exc:
            log.error('WS_RATES_INIT_FAIL channel=%s error=%s', self.channel_name, exc)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP_RATES,   self.channel_name)
        await self.channel_layer.group_discard(GROUP_CAPITAL, self.channel_name)
        company_id = getattr(self, '_company_id', None)
        branch_id  = getattr(self, '_branch_id',  None)
        if company_id:
            await self.channel_layer.group_discard(f'company_{company_id}', self.channel_name)
        if branch_id:
            await self.channel_layer.group_discard(f'branch_{branch_id}', self.channel_name)
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
        """Reenvía una alerta persistida (AlertLog) al cliente WebSocket."""
        await self.send(text_data=json.dumps({
            'type':       'alert_log',
            'event_type': event.get('event_type', 'ALERT_TRIGGERED'),
            'alert':      event.get('alert', {}),
        }))

    async def transaction_event(self, event):
        """Reenvía eventos de transacciones (creación o cambio de estado)."""
        await self.send(text_data=json.dumps({
            'type':       'transaction_event',
            'event_type': event.get('event_type', 'TRANSACTION_CREATED'),
            'data':       {k: v for k, v in event.items() if k not in ('type', 'event_type')},
        }))

    async def inventory_update(self, event):
        """Reenvía cambios de inventario al cliente."""
        await self.send(text_data=json.dumps({
            'type':       'inventory_update',
            'event_type': event.get('event_type', 'INVENTORY_UPDATED'),
            'data':       {k: v for k, v in event.items() if k not in ('type', 'event_type')},
        }))

    async def kpi_update(self, event):
        """Reenvía actualizaciones de KPIs."""
        await self.send(text_data=json.dumps({
            'type':       'kpi_update',
            'event_type': event.get('event_type', 'KPI_UPDATED'),
            'data':       {k: v for k, v in event.items() if k not in ('type', 'event_type')},
        }))

    async def extraction_update(self, event):
        """Reenvía estado del ciclo de extracción continua."""
        await self.send(text_data=json.dumps({
            'type': 'extraction_update',
            'data': {k: v for k, v in event.items() if k not in ('type',)},
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


class RatesConsumer(AsyncWebsocketConsumer):
    """
    /ws/rates-live/
    Consumer para el feed de consenso en tiempo real.

    Al conectarse: envía inmediatamente el último consenso de todos los pares.
    Broadcast: cada vez que calculate_consensus termina publica al group 'rates_live'.

    Autenticación: JWT via ?token= (igual que RateConsumer).
    Formato saliente:
    {
      "type": "rates_update",
      "timestamp": "…",
      "pares": {
        "USD/BOB": {"consenso": 9.82, "compra": …, "cambio_pct": 0.51, "tendencia": "ALCISTA"},
        …
      }
    }
    """

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not getattr(user, 'is_authenticated', False):
            log.warning('WS_RATES_LIVE_REJECT anonymous %s', self.scope.get('client'))
            await self.close(code=4001)
            return

        self.user = user
        await self.channel_layer.group_add(GROUP_RATES_LIVE, self.channel_name)
        await self.accept()
        log.info('WS_RATES_LIVE_CONNECT user=%s', user.username)

        # Enviar consenso actual inmediatamente
        snapshot = await self._get_consensus_snapshot()
        await self.send(text_data=json.dumps({
            'type':      'rates_update',
            'timestamp': snapshot['timestamp'],
            'pares':     snapshot['pares'],
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP_RATES_LIVE, self.channel_name)
        log.info('WS_RATES_LIVE_DISCONNECT code=%s', close_code)

    async def receive(self, text_data):
        try:
            msg = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if msg.get('type') == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))
        elif msg.get('type') == 'request_consensus':
            snapshot = await self._get_consensus_snapshot()
            await self.send(text_data=json.dumps({
                'type':      'rates_update',
                'timestamp': snapshot['timestamp'],
                'pares':     snapshot['pares'],
            }))

    async def rates_update(self, event):
        """Handler del broadcast de consensus task → clientes WS."""
        await self.send(text_data=json.dumps({
            'type':      'rates_update',
            'timestamp': event.get('timestamp', ''),
            'pares':     event.get('pares', {}),
        }))

    @database_sync_to_async
    def _get_consensus_snapshot(self) -> dict:
        """Carga el consenso vigente de todos los pares desde DB."""
        try:
            from .models import ExchangeRateConsensus
            from django.utils import timezone
            vigentes = ExchangeRateConsensus.objects.filter(vigente=True).order_by('par')
            pares = {}
            for c in vigentes:
                pares[c.par] = {
                    'consenso':      float(c.precio_consenso),
                    'compra':        float(c.precio_compra)    if c.precio_compra  else None,
                    'venta':         float(c.precio_venta)     if c.precio_venta   else None,
                    'fuentes':       c.fuentes_count,
                    'confianza':     c.confianza_pct,
                    'cambio_pct':    float(c.cambio_pct_24h)   if c.cambio_pct_24h else 0.0,
                    'tendencia':     c.tendencia or 'NEUTRAL',
                }
            return {'timestamp': timezone.now().isoformat(), 'pares': pares}
        except Exception as exc:
            log.error('WS_RATES_LIVE_SNAPSHOT_ERROR %s', exc)
            return {'timestamp': '', 'pares': {}}


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
