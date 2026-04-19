# Generated for CashFlowLog — tracks BOB cash impact of every forex transaction.
from decimal import Decimal
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):

    dependencies = [
        ('capital', '0004_add_capital_composicion'),
        ('transactions', '0004_alter_transaction_amount_decimals'),
        ('users', '0002_alter_branch_options_alter_user_options'),
    ]

    operations = [
        migrations.CreateModel(
            name='CashFlowLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(
                    choices=[('IN', 'Entrada de efectivo'), ('OUT', 'Salida de efectivo')],
                    db_index=True, max_length=3,
                )),
                ('concepto', models.CharField(
                    help_text='Descripción legible: "COMPRA USD × 100", etc.',
                    max_length=300,
                )),
                ('monto_bob', models.DecimalField(
                    decimal_places=2,
                    help_text='Monto absoluto en BOB (siempre positivo)',
                    max_digits=18,
                    validators=[MinValueValidator(Decimal('0.01'))],
                )),
                ('campo_afectado', models.CharField(
                    help_text='Campo de CapitalComposicion modificado: fuertes, qr_transferencias, etc.',
                    max_length=30,
                )),
                ('saldo_anterior', models.DecimalField(
                    decimal_places=2,
                    help_text='Valor del campo antes de aplicar la transacción',
                    max_digits=18,
                )),
                ('saldo_resultante', models.DecimalField(
                    decimal_places=2,
                    help_text='Valor del campo después de aplicar la transacción',
                    max_digits=18,
                )),
                ('fecha', models.DateField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='cash_flow_logs',
                    to='users.branch',
                )),
                ('transaction', models.ForeignKey(
                    help_text='Transacción que originó este movimiento de caja',
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='cash_flow_logs',
                    to='transactions.transaction',
                )),
            ],
            options={
                'verbose_name': 'Log de Flujo de Caja',
                'verbose_name_plural': 'Logs de Flujo de Caja',
                'db_table': 'capital_cashflow_log',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='cashflowlog',
            index=models.Index(fields=['branch', '-fecha'], name='capital_cashflow_branch_fecha_idx'),
        ),
        migrations.AddIndex(
            model_name='cashflowlog',
            index=models.Index(fields=['transaction'], name='capital_cashflow_tx_idx'),
        ),
        migrations.AddIndex(
            model_name='cashflowlog',
            index=models.Index(fields=['tipo', '-fecha'], name='capital_cashflow_tipo_fecha_idx'),
        ),
    ]
