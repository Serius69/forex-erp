import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('users', '0004_remove_auditlog_audit_ct_obj_ts_idx_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AlertLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source', models.CharField(
                    choices=[
                        ('SNAPSHOT',    'Comparación de Snapshot'),
                        ('TRANSACTION', 'Transacción Forex'),
                        ('ANOMALY',     'Detector de Anomalías'),
                        ('SYSTEM',      'Infraestructura del Sistema'),
                        ('INVENTORY',   'Inventario'),
                        ('RATES',       'Tasas de Cambio'),
                    ],
                    db_index=True, max_length=20,
                )),
                ('alert_type', models.CharField(db_index=True, max_length=60)),
                ('severity', models.CharField(
                    choices=[
                        ('CRITICAL', 'Crítica'),
                        ('HIGH',     'Alta'),
                        ('MEDIUM',   'Media'),
                        ('LOW',      'Baja'),
                    ],
                    db_index=True, max_length=10,
                )),
                ('title',   models.CharField(max_length=200)),
                ('message', models.TextField()),
                ('data',    models.JSONField(blank=True, default=dict)),
                ('is_acknowledged', models.BooleanField(default=False, db_index=True)),
                ('acknowledged_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='alert_logs',
                    to='users.branch',
                )),
                ('triggered_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='triggered_alerts',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('acknowledged_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='acknowledged_alerts',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name':        'Alerta',
                'verbose_name_plural': 'Alertas',
                'db_table':            'alerts_log',
                'ordering':            ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='alertlog',
            index=models.Index(
                fields=['is_acknowledged', '-created_at'],
                name='alerts_unack_recent_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='alertlog',
            index=models.Index(
                fields=['severity', '-created_at'],
                name='alerts_severity_recent_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='alertlog',
            index=models.Index(
                fields=['source', '-created_at'],
                name='alerts_source_recent_idx',
            ),
        ),
    ]
