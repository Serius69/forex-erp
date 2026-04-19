from decimal import Decimal
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tarjetas', '0002_add_comision_to_venta'),
        ('users', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MovimientoTarjeta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('tipo_movimiento', models.CharField(
                    choices=[('COMPRA', 'Compra de lote'), ('VENTA', 'Venta a cliente')],
                    db_index=True, max_length=6,
                )),
                ('cantidad', models.PositiveIntegerField()),
                ('precio_unitario', models.DecimalField(decimal_places=4, max_digits=10)),
                ('total_bob', models.DecimalField(decimal_places=2, max_digits=15)),
                ('ganancia_bob', models.DecimalField(
                    blank=True, decimal_places=2, max_digits=15, null=True,
                    help_text='Ganancia neta. Solo aplica a VENTA.',
                )),
                ('notas', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('tipo_tarjeta', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='movimientos', to='tarjetas.tipotarjeta',
                )),
                ('lote_compra', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='movimientos_diario', to='tarjetas.lotecompra',
                    help_text='Referencia al lote de compra origen (solo COMPRA).',
                )),
                ('venta_tarjeta', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='movimientos_diario', to='tarjetas.ventatarjeta',
                    help_text='Referencia a la venta origen (solo VENTA).',
                )),
                ('usuario', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='movimientos_tarjetas',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='movimientos_tarjetas', to='users.branch',
                )),
            ],
            options={
                'verbose_name': 'Movimiento de Tarjeta',
                'verbose_name_plural': 'Movimientos de Tarjetas',
                'db_table': 'tarjetas_movimiento',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='movimientotarjeta',
            index=models.Index(
                fields=['tipo_tarjeta', '-created_at'],
                name='tarjetas_mov_tipo_ts_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='movimientotarjeta',
            index=models.Index(
                fields=['tipo_movimiento', '-created_at'],
                name='tarjetas_mov_tipmov_ts_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='movimientotarjeta',
            index=models.Index(
                fields=['branch', '-created_at'],
                name='tarjetas_mov_branch_ts_idx',
            ),
        ),
    ]
