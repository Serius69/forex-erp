"""
Cambia TransactionProfitLedger.transaction de OneToOneField a ForeignKey.
Esto permite registrar tanto la transacción original (BUY/SELL)
como su compensación de reversa (REVERSAL) en el mismo ledger.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0001_initial'),
        ('transactions', '0004_alter_transaction_amount_decimals'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transactionprofitledger',
            name='transaction',
            field=models.ForeignKey(
                help_text=(
                    'Transacción origen de este registro de P&L. '
                    'Una transacción puede tener dos filas: '
                    'la original (BUY/SELL) y la compensación (REVERSAL).'
                ),
                on_delete=django.db.models.deletion.PROTECT,
                related_name='profit_ledgers',
                to='transactions.transaction',
            ),
        ),
    ]
