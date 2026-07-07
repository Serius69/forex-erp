from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0004_alter_transaction_amount_decimals'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='denomination_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('BILLS', 'Billetes grandes (100 y 50)'),
                    ('SUELTOS', 'Sueltos (5, 10, 20)'),
                    ('SINGLES', 'Unidades (1 y 2)'),
                ],
                help_text='Tipo de billete USD: BILLS (100/50), SUELTOS (5/10/20), SINGLES (1/2). '
                          'Requerido para transacciones en efectivo USD.',
                max_length=10,
                null=True,
            ),
        ),
    ]
