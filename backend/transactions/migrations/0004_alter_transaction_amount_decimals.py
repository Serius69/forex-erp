"""
Migration: increase decimal_places on amount_from/amount_to from 2 to 4.
Required by quantize_amount() which returns 4-decimal precision.
"""
from django.db import migrations, models
from decimal import Decimal
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0003_alter_transactiondocument_options'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='amount_from',
            field=models.DecimalField(
                decimal_places=4,
                max_digits=15,
                validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))],
            ),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='amount_to',
            field=models.DecimalField(
                decimal_places=4,
                max_digits=15,
                validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))],
            ),
        ),
    ]
