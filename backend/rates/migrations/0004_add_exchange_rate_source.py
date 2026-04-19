# Generated manually 2026-04-07 — ExchangeRateSource model + rate_source FK

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0003_add_scale_factor_to_currency'),
    ]

    operations = [
        # 1. Create ExchangeRateSource
        migrations.CreateModel(
            name='ExchangeRateSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('source_type', models.CharField(
                    choices=[
                        ('bcb_official',  'BCB Oficial'),
                        ('bcb_reference', 'BCB Referencial'),
                        ('digital',       'Plataforma Digital'),
                        ('parallel',      'Mercado Paralelo'),
                    ],
                    db_index=True,
                    max_length=20,
                )),
                ('url', models.URLField(blank=True, help_text='URL base del scraping/API')),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('fetch_interval_min', models.IntegerField(
                    default=30,
                    help_text='Frecuencia de actualización en minutos',
                )),
                ('weight', models.DecimalField(
                    decimal_places=2,
                    default='1.00',
                    help_text='Peso en el cálculo de tasa promedio ponderada (paralelo>digital>oficial)',
                    max_digits=4,
                )),
                ('priority', models.IntegerField(
                    default=1,
                    help_text='Mayor número = usada primero como fallback',
                )),
                ('last_fetched_at', models.DateTimeField(blank=True, null=True)),
                ('last_success_at', models.DateTimeField(blank=True, null=True)),
                ('consecutive_failures', models.IntegerField(default=0)),
                ('config', models.JSONField(
                    blank=True,
                    default=dict,
                    help_text='Configuración extra: {"headers": {}, "css_selector": "", "timeout": 15}',
                )),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name':        'Fuente de Tasa',
                'verbose_name_plural': 'Fuentes de Tasas',
                'ordering':            ['-priority', 'name'],
            },
        ),

        # 2. Add rate_source FK to ExchangeRate (nullable — backward compatible)
        migrations.AddField(
            model_name='exchangerate',
            name='rate_source',
            field=models.ForeignKey(
                blank=True,
                help_text='Fuente de datos que generó esta tasa.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='rates',
                to='rates.exchangeratesource',
            ),
        ),

        # 3. Expand market_type choices to 4 values (official, bcb, digital, parallel)
        migrations.AlterField(
            model_name='exchangerate',
            name='market_type',
            field=models.CharField(
                choices=[
                    ('official', 'Oficial BCB'),
                    ('bcb',      'BCB Referencial'),
                    ('digital',  'Plataforma Digital'),
                    ('parallel', 'Mercado Paralelo'),
                ],
                db_index=True,
                default='official',
                help_text='Tipo de mercado que representa esta tasa.',
                max_length=10,
            ),
        ),

        # 4. Update unique_together to include rate_source
        migrations.AlterUniqueTogether(
            name='exchangerate',
            unique_together={('currency_from', 'currency_to', 'valid_from', 'market_type', 'rate_source')},
        ),

        # 5. Add composite indexes for efficient multi-source queries
        migrations.AddIndex(
            model_name='exchangerate',
            index=models.Index(
                fields=['rate_source', 'currency_from', '-valid_from'],
                name='rates_excha_rate_so_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='exchangerate',
            index=models.Index(
                fields=['valid_until', 'currency_from', 'currency_to'],
                name='rates_excha_valid_u_idx',
            ),
        ),
    ]
