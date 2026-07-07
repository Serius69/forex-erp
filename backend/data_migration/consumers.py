# data_migration/consumers.py
"""
WebSocket consumer para progreso en tiempo real de migraciones.

El cliente se conecta a: ws://host/ws/migration/{migration_id}/
Recibe eventos: started, metadata, progress, validated, completed, failed, paused, resumed.
"""
from __future__ import annotations
import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)

GROUP_PREFIX = 'migration_'


class MigrationConsumer(AsyncWebsocketConsumer):
    """
    Consumer que envía actualizaciones de progreso de una migración específica.
    Cada migración tiene su propio grupo: migration_{uuid}.
    """

    async def connect(self):
        self.migration_id = self.scope['url_route']['kwargs']['migration_id']
        self.group_name   = f'{GROUP_PREFIX}{self.migration_id}'

        # Verificar que la migración existe
        exists = await self._migration_exists(self.migration_id)
        if not exists:
            logger.warning('MigrationConsumer: migration %s not found — closing', self.migration_id)
            await self.close(code=4004)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Enviar estado actual al conectar
        status = await self._get_migration_status(self.migration_id)
        await self.send(text_data=json.dumps({'type': 'current_status', **status}))

        logger.info('MigrationConsumer connected: migration=%s', self.migration_id)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info('MigrationConsumer disconnected: migration=%s code=%s', self.migration_id, close_code)

    async def receive(self, text_data):
        """El cliente puede enviar comandos: pause, resume."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        command = data.get('command')

        if command == 'pause':
            await self._pause_migration()
        elif command == 'resume':
            await self._resume_migration()
        elif command == 'status':
            status = await self._get_migration_status(self.migration_id)
            await self.send(text_data=json.dumps({'type': 'current_status', **status}))

    # ── Group message handlers ────────────────────────────────────────────────

    async def migration_event(self, event):
        """Reenvía cualquier evento del grupo al cliente WebSocket."""
        event_type = event.pop('type_label', event.get('event_type', 'event'))
        # Limpiar la key 'type' que channels usa internamente
        payload = {k: v for k, v in event.items() if k != 'type'}
        payload['type'] = event_type
        await self.send(text_data=json.dumps(payload))

    # ── DB helpers ────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _migration_exists(self, migration_id: str) -> bool:
        from data_migration.models import MigrationLog
        return MigrationLog.objects.filter(id=migration_id).exists()

    @database_sync_to_async
    def _get_migration_status(self, migration_id: str) -> dict:
        from data_migration.models import MigrationLog
        try:
            m = MigrationLog.objects.get(id=migration_id)
            return {
                'migration_id':   str(m.id),
                'name':           m.name,
                'status':         m.status,
                'total_rows':     m.total_rows,
                'processed_rows': m.processed_rows,
                'success_rows':   m.success_rows,
                'error_rows':     m.error_rows,
                'skipped_rows':   m.skipped_rows,
                'progress_pct':   m.progress_pct,
                'dry_run':        m.dry_run,
                'started_at':     m.started_at.isoformat() if m.started_at else None,
                'finished_at':    m.finished_at.isoformat() if m.finished_at else None,
            }
        except MigrationLog.DoesNotExist:
            return {'error': 'Migration not found'}

    @database_sync_to_async
    def _pause_migration(self) -> None:
        from data_migration.models import MigrationLog
        MigrationLog.objects.filter(
            id=self.migration_id,
            status=MigrationLog.STATUS_RUNNING,
        ).update(status=MigrationLog.STATUS_PAUSED)
        logger.info('Migration %s paused via WebSocket', self.migration_id)

    @database_sync_to_async
    def _resume_migration(self) -> None:
        from data_migration.models import MigrationLog
        from data_migration.tasks import start_migration

        updated = MigrationLog.objects.filter(
            id=self.migration_id,
            status=MigrationLog.STATUS_PAUSED,
        ).update(status=MigrationLog.STATUS_PENDING)

        if updated:
            start_migration.apply_async(args=[self.migration_id])
            logger.info('Migration %s resumed via WebSocket', self.migration_id)
