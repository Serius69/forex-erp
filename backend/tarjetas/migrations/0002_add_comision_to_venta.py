# Generated manually 2026-04-07 — Add comision_bob + total_con_comision to VentaTarjeta

from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tarjetas', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='ventatarjeta',
            name='comision_bob',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('0'), max_digits=10,
                help_text='Comisión o cargo adicional sobre la venta en BOB',
            ),
        ),
        migrations.AddField(
            model_name='ventatarjeta',
            name='total_con_comision',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('0'), max_digits=15,
                help_text='total_bob + comision_bob',
            ),
        ),
    ]
