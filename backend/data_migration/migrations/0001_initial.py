# data_migration/migrations/0001_initial.py
import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MigrationLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(help_text='Nombre descriptivo de la migración', max_length=200)),
                ('spreadsheet_id', models.CharField(help_text='ID del Google Spreadsheet', max_length=200)),
                ('sheet_name', models.CharField(help_text='Nombre de la hoja (tab)', max_length=200)),
                ('target_model', models.CharField(
                    choices=[
                        ('transactions', 'Transacciones'), ('rates', 'Tasas de cambio'),
                        ('inventory', 'Inventario'), ('customers', 'Clientes'),
                        ('capital', 'Capital / Gastos'), ('users', 'Usuarios'),
                    ],
                    db_index=True, max_length=50,
                )),
                ('status', models.CharField(
                    choices=[
                        ('PENDING', 'Pendiente'), ('RUNNING', 'Ejecutando'),
                        ('PAUSED', 'Pausado'), ('COMPLETED', 'Completado'),
                        ('FAILED', 'Fallido'), ('VALIDATED', 'Validado'),
                    ],
                    db_index=True, default='PENDING', max_length=20,
                )),
                ('total_rows', models.IntegerField(default=0)),
                ('processed_rows', models.IntegerField(default=0)),
                ('success_rows', models.IntegerField(default=0)),
                ('error_rows', models.IntegerField(default=0)),
                ('skipped_rows', models.IntegerField(default=0)),
                ('dry_run', models.BooleanField(default=False, help_text='Si True, no persiste cambios')),
                ('skip_errors', models.BooleanField(default=False, help_text='Continuar si hay errores de fila')),
                ('batch_size', models.IntegerField(default=100)),
                ('error_log', models.JSONField(blank=True, default=list)),
                ('summary', models.JSONField(blank=True, default=dict)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='migrations_created',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Log de migración',
                'verbose_name_plural': 'Logs de migración',
                'db_table': 'data_migration_log',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MigrationCheckpoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('last_row_index', models.IntegerField(
                    default=0, help_text='Índice de la última fila procesada (0-based)'
                )),
                ('last_batch_num', models.IntegerField(default=0)),
                ('state_snapshot', models.JSONField(
                    blank=True, default=dict,
                    help_text='Estado intermedio (WAC, saldos, etc.)',
                )),
                ('saved_at', models.DateTimeField(auto_now=True)),
                ('migration', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='checkpoint',
                    to='data_migration.migrationlog',
                )),
            ],
            options={
                'verbose_name': 'Checkpoint de migración',
                'verbose_name_plural': 'Checkpoints de migración',
                'db_table': 'data_migration_checkpoint',
            },
        ),
        migrations.CreateModel(
            name='ColumnMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sheet_column', models.CharField(help_text='Nombre de columna en el sheet', max_length=100)),
                ('model_field', models.CharField(help_text='Nombre del campo en el modelo Django', max_length=100)),
                ('transform', models.CharField(
                    choices=[
                        ('none', 'Sin transformación'), ('upper', 'MAYÚSCULAS'),
                        ('lower', 'minúsculas'), ('strip', 'Quitar espacios'),
                        ('date_bo', 'Fecha formato boliviano (dd/mm/yyyy)'),
                        ('date_iso', 'Fecha ISO (yyyy-mm-dd)'),
                        ('decimal', 'Decimal (coma → punto)'),
                        ('boolean', 'Booleano (si/no, 1/0, true/false)'),
                        ('currency_code', 'Código de moneda (normalizar a USD/EUR/etc.)'),
                        ('lookup_branch', 'Buscar sucursal por nombre'),
                        ('lookup_user', 'Buscar usuario por username'),
                    ],
                    default='none', max_length=20,
                )),
                ('is_required', models.BooleanField(default=False)),
                ('default_value', models.CharField(
                    blank=True, help_text='Valor por defecto si la celda está vacía', max_length=200,
                )),
                ('validation_regex', models.CharField(
                    blank=True, help_text='Regex de validación (opcional)', max_length=300,
                )),
                ('order', models.PositiveSmallIntegerField(default=0, help_text='Orden de procesamiento')),
                ('migration', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='column_mappings',
                    to='data_migration.migrationlog',
                )),
            ],
            options={
                'verbose_name': 'Mapeo de columna',
                'verbose_name_plural': 'Mapeos de columnas',
                'db_table': 'data_migration_column_mapping',
                'ordering': ['order', 'sheet_column'],
                'unique_together': {('migration', 'sheet_column')},
            },
        ),
    ]
