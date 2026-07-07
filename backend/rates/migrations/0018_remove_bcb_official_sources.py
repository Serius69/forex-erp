"""
Migración: eliminar BCB/official del sistema de tasas.

Cambios:
  1. Eliminar tabla rates_referencerate (ReferenceRate model eliminado)
  2. Eliminar campo rate_bcb de rates_pricing_decision_log
  3. Eliminar campo weight_bcb de rates_pricing_decision_log
  4. Cambiar default market_type en rates_exchangerate de 'official' a 'paralelo_digital'
  5. Cambiar default source en rates_exchangerate de 'BCB' a ''
  6. Eliminar registros con market_type IN ('official', 'bcb') y tasas < 7.0 BOB
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0017_rename_rates_ref_currency_source_ts_idx_rates_refer_currenc_904c1f_idx'),
    ]

    operations = [
        # 1. Eliminar tabla ReferenceRate
        migrations.DeleteModel(
            name='ReferenceRate',
        ),

        # 2. Eliminar rate_bcb de ExchangeRateDecisionLog
        migrations.RemoveField(
            model_name='exchangeratedecisionlog',
            name='rate_bcb',
        ),

        # 3. Eliminar weight_bcb de ExchangeRateDecisionLog
        migrations.RemoveField(
            model_name='exchangeratedecisionlog',
            name='weight_bcb',
        ),

        # 4. Actualizar choices + default market_type en ExchangeRate
        migrations.AlterField(
            model_name='exchangerate',
            name='market_type',
            field=models.CharField(
                max_length=30,
                choices=[
                    ('paralelo_digital',            'Paralelo Digital (Binance/Takenos/Airtm)'),
                    ('paralelo_fisico_empresa',     'Paralelo Físico — Empresa'),
                    ('paralelo_fisico_competencia', 'Paralelo Físico — Competencia'),
                    ('parallel', 'Mercado Paralelo (legacy)'),
                    ('digital',  'Plataforma Digital (legacy)'),
                ],
                default='paralelo_digital',
                db_index=True,
                help_text='Tipo de mercado que representa esta tasa.',
            ),
        ),

        # 5. Actualizar default source en ExchangeRate
        migrations.AlterField(
            model_name='exchangerate',
            name='source',
            field=models.CharField(
                max_length=50,
                default='',
                help_text='Nombre(s) de la fuente — legado, usar source_method para clasificación.',
            ),
        ),

        # 6. Actualizar choices de ExchangeRateSource
        migrations.AlterField(
            model_name='exchangeratesource',
            name='source_type',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('digital',  'Plataforma Digital'),
                    ('parallel', 'Mercado Paralelo'),
                ],
                db_index=True,
            ),
        ),

        # 7. Actualizar pesos por defecto en ExchangeRateDecisionLog
        migrations.AlterField(
            model_name='exchangeratedecisionlog',
            name='weight_binance',
            field=models.DecimalField(max_digits=5, decimal_places=4, default='0.45'),
        ),
        migrations.AlterField(
            model_name='exchangeratedecisionlog',
            name='weight_historical',
            field=models.DecimalField(max_digits=5, decimal_places=4, default='0.35'),
        ),
        migrations.AlterField(
            model_name='exchangeratedecisionlog',
            name='weight_competition',
            field=models.DecimalField(max_digits=5, decimal_places=4, default='0.20'),
        ),
    ]
