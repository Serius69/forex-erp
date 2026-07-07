# users/migrations/0003_add_audit_log.py
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('users', '0002_alter_branch_options_alter_user_options'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.CharField(db_index=True, max_length=100)),
                ('object_repr', models.CharField(blank=True, max_length=300)),
                ('action', models.CharField(
                    choices=[
                        ('CREATE', 'Creación'), ('UPDATE', 'Modificación'),
                        ('DELETE', 'Eliminación'), ('REVERSE', 'Reversión'),
                    ],
                    db_index=True, max_length=10,
                )),
                ('before_json', models.JSONField(blank=True, default=dict)),
                ('after_json', models.JSONField(blank=True, default=dict)),
                ('changed_fields', models.JSONField(blank=True, default=list)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.TextField(blank=True)),
                ('extra', models.JSONField(blank=True, default=dict)),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('content_type', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='audit_logs',
                    to='contenttypes.contenttype',
                )),
                ('user', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='audit_logs',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Log de auditoría',
                'verbose_name_plural': 'Logs de auditoría',
                'db_table': 'core_audit_log',
                'ordering': ['-timestamp'],
                'indexes': [
                    models.Index(fields=['content_type', 'object_id', '-timestamp'],
                                 name='audit_ct_obj_ts_idx'),
                    models.Index(fields=['user', '-timestamp'],
                                 name='audit_user_ts_idx'),
                    models.Index(fields=['action', '-timestamp'],
                                 name='audit_action_ts_idx'),
                ],
            },
        ),
    ]
