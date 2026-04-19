from decimal import Decimal
import django.db.models.deletion
from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('transactions', '0004_alter_transaction_amount_decimals'),
        ('users', '0002_alter_branch_options_alter_user_options'),
    ]

    operations = [

        # ── TransactionProfitLedger ───────────────────────────────────────────
        migrations.CreateModel(
            name='TransactionProfitLedger',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('transaction_type', models.CharField(
                    choices=[('BUY', 'Compra'), ('SELL', 'Venta'), ('REVERSAL', 'Reversa')],
                    max_length=8,
                )),
                ('currency_code',   models.CharField(db_index=True, max_length=5)),
                ('fecha',           models.DateField(db_index=True)),
                ('amount_foreign',  models.DecimalField(decimal_places=4, max_digits=18)),
                ('exchange_rate',   models.DecimalField(decimal_places=4, max_digits=14)),
                ('amount_bob',      models.DecimalField(decimal_places=2, max_digits=18)),
                ('wac_at_transaction',    models.DecimalField(decimal_places=4, max_digits=14,
                    help_text='WAC antes de la transacción')),
                ('wac_after_transaction', models.DecimalField(decimal_places=4, max_digits=14,
                    help_text='WAC después de la transacción')),
                ('cost_bob',        models.DecimalField(decimal_places=2, max_digits=18)),
                ('profit_bob',      models.DecimalField(decimal_places=2, max_digits=18)),
                ('profit_pct',      models.DecimalField(decimal_places=4, max_digits=8,
                    default=Decimal('0'))),
                ('spread_bob',      models.DecimalField(decimal_places=4, max_digits=10,
                    default=Decimal('0'))),
                ('created_at',      models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='profit_ledgers',
                    to='users.branch',
                )),
                ('transaction', models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='profit_ledger',
                    to='transactions.transaction',
                )),
            ],
            options={
                'verbose_name': 'Ledger de Ganancias',
                'verbose_name_plural': 'Ledger de Ganancias',
                'db_table': 'analytics_profit_ledger',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='transactionprofitledger',
            index=models.Index(fields=['currency_code', '-fecha'],
                               name='analytics_profit_currency_fecha_idx'),
        ),
        migrations.AddIndex(
            model_name='transactionprofitledger',
            index=models.Index(fields=['branch', '-fecha'],
                               name='analytics_profit_branch_fecha_idx'),
        ),
        migrations.AddIndex(
            model_name='transactionprofitledger',
            index=models.Index(fields=['-fecha', 'transaction_type'],
                               name='analytics_profit_fecha_type_idx'),
        ),

        # ── PnLDailySnapshot ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='PnLDailySnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('fecha',                 models.DateField(db_index=True)),
                ('num_ventas',            models.IntegerField(default=0)),
                ('ingreso_ventas_bob',    models.DecimalField(decimal_places=2,
                    max_digits=18, default=Decimal('0'))),
                ('costo_ventas_bob',      models.DecimalField(decimal_places=2,
                    max_digits=18, default=Decimal('0'))),
                ('ganancia_bruta_bob',    models.DecimalField(decimal_places=2,
                    max_digits=18, default=Decimal('0'))),
                ('num_compras',           models.IntegerField(default=0)),
                ('inversion_compras_bob', models.DecimalField(decimal_places=2,
                    max_digits=18, default=Decimal('0'))),
                ('gastos_operativos_bob', models.DecimalField(decimal_places=2,
                    max_digits=18, default=Decimal('0'))),
                ('ganancia_neta_bob',     models.DecimalField(decimal_places=2,
                    max_digits=18, default=Decimal('0'))),
                ('margen_neto_pct',       models.DecimalField(decimal_places=4,
                    max_digits=8, default=Decimal('0'))),
                ('calculado_en',          models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='pnl_snapshots',
                    to='users.branch',
                )),
            ],
            options={
                'verbose_name': 'Snapshot P&L Diario',
                'verbose_name_plural': 'Snapshots P&L Diario',
                'db_table': 'analytics_pnl_daily',
                'ordering': ['-fecha'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='pnldailysnapshot',
            unique_together={('fecha', 'branch')},
        ),
        migrations.AddIndex(
            model_name='pnldailysnapshot',
            index=models.Index(fields=['branch', '-fecha'],
                               name='analytics_pnl_branch_fecha_idx'),
        ),

        # ── ExposureSnapshot ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='ExposureSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('timestamp',          models.DateTimeField(db_index=True)),
                ('currency_code',      models.CharField(db_index=True, max_length=5)),
                ('currency_name',      models.CharField(max_length=100)),
                ('scale_factor',       models.IntegerField(default=1)),
                ('stock_units',        models.DecimalField(decimal_places=4, max_digits=18)),
                ('wac',                models.DecimalField(decimal_places=4, max_digits=14)),
                ('sell_rate_unit',     models.DecimalField(decimal_places=4, max_digits=14)),
                ('sell_rate_lote',     models.DecimalField(decimal_places=4, max_digits=14)),
                ('exposure_bob',       models.DecimalField(decimal_places=2, max_digits=18)),
                ('pct_of_capital',     models.DecimalField(decimal_places=4, max_digits=7)),
                ('unrealized_pnl_bob', models.DecimalField(decimal_places=2, max_digits=18)),
                ('alert_level',        models.CharField(
                    choices=[('OK','Normal'),('WARNING','Advertencia'),('CRITICAL','Crítico')],
                    default='OK', max_length=8,
                )),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='exposure_snapshots',
                    to='users.branch',
                )),
            ],
            options={
                'verbose_name': 'Snapshot de Exposición',
                'verbose_name_plural': 'Snapshots de Exposición',
                'db_table': 'analytics_exposure',
                'ordering': ['-timestamp', 'currency_code'],
            },
        ),
        migrations.AddIndex(
            model_name='exposuresnapshot',
            index=models.Index(fields=['branch', '-timestamp'],
                               name='analytics_exp_branch_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='exposuresnapshot',
            index=models.Index(fields=['currency_code', '-timestamp'],
                               name='analytics_exp_currency_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='exposuresnapshot',
            index=models.Index(fields=['alert_level', '-timestamp'],
                               name='analytics_exp_alert_ts_idx'),
        ),

        # ── SpreadSnapshot ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='SpreadSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('timestamp',          models.DateTimeField(db_index=True)),
                ('currency_code',      models.CharField(db_index=True, max_length=5)),
                ('market_type',        models.CharField(max_length=30)),
                ('buy_rate',           models.DecimalField(decimal_places=4, max_digits=14)),
                ('sell_rate',          models.DecimalField(decimal_places=4, max_digits=14)),
                ('official_rate',      models.DecimalField(decimal_places=4, max_digits=14,
                    null=True, blank=True)),
                ('spread_bob',         models.DecimalField(decimal_places=4, max_digits=10)),
                ('spread_pct',         models.DecimalField(decimal_places=4, max_digits=8)),
                ('prima_oficial_pct',  models.DecimalField(decimal_places=4, max_digits=8,
                    default=Decimal('0'))),
            ],
            options={
                'verbose_name': 'Snapshot de Spread',
                'verbose_name_plural': 'Snapshots de Spread',
                'db_table': 'analytics_spread',
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='spreadsnapshot',
            index=models.Index(fields=['currency_code', '-timestamp'],
                               name='analytics_spread_currency_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='spreadsnapshot',
            index=models.Index(fields=['market_type', '-timestamp'],
                               name='analytics_spread_market_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='spreadsnapshot',
            index=models.Index(fields=['currency_code', 'market_type', '-timestamp'],
                               name='analytics_spread_curr_mkt_ts_idx'),
        ),
    ]
