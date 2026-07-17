from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0017_add_composite_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(
                fields=['cashier', '-created_at'],
                name='tx_cashier_ts_idx',
            ),
        ),
    ]
