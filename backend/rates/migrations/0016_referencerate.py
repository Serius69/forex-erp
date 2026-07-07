from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0015_rename_rates_snap_date_idx_rates_excha_date_683479_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReferenceRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('currency', models.CharField(db_index=True, max_length=10)),
                ('reference_buy', models.DecimalField(decimal_places=4, max_digits=10)),
                ('reference_sell', models.DecimalField(decimal_places=4, max_digits=10)),
                ('source', models.CharField(
                    choices=[('BCB', 'Banco Central de Bolivia'), ('BCP', 'BCP Bolivia')],
                    db_index=True, max_length=5,
                )),
                ('raw_response', models.JSONField(blank=True, default=dict)),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'verbose_name': 'Tasa de Referencia',
                'verbose_name_plural': 'Tasas de Referencia',
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='referencerate',
            index=models.Index(
                fields=['currency', 'source', '-timestamp'],
                name='rates_ref_currency_source_ts_idx',
            ),
        ),
    ]
