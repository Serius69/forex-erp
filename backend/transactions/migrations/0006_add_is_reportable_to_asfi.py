from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0005_add_denomination_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='is_reportable_to_asfi',
            field=models.BooleanField(
                default=True,
                db_index=True,
                help_text='Si TRUE, la transacción se incluye en los reportes regulatorios ASFI '
                          '(RTE, Libro Diario). Si FALSE, es solo interna.',
            ),
        ),
    ]
