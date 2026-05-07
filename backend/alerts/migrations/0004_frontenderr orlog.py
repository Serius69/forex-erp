from django.db import migrations, models
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0003_fix_related_name_conflicts'),
    ]

    operations = [
        migrations.CreateModel(
            name='FrontendErrorLog',
            fields=[
                ('id',              models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('error_id',        models.CharField(db_index=True, max_length=64)),
                ('error_type',      models.CharField(db_index=True, default='UnknownError', max_length=64)),
                ('message',         models.TextField()),
                ('stack',           models.TextField(blank=True)),
                ('component_stack', models.TextField(blank=True)),
                ('url',             models.CharField(blank=True, max_length=500)),
                ('user_agent',      models.CharField(blank=True, max_length=300)),
                ('user_id',         models.IntegerField(blank=True, db_index=True, null=True)),
                ('company_id',      models.IntegerField(blank=True, null=True)),
                ('extra',           models.JSONField(blank=True, default=dict)),
                ('ip_address',      models.GenericIPAddressField(blank=True, null=True)),
                ('created_at',      models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
            ],
            options={
                'verbose_name': 'Error Frontend',
                'verbose_name_plural': 'Errores Frontend',
                'db_table': 'alerts_frontend_error_log',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='frontenderr orlog',
            index=models.Index(fields=['error_type', '-created_at'], name='fe_err_type_recent_idx'),
        ),
    ]
