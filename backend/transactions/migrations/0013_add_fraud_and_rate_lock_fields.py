from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0012_remove_customer_transaction_documen_4ed5c0_idx_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Extend STATUS_CHOICES — alter field to accept new values
        migrations.AlterField(
            model_name='transaction',
            name='status',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('DRAFT',        'Borrador'),
                    ('PENDING_RATE', 'Esperando tasa'),
                    ('PENDING',      'Pendiente'),
                    ('APPROVED',     'Aprobada'),
                    ('PROCESSING',   'Procesando'),
                    ('COMPLETED',    'Completada'),
                    ('FAILED',       'Fallida'),
                    ('CANCELLED',    'Cancelada'),
                    ('REVERSED',     'Revertida'),
                ],
                default='COMPLETED',
            ),
        ),
        # Parallel rate snapshot
        migrations.AddField(
            model_name='transaction',
            name='parallel_rate_at_creation',
            field=models.DecimalField(
                max_digits=10, decimal_places=4,
                null=True, blank=True,
                help_text='Tasa paralela de mercado en el momento de creación.',
            ),
        ),
        # Rate lock expiry
        migrations.AddField(
            model_name='transaction',
            name='rate_lock_expires_at',
            field=models.DateTimeField(null=True, blank=True, db_index=True),
        ),
        # Fraud score
        migrations.AddField(
            model_name='transaction',
            name='fraud_score',
            field=models.DecimalField(
                max_digits=5, decimal_places=4,
                null=True, blank=True,
                help_text='Score de riesgo 0.0000–1.0000.',
            ),
        ),
        # Fraud flags list
        migrations.AddField(
            model_name='transaction',
            name='fraud_flags',
            field=models.JSONField(default=list, blank=True),
        ),
        # Approval required flag
        migrations.AddField(
            model_name='transaction',
            name='approval_required',
            field=models.BooleanField(default=False, db_index=True),
        ),
        # Approved by user FK
        migrations.AddField(
            model_name='transaction',
            name='approved_by',
            field=models.ForeignKey(
                to=settings.AUTH_USER_MODEL,
                on_delete=django.db.models.deletion.PROTECT,
                null=True, blank=True,
                related_name='transactions_approved',
            ),
        ),
        migrations.AddField(
            model_name='transaction',
            name='approved_at',
            field=models.DateTimeField(null=True, blank=True),
        ),
        # Manual rate justification
        migrations.AddField(
            model_name='transaction',
            name='manual_rate_justification',
            field=models.TextField(blank=True, default=''),
            preserve_default=False,
        ),
    ]
