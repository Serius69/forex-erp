from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0009_add_traceability_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='exchangerate',
            name='is_primary',
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text=(
                    'True para la tasa que el sistema usará en todas las transacciones. '
                    'Solo puede haber una tasa primaria activa por par de divisas.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='exchangerate',
            name='avg_rate',
            field=models.DecimalField(
                max_digits=10,
                decimal_places=4,
                null=True,
                blank=True,
                help_text='Promedio simple de buy y sell rate (mid-rate).',
            ),
        ),
        migrations.AddIndex(
            model_name='exchangerate',
            index=models.Index(
                fields=['is_primary', 'currency_from', 'currency_to'],
                name='rates_excha_is_prim_idx',
            ),
        ),
    ]
