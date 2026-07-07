from django.db import migrations, models
import django.db.models.expressions


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0016_add_status_created_at_index'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(
                fields=['branch', 'status', '-created_at'],
                name='tx_branch_status_ts_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(
                fields=['branch', 'transaction_type', '-created_at'],
                name='tx_branch_type_ts_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(
                fields=['branch', '-created_at'],
                name='tx_branch_completed_idx',
                condition=models.Q(status='COMPLETED'),
            ),
        ),
    ]
