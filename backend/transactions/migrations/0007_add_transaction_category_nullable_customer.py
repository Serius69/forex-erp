"""
Migration: add transaction_category + make customer nullable.

transaction_category:
  REPORTABLE (default) — requires customer CI, included in ASFI reports
  INTERNA              — no customer required, excluded from ASFI reports

customer:
  Now null=True, blank=True to allow INTERNA transactions without customer data.

is_reportable_to_asfi is kept in sync by Transaction.save() and should not be
set directly — it is derived from transaction_category.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0006_add_is_reportable_to_asfi'),
    ]

    operations = [
        # 1. Add transaction_category field (REPORTABLE default keeps existing rows valid)
        migrations.AddField(
            model_name='transaction',
            name='transaction_category',
            field=models.CharField(
                max_length=12,
                choices=[
                    ('REPORTABLE', 'Reportable ASFI'),
                    ('INTERNA',    'Interna (no reportable)'),
                ],
                default='REPORTABLE',
                db_index=True,
                help_text=(
                    'REPORTABLE: requiere CI del cliente, se incluye en reportes ASFI. '
                    'INTERNA: sin datos de cliente obligatorios, no aparece en reportes ASFI.'
                ),
            ),
        ),

        # 2. Make customer nullable to allow INTERNA transactions without customer data
        migrations.AlterField(
            model_name='transaction',
            name='customer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='transactions',
                to='transactions.customer',
            ),
        ),
    ]
