from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0013_add_fraud_and_rate_lock_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TransactionAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('transaction', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='audit_logs',
                    to='transactions.transaction',
                )),
                ('transaction_number', models.CharField(max_length=20, db_index=True)),
                ('action', models.CharField(
                    max_length=30,
                    choices=[
                        ('CREATED',          'Transacción creada'),
                        ('STATUS_CHANGED',   'Estado modificado'),
                        ('APPROVED',         'Aprobada por supervisor'),
                        ('REVERSED',         'Revertida'),
                        ('CANCELLED',        'Cancelada'),
                        ('RATE_LOCKED',      'Tasa bloqueada'),
                        ('RATE_EXPIRED',     'Bloqueo de tasa expirado'),
                        ('FRAUD_FLAGGED',    'Marcada por sistema antifraude'),
                        ('FRAUD_OVERRIDDEN', 'Flag de fraude anulado'),
                        ('MANUAL_RATE',      'Tasa manual aplicada'),
                        ('FIELD_UPDATED',    'Campos editados'),
                        ('NOTE_ADDED',       'Nota agregada'),
                        ('DOCUMENT_ADDED',   'Documento adjunto'),
                    ],
                    db_index=True,
                )),
                ('previous_state', models.JSONField(default=dict)),
                ('new_state', models.JSONField(default=dict)),
                ('user', models.ForeignKey(
                    null=True, blank=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='transaction_audit_logs',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('user_display', models.CharField(max_length=200, blank=True)),
                ('ip_address', models.GenericIPAddressField(null=True, blank=True)),
                ('user_agent', models.CharField(max_length=500, blank=True)),
                ('checksum_sha256', models.CharField(max_length=64)),
                ('timestamp_utc', models.DateTimeField(db_index=True)),
            ],
            options={
                'db_table': 'transaction_audit_log',
                'ordering': ['-timestamp_utc'],
                'verbose_name': 'Log de Auditoría',
                'verbose_name_plural': 'Logs de Auditoría',
            },
        ),
        migrations.AddIndex(
            model_name='transactionauditlog',
            index=models.Index(fields=['transaction', '-timestamp_utc'], name='tx_audit_tx_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='transactionauditlog',
            index=models.Index(fields=['action', '-timestamp_utc'], name='tx_audit_action_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='transactionauditlog',
            index=models.Index(fields=['user', '-timestamp_utc'], name='tx_audit_user_ts_idx'),
        ),
    ]
