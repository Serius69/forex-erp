# rates/migrations/0007_add_pricing_decision_log.py
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0006_extend_market_type_choices'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExchangeRateDecisionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('currency_code', models.CharField(db_index=True, max_length=10)),
                ('trigger', models.CharField(
                    choices=[
                        ('scheduled', 'Tarea programada'), ('manual', 'Solicitud manual'),
                        ('inventory', 'Alerta de inventario'), ('demand', 'Cambio de demanda'),
                    ],
                    default='scheduled', max_length=20,
                )),
                ('rate_bcb',         models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ('rate_binance',     models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ('rate_historical',  models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ('rate_competition', models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ('weight_bcb',         models.DecimalField(decimal_places=4, default=Decimal('0.25'), max_digits=5)),
                ('weight_binance',     models.DecimalField(decimal_places=4, default=Decimal('0.35'), max_digits=5)),
                ('weight_historical',  models.DecimalField(decimal_places=4, default=Decimal('0.25'), max_digits=5)),
                ('weight_competition', models.DecimalField(decimal_places=4, default=Decimal('0.15'), max_digits=5)),
                ('base_rate_bob',      models.DecimalField(decimal_places=4, max_digits=12)),
                ('inventory_factor',   models.DecimalField(decimal_places=4, default=Decimal('1.0'), max_digits=7)),
                ('demand_factor',      models.DecimalField(decimal_places=4, default=Decimal('1.0'), max_digits=7)),
                ('suggested_buy',      models.DecimalField(decimal_places=4, max_digits=12)),
                ('suggested_sell',     models.DecimalField(decimal_places=4, max_digits=12)),
                ('suggested_spread',   models.DecimalField(decimal_places=4, max_digits=12)),
                ('suggested_spread_pct', models.DecimalField(decimal_places=3, max_digits=6)),
                ('actual_buy',  models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ('actual_sell', models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ('inventory_stock',     models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('inventory_minimum',   models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('inventory_maximum',   models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('inventory_stock_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('recent_buy_count',  models.IntegerField(default=0)),
                ('recent_sell_count', models.IntegerField(default=0)),
                ('recommendation', models.CharField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='pricing_decisions',
                    to='users.branch',
                )),
            ],
            options={
                'verbose_name': 'Decisión de Precios AI',
                'verbose_name_plural': 'Decisiones de Precios AI',
                'db_table': 'rates_pricing_decision_log',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['currency_code', '-created_at'],
                                 name='rates_pricin_curr_cd_idx'),
                    models.Index(fields=['branch', '-created_at'],
                                 name='rates_pricin_branch_idx'),
                ],
            },
        ),
    ]
