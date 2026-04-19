# Migration: CapitalAnomalyLog — persistent anomaly detection registry.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0003_rename_analytics_exp_branch_ts_idx_analytics_e_branch__379a28_idx_and_more'),
        ('users', '0002_alter_branch_options_alter_user_options'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CapitalAnomalyLog',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name='ID',
                )),
                # Classification
                ('rule', models.CharField(
                    max_length=25,
                    choices=[
                        ('CAPITAL_DROP',       'Caída de capital'),
                        ('MISSING_CASH',       'Diferencia en caja'),
                        ('NEGATIVE_BALANCE',   'Saldo negativo'),
                        ('RATE_INVERTED',      'Spread invertido'),
                        ('RATE_STALE',         'Tasa desactualizada'),
                        ('RATE_BCB_DEVIATION', 'Desviación sobre BCB'),
                        ('SPREAD_BELOW_MIN',   'Spread insuficiente'),
                        ('EXPOSURE_HIGH',      'Concentración de riesgo'),
                    ],
                    db_index=True,
                )),
                ('severity', models.CharField(
                    max_length=8,
                    choices=[
                        ('INFO',     'Información'),
                        ('WARNING',  'Advertencia'),
                        ('CRITICAL', 'Crítico'),
                    ],
                    db_index=True,
                )),
                # Context
                ('currency', models.CharField(
                    max_length=5, blank=True,
                    help_text='Divisa involucrada (vacío si es de capital global)',
                )),
                ('description', models.TextField(
                    help_text='Mensaje legible para el operador',
                )),
                # Trigger values
                ('value', models.DecimalField(
                    max_digits=18, decimal_places=4,
                    help_text='Valor medido que cruzó el umbral',
                )),
                ('threshold', models.DecimalField(
                    max_digits=18, decimal_places=4,
                    help_text='Umbral que fue superado',
                )),
                ('details', models.JSONField(
                    default=dict,
                    help_text='Datos adicionales: snapshot anterior, tasas, etc.',
                )),
                # Lifecycle
                ('resolved',    models.BooleanField(default=False, db_index=True)),
                ('resolved_at', models.DateTimeField(null=True, blank=True)),
                ('created_at',  models.DateTimeField(auto_now_add=True, db_index=True)),
                # FKs
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.SET_NULL,
                    null=True, blank=True,
                    related_name='anomaly_logs',
                    to='users.branch',
                )),
                ('resolved_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.SET_NULL,
                    null=True, blank=True,
                    related_name='resolved_anomalies',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name':        'Anomalía Detectada',
                'verbose_name_plural': 'Anomalías Detectadas',
                'db_table':            'analytics_anomaly_log',
                'ordering':            ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='capitalanomalylog',
            index=models.Index(
                fields=['severity', '-created_at'],
                name='analytics_anomaly_severity_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='capitalanomalylog',
            index=models.Index(
                fields=['rule', '-created_at'],
                name='analytics_anomaly_rule_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='capitalanomalylog',
            index=models.Index(
                fields=['branch', '-created_at'],
                name='analytics_anomaly_branch_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='capitalanomalylog',
            index=models.Index(
                fields=['resolved', '-created_at'],
                name='analytics_anomaly_resolved_idx',
            ),
        ),
    ]
