"""
Migration 0014:
  1. Create ExchangeRateSnapshot model
  2. Seed special currency variants (USD_CASH_LOOSE, USD_SMALL_BILLS, PEN_COINS)
  3. Seed ExchangeRateSource entries for multi-platform providers
"""
from django.db import migrations, models


def seed_special_currencies(apps, schema_editor):
    """Crea las divisas especiales del mercado boliviano si no existen."""
    Currency = apps.get_model('rates', 'Currency')

    special_currencies = [
        {
            'code':              'USD_CASH_LOOSE',
            'name_en':           'USD Cash Loose (Small Bills 5-10)',
            'name_es':           'USD Sueltos / Sencillos (5-10)',
            'symbol':            'US$',
            'scale_factor':      1,
            'use_exchange_rate': True,
            'is_base_currency':  False,
            'is_active':         True,
        },
        {
            'code':              'USD_SMALL_BILLS',
            'name_en':           'USD Small Bills (1-2 Dollars)',
            'name_es':           'USD Billetes 1 y 2',
            'symbol':            'US$',
            'scale_factor':      1,
            'use_exchange_rate': True,
            'is_base_currency':  False,
            'is_active':         True,
        },
        {
            'code':              'PEN_COINS',
            'name_en':           'PEN Coins (Peruvian Sol Coins)',
            'name_es':           'PEN Monedas (Sol Peruano)',
            'symbol':            'S/',
            'scale_factor':      1,
            'use_exchange_rate': True,
            'is_base_currency':  False,
            'is_active':         True,
        },
        # Asegurar monedas estándar que puede que no existan
        {
            'code':              'GBP',
            'name_en':           'British Pound',
            'name_es':           'Libra Esterlina',
            'symbol':            '£',
            'scale_factor':      1,
            'use_exchange_rate': True,
            'is_base_currency':  False,
            'is_active':         True,
        },
        {
            'code':              'CNY',
            'name_en':           'Chinese Yuan',
            'name_es':           'Yuan Chino (Renminbi)',
            'symbol':            '¥',
            'scale_factor':      1,
            'use_exchange_rate': True,
            'is_base_currency':  False,
            'is_active':         True,
        },
    ]

    for data in special_currencies:
        try:
            Currency.objects.get_or_create(code=data['code'], defaults=data)
        except Exception as e:
            print(f"[MIGRATION WARN] Currency {data['code']}: {e}")


def seed_exchange_rate_sources(apps, schema_editor):
    """Crea fuentes de datos para proveedores multi-plataforma."""
    ExchangeRateSource = apps.get_model('rates', 'ExchangeRateSource')

    sources = [
        {
            'name':               'binance_p2p',
            'source_type':        'digital',
            'url':                'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search',
            'is_active':          True,
            'fetch_interval_min': 5,
            'weight':             '1.50',
            'priority':           10,
            'notes':              'Binance P2P — API REST, USDT/BOB en tiempo real',
        },
        {
            'name':               'dolarblue_bo',
            'source_type':        'parallel',
            'url':                'https://www.dolarbluebolivia.click/',
            'is_active':          True,
            'fetch_interval_min': 15,
            'weight':             '1.20',
            'priority':           8,
            'notes':              'DolarBlueBolivia — scraping, referencia paralelo boliviano',
        },
        {
            'name':               'dolarblue_airtm',
            'source_type':        'digital',
            'url':                'https://www.dolarbluebolivia.click/',
            'is_active':          True,
            'fetch_interval_min': 15,
            'weight':             '1.10',
            'priority':           7,
            'notes':              'Airtm extraído de DolarBlueBolivia (scraping)',
        },
        {
            'name':               'dolarblue_takenos',
            'source_type':        'digital',
            'url':                'https://www.dolarbluebolivia.click/',
            'is_active':          True,
            'fetch_interval_min': 15,
            'weight':             '1.10',
            'priority':           7,
            'notes':              'Takenos extraído de DolarBlueBolivia (scraping)',
        },
        {
            'name':               'dolarblue_wallbit',
            'source_type':        'digital',
            'url':                'https://www.dolarbluebolivia.click/',
            'is_active':          True,
            'fetch_interval_min': 15,
            'weight':             '1.00',
            'priority':           6,
            'notes':              'Wallbit extraído de DolarBlueBolivia (scraping)',
        },
        {
            'name':               'bcb_official',
            'source_type':        'bcb_official',
            'url':                'https://www.bcb.gob.bo/mercadocambiario/',
            'is_active':          True,
            'fetch_interval_min': 60,
            'weight':             '0.80',
            'priority':           5,
            'notes':              'BCB — Tipo de cambio oficial regulado',
        },
        {
            'name':               'takenos_api',
            'source_type':        'digital',
            'url':                'https://www.takenos.com/',
            'is_active':          True,
            'fetch_interval_min': 30,
            'weight':             '1.05',
            'priority':           7,
            'notes':              'Takenos — plataforma P2P argentina con operaciones BOB',
        },
        {
            'name':               'airtm_api',
            'source_type':        'digital',
            'url':                'https://www.airtm.com/',
            'is_active':          True,
            'fetch_interval_min': 30,
            'weight':             '1.05',
            'priority':           7,
            'notes':              'Airtm — plataforma P2P latinoamericana',
        },
    ]

    for data in sources:
        try:
            ExchangeRateSource.objects.get_or_create(
                name=data['name'],
                defaults={k: v for k, v in data.items() if k != 'name'},
            )
        except Exception as e:
            print(f"[MIGRATION WARN] ExchangeRateSource {data['name']}: {e}")


def undo_seeds(apps, schema_editor):
    """No revertir seeds — las divisas y fuentes son datos de referencia."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0013_alter_currency_scale_factor'),
    ]

    operations = [
        # ── Widen Currency.code to fit extended codes like USD_CASH_LOOSE ─────
        migrations.AlterField(
            model_name='currency',
            name='code',
            field=models.CharField(max_length=20, unique=True),
        ),

        # ── ExchangeRateSnapshot ──────────────────────────────────────────────
        migrations.CreateModel(
            name='ExchangeRateSnapshot',
            fields=[
                ('id',            models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('date',          models.DateField(db_index=True, unique=True)),
                ('status',        models.CharField(
                    choices=[
                        ('partial',  'Parcial — algunas fuentes no disponibles'),
                        ('complete', 'Completo — todas las fuentes respondieron'),
                        ('degraded', 'Degradado — solo fuentes secundarias'),
                    ],
                    default='partial', max_length=10,
                )),
                ('aggregated_data', models.JSONField(default=dict)),
                ('best_source',   models.CharField(blank=True, max_length=50)),
                ('avg_usd_buy',   models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                ('avg_usd_sell',  models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                ('max_spread_pct', models.DecimalField(decimal_places=3, max_digits=6, null=True, blank=True)),
                ('source_count',  models.IntegerField(default=0)),
                ('anomaly_count', models.IntegerField(default=0)),
                ('close_usd_buy',  models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                ('close_usd_sell', models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                ('close_eur_buy',  models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                ('close_eur_sell', models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                ('notes',         models.TextField(blank=True)),
                ('created_at',    models.DateTimeField(auto_now_add=True)),
                ('updated_at',    models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name':        'Snapshot de Tasas',
                'verbose_name_plural': 'Snapshots de Tasas',
                'ordering':            ['-date'],
            },
        ),
        migrations.AddIndex(
            model_name='exchangeratesnapshot',
            index=models.Index(fields=['-date'], name='rates_snap_date_idx'),
        ),
        migrations.AddIndex(
            model_name='exchangeratesnapshot',
            index=models.Index(fields=['status', '-date'], name='rates_snap_status_date_idx'),
        ),

        # ── Seed currencies and sources ───────────────────────────────────────
        migrations.RunPython(seed_special_currencies,  reverse_code=undo_seeds),
        migrations.RunPython(seed_exchange_rate_sources, reverse_code=undo_seeds),
    ]
