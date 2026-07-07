# data_migration/views.py
"""
API ViewSet para gestión de migraciones de datos.

Endpoints:
  POST   /api/migration/start/              → Crear migración y encolar tarea
  GET    /api/migration/{id}/status/        → Estado actual
  POST   /api/migration/{id}/pause/         → Pausar migración en curso
  POST   /api/migration/{id}/resume/        → Reanudar migración pausada
  POST   /api/migration/suggest_mapping/    → Sugerir mapeo de columnas
  POST   /api/migration/validate_mapping/   → Validar mapeo antes de migrar
  GET    /api/migration/                    → Listar todas las migraciones
  GET    /api/migration/{id}/               → Detalle de migración
  DELETE /api/migration/{id}/               → Eliminar migración (solo PENDING/FAILED)
"""
from __future__ import annotations
import logging

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import MigrationLog, ColumnMapping
from .serializers import (
    MigrationLogSerializer,
    StartMigrationSerializer,
    SuggestMappingSerializer,
    ValidateMappingSerializer,
    ColumnMappingSerializer,
)

logger = logging.getLogger(__name__)


class MigrationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = MigrationLogSerializer

    def get_queryset(self):
        return MigrationLog.objects.prefetch_related('column_mappings').order_by('-created_at')

    def destroy(self, request, *args, **kwargs):
        migration = self.get_object()
        if migration.status not in (MigrationLog.STATUS_PENDING, MigrationLog.STATUS_FAILED):
            return Response(
                {'error': f'No se puede eliminar migración en estado {migration.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        migration.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── POST /api/migration/start/ ────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='start')
    def start(self, request):
        ser = StartMigrationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        migration = MigrationLog.objects.create(
            name           = data['name'],
            spreadsheet_id = data['spreadsheet_id'],
            sheet_name     = data['sheet_name'],
            target_model   = data['target_model'],
            dry_run        = data['dry_run'],
            skip_errors    = data['skip_errors'],
            batch_size     = data['batch_size'],
            created_by     = request.user,
            status         = MigrationLog.STATUS_PENDING,
        )

        # Guardar mappings si vienen
        mappings_data = data.get('column_mappings', [])
        for order, m in enumerate(mappings_data):
            ColumnMapping.objects.create(
                migration        = migration,
                sheet_column     = m['sheet_column'],
                model_field      = m.get('model_field', ''),
                transform        = m.get('transform', 'none'),
                is_required      = m.get('is_required', False),
                default_value    = m.get('default_value', ''),
                validation_regex = m.get('validation_regex', ''),
                order            = m.get('order', order),
            )

        # Encolar tarea
        from .tasks import start_migration
        start_migration.apply_async(args=[str(migration.id)])

        return Response(
            MigrationLogSerializer(migration).data,
            status=status.HTTP_201_CREATED,
        )

    # ── GET /api/migration/{id}/status/ ──────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='status')
    def migration_status(self, request, pk=None):
        migration = self.get_object()
        return Response(MigrationLogSerializer(migration).data)

    # ── POST /api/migration/{id}/pause/ ──────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='pause')
    def pause(self, request, pk=None):
        migration = self.get_object()
        if migration.status != MigrationLog.STATUS_RUNNING:
            return Response(
                {'error': f'No se puede pausar migración en estado {migration.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        migration.status = MigrationLog.STATUS_PAUSED
        migration.save(update_fields=['status', 'updated_at'])
        logger.info('Migration %s paused by user %s', migration.id, request.user)
        return Response({'status': 'paused', 'migration_id': str(migration.id)})

    # ── POST /api/migration/{id}/resume/ ─────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='resume')
    def resume(self, request, pk=None):
        migration = self.get_object()
        if migration.status != MigrationLog.STATUS_PAUSED:
            return Response(
                {'error': f'No se puede reanudar migración en estado {migration.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        migration.status = MigrationLog.STATUS_PENDING
        migration.save(update_fields=['status', 'updated_at'])

        from .tasks import start_migration
        start_migration.apply_async(args=[str(migration.id)])

        logger.info('Migration %s resumed by user %s', migration.id, request.user)
        return Response({'status': 'resumed', 'migration_id': str(migration.id)})

    # ── POST /api/migration/suggest_mapping/ ─────────────────────────────────

    @action(detail=False, methods=['post'], url_path='suggest_mapping')
    def suggest_mapping(self, request):
        ser = SuggestMappingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            from .services.google_sheets_client import GoogleSheetsClient
            from .services.intelligent_mapper import IntelligentMapper

            client    = GoogleSheetsClient(data['spreadsheet_id'])
            header    = client.get_header_row(data['sheet_name'])
            sample_rows = client.get_rows_batch(
                data['sheet_name'], start_row=0, batch_size=data['sample_rows']
            )

            mapper      = IntelligentMapper(data['target_model'])
            suggestions = mapper.suggest_mappings(header, sample_rows)
            completeness = mapper.validate_mapping_completeness(suggestions)

            return Response({
                'spreadsheet_id': data['spreadsheet_id'],
                'sheet_name':     data['sheet_name'],
                'target_model':   data['target_model'],
                'columns_found':  header,
                'suggestions':    suggestions,
                'completeness':   completeness,
            })

        except FileNotFoundError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception('suggest_mapping error')
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # ── POST /api/migration/validate_mapping/ ────────────────────────────────

    @action(detail=False, methods=['post'], url_path='validate_mapping')
    def validate_mapping(self, request):
        ser = ValidateMappingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            from .services.intelligent_mapper import IntelligentMapper
            mapper = IntelligentMapper(data['target_model'])
            result = mapper.validate_mapping_completeness(data['column_mappings'])
            return Response(result)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # ── GET /api/migration/{id}/errors/ ──────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='errors')
    def errors(self, request, pk=None):
        migration = self.get_object()
        page    = int(request.query_params.get('page', 1))
        per_page = int(request.query_params.get('per_page', 50))
        errors  = migration.error_log
        start   = (page - 1) * per_page
        return Response({
            'total':  len(errors),
            'page':   page,
            'errors': errors[start:start + per_page],
        })

    # ── GET /api/migration/sheets_info/ ──────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='sheets_info')
    def sheets_info(self, request):
        """
        Valida una URL/ID de Google Sheets y retorna metadata + hojas detectadas.
        Acepta: ?sheet_url=<url> ó ?spreadsheet_id=<id>
        """
        sheet_url      = request.query_params.get('sheet_url', '').strip()
        spreadsheet_id = request.query_params.get('spreadsheet_id', '').strip()

        if not sheet_url and not spreadsheet_id:
            return Response(
                {'error': 'Se requiere sheet_url o spreadsheet_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from .services.google_sheets_service import GoogleSheetsService
            url_or_id = sheet_url or spreadsheet_id
            result = GoogleSheetsService.validate_url(url_or_id)
            return Response(result)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except FileNotFoundError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception('sheets_info error')
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # ── POST /api/migration/quick_sync/ ──────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='quick_sync')
    def quick_sync(self, request):
        """
        Sincronización rápida desde Google Sheets a la DB.

        Body:
          sheet_url  str       — URL o ID del spreadsheet
          targets    list[str] — ['capital','inventory','rates'] (vacío = todos)
          dry_run    bool      — default false

        Para sheets grandes (> 500 filas) usar /api/migration/start/ (pipeline Celery).
        """
        sheet_url = (request.data.get('sheet_url') or '').strip()
        targets   = request.data.get('targets') or []
        dry_run   = bool(request.data.get('dry_run', False))

        if not sheet_url:
            return Response({'error': 'sheet_url es requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from .services.google_sheets_service import GoogleSheetsService

            # 1. Fetch datos del sheet
            data = GoogleSheetsService.fetch_sheet_data(sheet_url)

            if not data['sheets_found']:
                return Response({
                    'warning': 'No se encontraron hojas reconocidas (Capital, Inventario, Tasas).',
                    'available_sheets': data.get('title', ''),
                }, status=status.HTTP_200_OK)

            # 2. Sincronizar a DB
            sync_results = GoogleSheetsService.sync_to_db(
                data,
                targets=targets or None,
                dry_run=dry_run,
                user=request.user,
            )

            # 3. Broadcast WebSocket para refrescar frontend (solo si no es dry_run)
            if not dry_run:
                from .tasks import _ws_broadcast_sync_complete
                _ws_broadcast_sync_complete(
                    migration_id='quick_sync',
                    target_model=','.join(data['sheets_found']),
                    success_rows=sum(r.get('synced', 0) for r in sync_results.values()),
                    dry_run=False,
                )

            total_synced = sum(r.get('synced', 0) for r in sync_results.values())
            total_errors = sum(len(r.get('errors', [])) for r in sync_results.values())

            logger.info(
                'quick_sync user=%s dry_run=%s sheets=%s synced=%d errors=%d',
                request.user, dry_run, data['sheets_found'], total_synced, total_errors,
            )

            return Response({
                'spreadsheet_id': data['spreadsheet_id'],
                'title':          data['title'],
                'sheets_synced':  data['sheets_found'],
                'dry_run':        dry_run,
                'results':        sync_results,
                'total_synced':   total_synced,
                'total_errors':   total_errors,
                'status':         'ok' if total_errors == 0 else 'partial',
            })

        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except FileNotFoundError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception('quick_sync error')
            return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ── POST /api/migration/export_snapshot/ ─────────────────────────────────

    @action(detail=False, methods=['post'], url_path='export_snapshot')
    def export_snapshot(self, request):
        """
        Exporta el estado actual del sistema a la pestaña 'Kapitalya_Snapshot'
        del spreadsheet indicado.

        Body:
          sheet_url str — URL o ID del spreadsheet destino

        Requiere GOOGLE_SHEETS_WRITABLE=True en settings.
        """
        sheet_url = (request.data.get('sheet_url') or '').strip()
        if not sheet_url:
            return Response({'error': 'sheet_url es requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from .services.google_sheets_service import GoogleSheetsService
            result = GoogleSheetsService.push_snapshot(sheet_url)
            logger.info('export_snapshot user=%s spreadsheet=%s rows=%d',
                        request.user, result['spreadsheet_id'], result['rows_written'])
            return Response(result)

        except PermissionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except FileNotFoundError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception('export_snapshot error')
            return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
