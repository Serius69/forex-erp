from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_rename_users_branch_company_active_idx_users_branc_company_058b1d_idx_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='useractivity',
            index=models.Index(
                fields=['user', '-timestamp'],
                name='useract_user_ts_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='useractivity',
            index=models.Index(
                fields=['-timestamp'],
                name='useract_ts_idx',
            ),
        ),
    ]
