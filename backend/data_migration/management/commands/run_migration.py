# data_migration/management/commands/run_migration.py
"""
Comando de gestión Django para ejecutar migraciones desde Google Sheets.

Uso:
  python manage.py run_migration \\
      --spreadsheet-id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms \\
      --sheet-name "Transacciones Enero" \\
      --target-model transactions \\
      --name "Importación Enero 2024"

Opciones:
  --dry-run          No persiste datos, solo simula
  --resume UUID      Reanuda migración existente pausada/fallida
  --suggest-mapping  Muestra sugerencia de mapeo sin migrar
  --batch-size N     Tamaño de batch (default: 100)
  --skip-errors      Continuar si hay errores de fila
  --sync             Ejecutar sincrónicamente (sin Celery)
"""
from __future__ import annotations
import json
import sys
import time

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Migra datos desde Google Sheets al modelo Django destino'

    def add_arguments(self, parser):
        # Requeridos (excepto con --resume o --list)
        parser.add_argument('--spreadsheet-id', type=str, dest='spreadsheet_id',
                            help='ID del Google Spreadsheet')
        parser.add_argument('--sheet-name', type=str, dest='sheet_name',
                            help='Nombre de la hoja (tab)')
        parser.add_argument('--target-model', type=str, dest='target_model',
                            choices=['transactions', 'rates', 'inventory',
                                     'customers', 'capital', 'users'],
                            help='Modelo Django destino')
        parser.add_argument('--name', type=str, default='',
                            help='Nombre descriptivo de la migración')

        # Opciones
        parser.add_argument('--dry-run', action='store_true', dest='dry_run',
                            help='Simular sin persistir datos')
        parser.add_argument('--skip-errors', action='store_true', dest='skip_errors',
                            help='Continuar en caso de error por fila')
        parser.add_argument('--batch-size', type=int, default=100, dest='batch_size',
                            help='Filas por batch (default: 100)')
        parser.add_argument('--sync', action='store_true',
                            help='Ejecutar sincrónicamente (bloquea hasta terminar)')

        # Modos especiales
        parser.add_argument('--resume', type=str, metavar='UUID',
                            help='Reanudar migración existente (UUID)')
        parser.add_argument('--suggest-mapping', action='store_true', dest='suggest_mapping',
                            help='Solo mostrar sugerencia de mapeo, sin migrar')
        parser.add_argument('--list', action='store_true',
                            help='Listar migraciones recientes')
        parser.add_argument('--status', type=str, metavar='UUID',
                            help='Ver estado de migración por UUID')
        parser.add_argument('--mapping-file', type=str, dest='mapping_file',
                            help='Archivo JSON con column_mappings predefinidos')
        parser.add_argument('--user', type=str, default='',
                            help='Username del creador (para auditoría)')

    def handle(self, *args, **options):
        # ── Modo --list ───────────────────────────────────────────────────────
        if options['list']:
            self._list_migrations()
            return

        # ── Modo --status ─────────────────────────────────────────────────────
        if options.get('status'):
            self._show_status(options['status'])
            return

        # ── Modo --resume ─────────────────────────────────────────────────────
        if options.get('resume'):
            self._resume_migration(options['resume'], options['sync'])
            return

        # ── Modo --suggest-mapping ────────────────────────────────────────────
        if options['suggest_mapping']:
            self._validate_required(options, ['spreadsheet_id', 'sheet_name', 'target_model'])
            self._suggest_mapping(options)
            return

        # ── Modo normal: nueva migración ──────────────────────────────────────
        self._validate_required(options, ['spreadsheet_id', 'sheet_name', 'target_model'])
        self._run_migration(options)

    # ── Submodos ──────────────────────────────────────────────────────────────

    def _validate_required(self, options, fields):
        for f in fields:
            if not options.get(f):
                raise CommandError(f'--{f.replace("_", "-")} es requerido para este modo')

    def _list_migrations(self):
        from data_migration.models import MigrationLog
        migrations = MigrationLog.objects.order_by('-created_at')[:20]
        if not migrations:
            self.stdout.write('No hay migraciones registradas.')
            return
        self.stdout.write(self.style.SUCCESS('\nÚltimas migraciones:'))
        self.stdout.write('-' * 80)
        for m in migrations:
            status_colored = {
                'COMPLETED':  self.style.SUCCESS,
                'FAILED':     self.style.ERROR,
                'RUNNING':    self.style.WARNING,
                'PAUSED':     self.style.WARNING,
            }.get(m.status, lambda x: x)
            self.stdout.write(
                f'{str(m.id)[:8]}...  '
                f'{m.name[:30]:<30}  '
                f'{m.target_model:<15}  '
                f'{status_colored(m.status):<12}  '
                f'{m.success_rows}/{m.total_rows} filas  '
                f'{m.created_at.strftime("%Y-%m-%d %H:%M")}'
            )

    def _show_status(self, migration_id: str):
        from data_migration.models import MigrationLog
        try:
            m = MigrationLog.objects.get(id=migration_id)
        except MigrationLog.DoesNotExist:
            raise CommandError(f'Migración {migration_id} no encontrada')

        self.stdout.write(self.style.SUCCESS(f'\nMigración: {m.name}'))
        self.stdout.write(f'  ID:           {m.id}')
        self.stdout.write(f'  Estado:       {m.status}')
        self.stdout.write(f'  Modelo:       {m.target_model}')
        self.stdout.write(f'  Sheet:        {m.sheet_name}')
        self.stdout.write(f'  Total:        {m.total_rows} filas')
        self.stdout.write(f'  Procesadas:   {m.processed_rows}')
        self.stdout.write(f'  Exitosas:     {m.success_rows}')
        self.stdout.write(f'  Errores:      {m.error_rows}')
        self.stdout.write(f'  Omitidas:     {m.skipped_rows}')
        self.stdout.write(f'  Progreso:     {m.progress_pct}%')
        if m.duration_seconds:
            self.stdout.write(f'  Duración:     {m.duration_seconds:.1f}s')
        if m.error_log:
            self.stdout.write(f'  Errores log:  {len(m.error_log)} entradas')

    def _suggest_mapping(self, options):
        from data_migration.services.google_sheets_client import GoogleSheetsClient
        from data_migration.services.intelligent_mapper import IntelligentMapper

        self.stdout.write(f'Conectando a Google Sheets: {options["spreadsheet_id"]}...')
        try:
            client  = GoogleSheetsClient(options['spreadsheet_id'])
            header  = client.get_header_row(options['sheet_name'])
            samples = client.get_rows_batch(options['sheet_name'], 0, 20)
        except Exception as exc:
            raise CommandError(f'Error al conectar con Google Sheets: {exc}')

        mapper      = IntelligentMapper(options['target_model'])
        suggestions = mapper.suggest_mappings(header, samples)
        completeness = mapper.validate_mapping_completeness(suggestions)

        self.stdout.write(self.style.SUCCESS(f'\nColumnas encontradas: {len(header)}'))
        self.stdout.write('-' * 70)
        self.stdout.write(f'{"Columna Sheet":<25} {"Campo Django":<25} {"Transform":<15} {"Confianza":>8}')
        self.stdout.write('-' * 70)

        for s in suggestions:
            confidence = s['confidence']
            style_fn = (self.style.SUCCESS if confidence > 0.8
                        else self.style.WARNING if confidence > 0.4
                        else self.style.ERROR)
            marker = '✓' if s['model_field'] else '?'
            self.stdout.write(
                f'{s["sheet_column"]:<25} '
                f'{style_fn(s["model_field"] or "-- sin mapeo --"):<25} '
                f'{s["transform"]:<15} '
                f'{confidence:>8.1%}'
            )

        self.stdout.write('-' * 70)
        if completeness['is_complete']:
            self.stdout.write(self.style.SUCCESS('✓ Mapeo completo — todos los campos requeridos cubiertos'))
        else:
            self.stdout.write(self.style.ERROR(
                f'✗ Faltan campos requeridos: {", ".join(completeness["missing_required"])}'
            ))

        # Exportar JSON para usar con --mapping-file
        mappings_json = [
            {'sheet_column': s['sheet_column'], 'model_field': s['model_field'],
             'transform': s['transform'], 'is_required': s['is_required'], 'order': i}
            for i, s in enumerate(suggestions) if s['model_field']
        ]
        self.stdout.write(f'\nJSON para --mapping-file:\n{json.dumps(mappings_json, indent=2, ensure_ascii=False)}')

    def _resume_migration(self, migration_id: str, sync: bool):
        from data_migration.models import MigrationLog
        from data_migration.tasks import start_migration

        try:
            migration = MigrationLog.objects.get(id=migration_id)
        except MigrationLog.DoesNotExist:
            raise CommandError(f'Migración {migration_id} no encontrada')

        if migration.status not in (MigrationLog.STATUS_PAUSED, MigrationLog.STATUS_FAILED):
            raise CommandError(
                f'Solo se pueden reanudar migraciones PAUSED o FAILED. '
                f'Estado actual: {migration.status}'
            )

        migration.status = MigrationLog.STATUS_PENDING
        migration.save(update_fields=['status', 'updated_at'])

        self.stdout.write(f'Reanudando migración: {migration.name}')
        if sync:
            start_migration(str(migration.id))
            self._poll_status(migration)
        else:
            start_migration.apply_async(args=[str(migration.id)])
            self.stdout.write(self.style.SUCCESS(f'Tarea encolada. UUID: {migration.id}'))

    def _run_migration(self, options):
        from data_migration.models import MigrationLog, ColumnMapping
        from data_migration.tasks import start_migration

        # Obtener/crear usuario
        user = None
        if options.get('user'):
            try:
                user = User.objects.get(username=options['user'])
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'Usuario {options["user"]} no encontrado — sin auditoría'))

        name = options['name'] or f'CLI: {options["sheet_name"]} → {options["target_model"]}'

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('[DRY RUN] No se persistirán datos'))

        migration = MigrationLog.objects.create(
            name           = name,
            spreadsheet_id = options['spreadsheet_id'],
            sheet_name     = options['sheet_name'],
            target_model   = options['target_model'],
            dry_run        = options['dry_run'],
            skip_errors    = options['skip_errors'],
            batch_size     = options['batch_size'],
            created_by     = user,
            status         = MigrationLog.STATUS_PENDING,
        )

        # Cargar mappings desde archivo
        if options.get('mapping_file'):
            try:
                with open(options['mapping_file']) as f:
                    mappings_data = json.load(f)
                for order, m in enumerate(mappings_data):
                    ColumnMapping.objects.create(
                        migration    = migration,
                        sheet_column = m['sheet_column'],
                        model_field  = m.get('model_field', ''),
                        transform    = m.get('transform', 'none'),
                        is_required  = m.get('is_required', False),
                        default_value = m.get('default_value', ''),
                        order        = m.get('order', order),
                    )
                self.stdout.write(f'Mappings cargados desde {options["mapping_file"]}: {len(mappings_data)}')
            except Exception as exc:
                raise CommandError(f'Error al leer --mapping-file: {exc}')

        self.stdout.write(f'Migración creada: {migration.id}')
        self.stdout.write(f'  Nombre:  {name}')
        self.stdout.write(f'  Sheet:   {options["sheet_name"]}')
        self.stdout.write(f'  Modelo:  {options["target_model"]}')
        self.stdout.write(f'  Batch:   {options["batch_size"]}')

        if options['sync']:
            self.stdout.write('Ejecutando sincrónicamente...')
            start_migration(str(migration.id))
            self._poll_status(migration)
        else:
            start_migration.apply_async(args=[str(migration.id)])
            self.stdout.write(self.style.SUCCESS(
                f'\nTarea encolada. Monitorear con:\n'
                f'  python manage.py run_migration --status {migration.id}'
            ))

    def _poll_status(self, migration):
        """Muestra barra de progreso mientras la tarea corre (modo --sync)."""
        from data_migration.models import MigrationLog
        import sys

        self.stdout.write('Progreso:')
        while True:
            migration.refresh_from_db()
            pct  = migration.progress_pct
            bar  = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
            sys.stdout.write(f'\r  [{bar}] {pct:5.1f}%  {migration.processed_rows}/{migration.total_rows}  ')
            sys.stdout.flush()

            if migration.status in ('COMPLETED', 'VALIDATED', 'FAILED'):
                break
            time.sleep(2)

        sys.stdout.write('\n')
        if migration.status in ('COMPLETED', 'VALIDATED'):
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ Migración completada: {migration.success_rows} filas exitosas, '
                f'{migration.error_rows} errores, {migration.skipped_rows} omitidas'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'\n✗ Migración FALLIDA. Revisa errors con:\n'
                f'  python manage.py run_migration --status {migration.id}'
            ))
