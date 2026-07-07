from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0021_alter_exchangerateconsensus_cambio_pct_24h_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='RawRateSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(
                    choices=[
                        ('binance_p2p',        'Binance P2P'),
                        ('dolar_blue_bolivia', 'DolarBlueBolivia'),
                        ('airtm',              'AirTM'),
                        ('eldorado',           'Eldorado'),
                        ('wallbit',            'Wallbit'),
                        ('saldoar',            'SaldoAR'),
                        ('okx',                'OKX P2P'),
                        ('p2p_exchanges',      'P2P Exchanges'),
                        ('p2p_multi_fiat',     'P2P Multi-Fiat'),
                        ('digital',            'Digital (Takenos/Airtm)'),
                        ('parallel',           'Parallel Scraper'),
                        ('dolarapi',           'DolarAPI'),
                        ('criptoya',           'Criptoya'),
                        ('other',              'Other'),
                    ],
                    db_index=True, max_length=30,
                )),
                ('currency_pair', models.CharField(
                    db_index=True, max_length=10,
                    help_text='ej: USD/BOB, USDT/ARS',
                )),
                ('raw_value', models.DecimalField(
                    blank=True, null=True, max_digits=18, decimal_places=8,
                )),
                ('fetched_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('response_time_ms', models.IntegerField(
                    default=0, help_text='Tiempo de respuesta en ms',
                )),
                ('success', models.BooleanField(default=True, db_index=True)),
                ('error_message', models.TextField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Snapshot Crudo de Tasa',
                'verbose_name_plural': 'Snapshots Crudos de Tasas',
                'ordering': ['-fetched_at'],
            },
        ),
        migrations.AddIndex(
            model_name='rawratesnapshot',
            index=models.Index(fields=['-fetched_at'], name='rawsnap_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='rawratesnapshot',
            index=models.Index(fields=['source', 'currency_pair'], name='rawsnap_src_pair_idx'),
        ),
        migrations.AddIndex(
            model_name='rawratesnapshot',
            index=models.Index(fields=['success', '-fetched_at'], name='rawsnap_ok_ts_idx'),
        ),
    ]
