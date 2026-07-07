"""
Migration 0020: Add integration-layer models.

New fields on ExchangeRateSource:
  id_fuente, tipo_fuente, metodo_http, requiere_auth,
  pais_referencia, necesita_revision

New models:
  ExchangeRateRaw   — immutable raw data per fetch
  ExchangeRateConsensus — weighted consensus per pair
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0019_alter_exchangeratedecisionlog_weight_binance_and_more'),
    ]

    operations = [
        # ── Extend ExchangeRateSource ──────────────────────────────────────────
        migrations.AddField(
            model_name='exchangeratesource',
            name='id_fuente',
            field=models.CharField(
                max_length=60, unique=True, null=True, blank=True,
                help_text='Slug único: binance_p2p_bob, saldoar…',
            ),
        ),
        migrations.AddField(
            model_name='exchangeratesource',
            name='tipo_fuente',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('P2P',       'P2P Exchange'),
                    ('AGREGADOR', 'Agregador / Sitio Web'),
                    ('EXCHANGE',  'Exchange Centralizado'),
                    ('WALLET',    'Wallet / Remesa'),
                ],
                null=True, blank=True, db_index=True,
            ),
        ),
        migrations.AddField(
            model_name='exchangeratesource',
            name='metodo_http',
            field=models.CharField(
                max_length=4,
                choices=[('GET', 'GET'), ('POST', 'POST')],
                default='GET',
            ),
        ),
        migrations.AddField(
            model_name='exchangeratesource',
            name='requiere_auth',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='exchangeratesource',
            name='pais_referencia',
            field=models.CharField(max_length=3, blank=True),
        ),
        migrations.AddField(
            model_name='exchangeratesource',
            name='necesita_revision',
            field=models.BooleanField(
                default=False,
                help_text='True si el parser no encontró el dato en el último ciclo',
            ),
        ),

        # ── ExchangeRateRaw ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='ExchangeRateRaw',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('fuente', models.ForeignKey(
                    'rates.ExchangeRateSource',
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='raw_rates', null=True, blank=True,
                )),
                ('id_fuente_str', models.CharField(max_length=60, db_index=True)),
                ('moneda_base',   models.CharField(max_length=3, db_index=True)),
                ('moneda_cotizada', models.CharField(max_length=3, db_index=True)),
                ('precio_compra',  models.DecimalField(max_digits=18, decimal_places=8)),
                ('precio_venta',   models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)),
                ('precio_promedio', models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)),
                ('spread_pct',     models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)),
                ('timestamp_fuente', models.DateTimeField()),
                ('timestamp_captura', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('payload_raw',    models.JSONField(default=dict)),
                ('es_valido',      models.BooleanField(default=True, db_index=True)),
                ('notas',          models.TextField(blank=True)),
            ],
            options={
                'verbose_name': 'Dato Crudo de Tasa',
                'verbose_name_plural': 'Datos Crudos de Tasas',
                'ordering': ['-timestamp_captura'],
            },
        ),
        migrations.AddIndex(
            model_name='exchangerateraw',
            index=models.Index(
                fields=['moneda_base', 'moneda_cotizada', '-timestamp_captura'],
                name='rates_raw_pair_ts_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='exchangerateraw',
            index=models.Index(
                fields=['id_fuente_str', '-timestamp_captura'],
                name='rates_raw_fuente_ts_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='exchangerateraw',
            index=models.Index(
                fields=['es_valido', 'moneda_base', '-timestamp_captura'],
                name='rates_raw_valid_idx',
            ),
        ),

        # ── ExchangeRateConsensus ─────────────────────────────────────────────
        migrations.CreateModel(
            name='ExchangeRateConsensus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('par',            models.CharField(max_length=7, db_index=True)),
                ('moneda_base',    models.CharField(max_length=3)),
                ('moneda_cotizada', models.CharField(max_length=3)),
                ('precio_consenso', models.DecimalField(max_digits=18, decimal_places=8)),
                ('precio_compra',  models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)),
                ('precio_venta',   models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)),
                ('fuentes_usadas', models.JSONField(default=list)),
                ('fuentes_count',  models.IntegerField(default=0)),
                ('confianza_pct',  models.IntegerField(default=0)),
                ('timestamp_calculo', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('metodo_calculo', models.CharField(
                    max_length=20,
                    choices=[
                        ('MEDIA_PONDERADA', 'Media ponderada por confianza'),
                        ('MEDIANA', 'Mediana simple'),
                        ('WINSORIZED_MEAN', 'Media Winsorizada (sin outliers)'),
                    ],
                    default='MEDIA_PONDERADA',
                )),
                ('vigente',       models.BooleanField(default=False, db_index=True)),
                ('cambio_pct_24h', models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)),
                ('tendencia',     models.CharField(max_length=10, blank=True)),
            ],
            options={
                'verbose_name': 'Consenso de Tasa',
                'verbose_name_plural': 'Consensos de Tasas',
                'ordering': ['-timestamp_calculo'],
            },
        ),
        migrations.AddIndex(
            model_name='exchangerateconsensus',
            index=models.Index(
                fields=['par', '-timestamp_calculo'],
                name='rates_cons_par_ts_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='exchangerateconsensus',
            index=models.Index(
                fields=['vigente', 'par'],
                name='rates_cons_vigente_idx',
            ),
        ),
    ]
