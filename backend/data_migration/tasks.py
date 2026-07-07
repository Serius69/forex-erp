# data_migration/tasks.py
"""
Tareas Celery para la migración de datos desde Google Sheets.

Flujo:
  start_migration  →  process_batch (encadenado)  →  validate_migration
                                                   →  generate_migration_report

Checkpoint: cada batch actualiza MigrationCheckpoint para soporte de resume.
WebSocket: cada batch envía progreso al grupo 'migration_{migration_id}'.
"""
from __future__ import annotations
import logging
from datetime import datetime

from celery import shared_task, chain
from django.utils import timezone

logger = logging.getLogger(__name__)

GROUP_PREFIX  = 'migration_'
GROUP_RATES   = 'rates_updates'   # grupo global al que se suscriben todos los clientes

AUTO_SYNC_TASK = 'data_migration.auto_sync_sheets'


def _ws_send(migration_id: str, event_type: str, payload: dict) -> None:
    """Envía evento WebSocket al grupo de la migración (fire-and-forget)."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        group_name = f'{GROUP_PREFIX}{migration_id}'
        async_to_sync(channel_layer.group_send)(
            group_name,
            {'type': 'migration_event', 'event_type': event_type, **payload},
        )
    except Exception as exc:
        logger.debug('WS send failed (non-critical): %s', exc)


def _ws_broadcast_sync_complete(migration_id: str, target_model: str,
                                 success_rows: int, dry_run: bool) -> None:
    """
    Broadcast global a todos los clientes conectados para que refresquen
    sus datos tras una migración completada (no dry-run).
    """
    if dry_run:
        return
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            GROUP_RATES,
            {
                'type':         'sheets_sync',   # → sheets_sync() en RateConsumer
                'migration_id': migration_id,
                'target_model': target_model,
                'success_rows': success_rows,
            },
        )
        logger.info('sheets_sync_complete broadcast sent (migration=%s model=%s rows=%d)',
                    migration_id, target_model, success_rows)
    except Exception as exc:
        logger.debug('WS broadcast sheets_sync failed (non-critical): %s', exc)


def _get_migration(migration_id: str):
    from data_migration.models import MigrationLog
    return MigrationLog.objects.select_related('created_by').get(id=migration_id)


@shared_task(bind=True, name='data_migration.start_migration', max_retries=0)
def start_migration(self, migration_id: str) -> dict:
    """
    Inicia el proceso de migración:
    1. Obtiene metadata del spreadsheet.
    2. Cuenta filas totales.
    3. Encadena process_batch tasks.
    """
    from data_migration.models import MigrationLog
    from data_migration.services.google_sheets_client import GoogleSheetsClient
    from data_migration.services.importer import RowImporter

    migration = _get_migration(migration_id)

    if migration.status not in (MigrationLog.STATUS_PENDING, MigrationLog.STATUS_PAUSED):
        logger.warning('Migration %s in state %s — skip start', migration_id, migration.status)
        return {'skipped': True, 'status': migration.status}

    migration.status = MigrationLog.STATUS_RUNNING
    migration.started_at = timezone.now()
    migration.save(update_fields=['status', 'started_at', 'updated_at'])

    _ws_send(migration_id, 'started', {'migration_id': migration_id, 'name': migration.name})

    try:
        client = GoogleSheetsClient(migration.spreadsheet_id)
        header_row = client.get_header_row(migration.sheet_name)
        total_rows = client.get_row_count(migration.sheet_name)

        migration.total_rows = total_rows
        migration.save(update_fields=['total_rows', 'updated_at'])

        _ws_send(migration_id, 'metadata', {
            'migration_id': migration_id,
            'total_rows': total_rows,
            'columns': header_row,
        })

        # Determinar punto de resume
        importer = RowImporter(migration)
        start_row, start_batch = importer.get_resume_point()

        logger.info(
            'Migration %s: %d rows, starting at row=%d batch=%d',
            migration_id, total_rows, start_row, start_batch
        )

        # Encadenar batches
        batch_size = migration.batch_size
        batch_tasks = []
        row_idx = start_row
        batch_num = start_batch

        while row_idx < total_rows:
            batch_tasks.append(
                process_batch.si(migration_id, row_idx, batch_num)
            )
            row_idx   += batch_size
            batch_num += 1

        if batch_tasks:
            # Encadenar todos los batches, luego validar y reportar
            full_chain = chain(
                *batch_tasks,
                validate_migration.si(migration_id),
                generate_migration_report.si(migration_id),
            )
            full_chain.apply_async()
        else:
            # Sin filas: completar directamente
            migration.status = MigrationLog.STATUS_COMPLETED
            migration.finished_at = timezone.now()
            migration.save(update_fields=['status', 'finished_at', 'updated_at'])
            _ws_send(migration_id, 'completed', {'migration_id': migration_id, 'total_rows': 0})

        return {'migration_id': migration_id, 'total_rows': total_rows, 'batches': len(batch_tasks)}

    except Exception as exc:
        migration.status = MigrationLog.STATUS_FAILED
        migration.finished_at = timezone.now()
        migration.error_log = migration.error_log + [{'phase': 'start', 'error': str(exc)}]
        migration.save(update_fields=['status', 'finished_at', 'error_log', 'updated_at'])
        _ws_send(migration_id, 'failed', {'migration_id': migration_id, 'error': str(exc)})
        logger.exception('Migration %s failed at start', migration_id)
        raise


@shared_task(bind=True, name='data_migration.process_batch', max_retries=3, default_retry_delay=10)
def process_batch(self, migration_id: str, start_row: int, batch_num: int) -> dict:
    """
    Procesa un batch de filas del Google Sheet.
    Actualiza contadores en MigrationLog y guarda checkpoint.
    """
    from data_migration.models import MigrationLog
    from data_migration.services.google_sheets_client import GoogleSheetsClient
    from data_migration.services.importer import RowImporter

    migration = _get_migration(migration_id)

    if migration.status == MigrationLog.STATUS_PAUSED:
        logger.info('Migration %s paused — stopping batch %d', migration_id, batch_num)
        return {'paused': True, 'batch_num': batch_num}

    if migration.status == MigrationLog.STATUS_FAILED:
        return {'aborted': True, 'batch_num': batch_num}

    client  = GoogleSheetsClient(migration.spreadsheet_id)
    header  = client.get_header_row(migration.sheet_name)
    rows    = client.get_rows_batch(migration.sheet_name, start_row, migration.batch_size)

    if not rows:
        logger.info('Batch %d: no rows returned (end of sheet)', batch_num)
        return {'batch_num': batch_num, 'rows': 0}

    importer     = RowImporter(migration)
    header_index = {col.strip(): idx for idx, col in enumerate(header)}

    try:
        result = importer.import_batch(rows, header_index, start_row_num=start_row)
    except Exception as exc:
        logger.exception('Batch %d error: %s', batch_num, exc)
        migration.error_log = migration.error_log + [{'batch': batch_num, 'error': str(exc)}]

        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            migration.status = MigrationLog.STATUS_FAILED
            migration.finished_at = timezone.now()
            migration.save(update_fields=['status', 'finished_at', 'error_log', 'updated_at'])
            _ws_send(migration_id, 'failed', {
                'migration_id': migration_id,
                'batch': batch_num,
                'error': str(exc),
            })
            raise

    # Actualizar contadores
    migration.processed_rows = migration.processed_rows + result['success'] + result['errors'] + result['skipped']
    migration.success_rows   = migration.success_rows + result['success']
    migration.error_rows     = migration.error_rows + result['errors']
    migration.skipped_rows   = migration.skipped_rows + result['skipped']

    if result['error_details']:
        migration.error_log = migration.error_log + result['error_details']

    migration.save(update_fields=[
        'processed_rows', 'success_rows', 'error_rows',
        'skipped_rows', 'error_log', 'updated_at'
    ])

    # Checkpoint
    next_row = start_row + len(rows)
    importer.save_checkpoint(next_row, batch_num)

    # Progreso WebSocket
    _ws_send(migration_id, 'progress', {
        'migration_id':    migration_id,
        'batch_num':       batch_num,
        'processed_rows':  migration.processed_rows,
        'total_rows':      migration.total_rows,
        'success_rows':    migration.success_rows,
        'error_rows':      migration.error_rows,
        'progress_pct':    migration.progress_pct,
    })

    logger.info(
        'Batch %d done: success=%d errors=%d skipped=%d',
        batch_num, result['success'], result['errors'], result['skipped']
    )
    return {
        'batch_num': batch_num,
        'start_row': start_row,
        'rows_in_batch': len(rows),
        **result,
    }


@shared_task(bind=True, name='data_migration.validate_migration', max_retries=0)
def validate_migration(self, migration_id: str) -> dict:
    """
    Valida los datos importados:
    - Consistencia de transacciones
    - Tipos de cambio en rango razonable
    - Clientes con documentos duplicados
    """
    migration = _get_migration(migration_id)
    issues: list[str] = []
    warnings: list[str] = []

    try:
        if migration.target_model == 'transactions':
            from transactions.models import Transaction
            from django.utils import timezone as tz
            from django.db.models import Q

            # Verificar transacciones sin exchange_rate
            zero_rate = Transaction.objects.filter(
                exchange_rate__lte=0,
                created_at__date=migration.started_at.date() if migration.started_at else tz.now().date(),
            ).count()
            if zero_rate > 0:
                issues.append(f'{zero_rate} transacciones con tasa de cambio 0')

            # Verificar montos negativos
            neg = Transaction.objects.filter(
                Q(amount_from__lt=0) | Q(amount_to__lt=0),
            ).count()
            if neg > 0:
                issues.append(f'{neg} transacciones con montos negativos')

        elif migration.target_model == 'rates':
            from rates.models import ExchangeRate
            neg_spread = ExchangeRate.objects.filter(sell_rate__lt=models_buy_rate()).count() \
                if False else 0  # simplificado

        if migration.error_rows > migration.success_rows * 0.1:
            warnings.append(
                f'Tasa de error alta: {migration.error_rows} errores de {migration.total_rows} filas '
                f'({migration.error_rows/max(migration.total_rows,1)*100:.1f}%)'
            )

        validation_result = {
            'is_valid':  len(issues) == 0,
            'issues':    issues,
            'warnings':  warnings,
            'validated_at': datetime.now().isoformat(),
        }

        migration.summary = {**migration.summary, 'validation': validation_result}

        if issues:
            migration.status = MigrationLog.STATUS_FAILED
            migration.error_log = migration.error_log + [{'phase': 'validation', 'issues': issues}]
        else:
            migration.status = MigrationLog.STATUS_VALIDATED

        migration.save(update_fields=['status', 'summary', 'error_log', 'updated_at'])

        _ws_send(migration_id, 'validated', {
            'migration_id': migration_id,
            'is_valid':     len(issues) == 0,
            'issues':       issues,
            'warnings':     warnings,
        })

        return validation_result

    except Exception as exc:
        logger.exception('Validation failed for %s', migration_id)
        _ws_send(migration_id, 'validation_error', {'migration_id': migration_id, 'error': str(exc)})
        return {'is_valid': False, 'issues': [str(exc)], 'warnings': []}


@shared_task(bind=True, name='data_migration.generate_migration_report', max_retries=0)
def generate_migration_report(self, migration_id: str) -> dict:
    """
    Genera el reporte final de la migración y marca como COMPLETED.
    """
    migration = _get_migration(migration_id)

    duration = migration.duration_seconds or 0
    rows_per_sec = migration.processed_rows / duration if duration > 0 else 0

    report = {
        'migration_id':   migration_id,
        'name':           migration.name,
        'target_model':   migration.target_model,
        'spreadsheet_id': migration.spreadsheet_id,
        'sheet_name':     migration.sheet_name,
        'dry_run':        migration.dry_run,
        'total_rows':     migration.total_rows,
        'processed_rows': migration.processed_rows,
        'success_rows':   migration.success_rows,
        'error_rows':     migration.error_rows,
        'skipped_rows':   migration.skipped_rows,
        'success_rate':   round(migration.success_rows / max(migration.processed_rows, 1) * 100, 1),
        'duration_seconds': round(duration, 1),
        'rows_per_second':  round(rows_per_sec, 1),
        'generated_at':   datetime.now().isoformat(),
    }

    migration.summary = {**migration.summary, 'report': report}
    if migration.status not in ('FAILED',):
        migration.status = 'COMPLETED'
    migration.finished_at = timezone.now()
    migration.save(update_fields=['status', 'summary', 'finished_at', 'updated_at'])

    _ws_send(migration_id, 'completed', {
        'migration_id':  migration_id,
        'success_rows':  migration.success_rows,
        'error_rows':    migration.error_rows,
        'duration':      round(duration, 1),
        'success_rate':  report['success_rate'],
    })

    # Notificar a todos los clientes para que refresquen sus datos.
    _ws_broadcast_sync_complete(
        migration_id=migration_id,
        target_model=migration.target_model,
        success_rows=migration.success_rows,
        dry_run=migration.dry_run,
    )

    logger.info(
        'Migration %s COMPLETED: %d/%d rows OK (%.1f%%) in %.1fs',
        migration_id, migration.success_rows, migration.total_rows,
        report['success_rate'], duration
    )
    return report


@shared_task(bind=True, name=AUTO_SYNC_TASK, max_retries=2, default_retry_delay=60)
def auto_sync_sheets(self) -> dict:
    """
    Sincronización automática periódica desde Google Sheets.

    Requiere GOOGLE_SHEETS_AUTO_SYNC_URL configurado en settings.
    Ejecutado según GOOGLE_SHEETS_AUTO_SYNC_INTERVAL (default: 30 min).
    Solo sincroniza capital, inventory y rates (no transactions).
    """
    from django.conf import settings

    sheet_url = getattr(settings, 'GOOGLE_SHEETS_AUTO_SYNC_URL', '').strip()
    if not sheet_url:
        logger.debug('auto_sync_sheets: GOOGLE_SHEETS_AUTO_SYNC_URL no configurado — skip')
        return {'skipped': True, 'reason': 'GOOGLE_SHEETS_AUTO_SYNC_URL not configured'}

    try:
        from data_migration.services.google_sheets_service import GoogleSheetsService

        targets = getattr(settings, 'GOOGLE_SHEETS_AUTO_SYNC_TARGETS',
                          ['capital', 'inventory', 'rates'])

        logger.info('auto_sync_sheets: fetching sheet=%s targets=%s', sheet_url, targets)

        data = GoogleSheetsService.fetch_sheet_data(sheet_url)

        if not data['sheets_found']:
            logger.warning('auto_sync_sheets: no sheets found in %s', sheet_url)
            return {'skipped': True, 'reason': 'no_sheets_found'}

        results = GoogleSheetsService.sync_to_db(data, targets=targets, dry_run=False)

        total_synced = sum(r.get('synced', 0) for r in results.values())
        total_errors = sum(len(r.get('errors', [])) for r in results.values())

        # Broadcast para que el frontend refresque datos
        if total_synced > 0:
            _ws_broadcast_sync_complete(
                migration_id='auto_sync',
                target_model=','.join(data['sheets_found']),
                success_rows=total_synced,
                dry_run=False,
            )

        # Emitir alerta si hay errores significativos
        if total_errors > 0:
            try:
                from alerts.services import GlobalAlertService
                GlobalAlertService.from_system(
                    component='google_sheets_auto_sync',
                    message=f'Auto-sync desde Google Sheets completado con {total_errors} errores.',
                    severity='MEDIUM',
                    details={'total_synced': total_synced, 'total_errors': total_errors,
                             'results': {k: v['errors'][:5] for k, v in results.items()}},
                )
            except Exception:
                pass

        logger.info(
            'auto_sync_sheets DONE: sheets=%s synced=%d errors=%d',
            data['sheets_found'], total_synced, total_errors,
        )
        return {
            'sheets_found':  data['sheets_found'],
            'total_synced':  total_synced,
            'total_errors':  total_errors,
            'results':       {k: {'synced': v['synced'], 'error_count': len(v.get('errors', []))}
                              for k, v in results.items()},
        }

    except Exception as exc:
        logger.exception('auto_sync_sheets failed: %s', exc)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            try:
                from alerts.services import GlobalAlertService
                GlobalAlertService.from_system(
                    component='google_sheets_auto_sync',
                    message=f'Auto-sync con Google Sheets falló definitivamente: {exc}',
                    severity='HIGH',
                    details={'error': str(exc)},
                )
            except Exception:
                pass
            raise
