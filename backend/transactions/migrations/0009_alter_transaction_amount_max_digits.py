"""
Migration: increase max_digits on amount_from/amount_to from 15 to 18.
Fixes validation error when JS floating-point multiplication produces
values like 69000.00000000001 (total digits > 15).
"""
from django.db import migrations, models
from decimal import Decimal
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0008_add_visible_asfi_nombre_cliente_carnet'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='amount_from',
            field=models.DecimalField(
                decimal_places=4,
                max_digits=18,
                validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))],
            ),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='amount_to',
            field=models.DecimalField(
                decimal_places=4,
                max_digits=18,
                validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))],
            ),
        ),
    ]
