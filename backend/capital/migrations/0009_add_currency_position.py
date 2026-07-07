from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('capital', '0008_remove_cashbob_capital_cashbob_branch_fecha_uniq_and_more'),
        ('rates', '0016_referencerate'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CurrencyPosition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='currency_positions',
                    to='users.branch',
                )),
                ('currency', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='positions',
                    to='rates.currency',
                )),
                ('net_position',          models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('0'))),
                ('avg_acquisition_cost',  models.DecimalField(max_digits=10, decimal_places=4, default=Decimal('0'))),
                ('total_bought',          models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('0'))),
                ('total_sold',            models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('0'))),
                ('total_cost_bob',        models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))),
                ('unrealized_pnl_parallel', models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))),
                ('unrealized_pnl_official', models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))),
                ('parallel_rate_used',    models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)),
                ('official_rate_used',    models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)),
                ('last_tx_at',            models.DateTimeField(null=True, blank=True)),
                ('updated_at',            models.DateTimeField(auto_now=True)),
                ('created_at',            models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'capital_currency_position',
                'unique_together': {('branch', 'currency')},
                'ordering': ['branch', 'currency__code'],
                'verbose_name': 'Posición por Divisa',
                'verbose_name_plural': 'Posiciones por Divisa',
            },
        ),
        migrations.AddIndex(
            model_name='currencyposition',
            index=models.Index(fields=['branch', 'currency'], name='cap_pos_branch_cur_idx'),
        ),
        migrations.CreateModel(
            name='CurrencyPositionHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('position', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='history',
                    to='capital.currencyposition',
                )),
                ('fecha',                  models.DateField(db_index=True)),
                ('net_position',           models.DecimalField(max_digits=18, decimal_places=4)),
                ('avg_acquisition_cost',   models.DecimalField(max_digits=10, decimal_places=4)),
                ('unrealized_pnl_parallel',models.DecimalField(max_digits=18, decimal_places=2)),
                ('unrealized_pnl_official',models.DecimalField(max_digits=18, decimal_places=2)),
                ('parallel_rate',          models.DecimalField(max_digits=10, decimal_places=4, null=True)),
                ('official_rate',          models.DecimalField(max_digits=10, decimal_places=4, null=True)),
                ('snapshot_type',          models.CharField(max_length=10, choices=[('DAILY','Diario'),('MANUAL','Manual')], default='DAILY')),
                ('created_at',             models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'capital_currency_position_history',
                'ordering': ['-fecha', '-created_at'],
                'verbose_name': 'Historial Posición Divisa',
                'verbose_name_plural': 'Historial Posiciones Divisa',
            },
        ),
        migrations.AddIndex(
            model_name='currencypositionhistory',
            index=models.Index(fields=['position', '-fecha'], name='cap_pos_hist_pos_fecha_idx'),
        ),
    ]
