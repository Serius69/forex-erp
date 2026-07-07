from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Company',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Razón social')),
                ('slug', models.SlugField(max_length=80, unique=True)),
                ('tax_id', models.CharField(blank=True, max_length=50, verbose_name='NIT / RUT / CUIT')),
                ('country', models.CharField(
                    choices=[
                        ('BO', 'Bolivia'), ('PE', 'Perú'), ('AR', 'Argentina'),
                        ('CL', 'Chile'), ('BR', 'Brasil'), ('CO', 'Colombia'),
                        ('PY', 'Paraguay'), ('UY', 'Uruguay'), ('OTHER', 'Otro'),
                    ],
                    default='BO', max_length=10,
                )),
                ('base_currency', models.CharField(default='BOB', max_length=10, verbose_name='Moneda base')),
                ('logo_url', models.URLField(blank=True)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Empresa',
                'verbose_name_plural': 'Empresas',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plan', models.CharField(
                    choices=[
                        ('FREE', 'Gratuito'), ('STARTER', 'Starter'),
                        ('GROWTH', 'Growth'), ('ENTERPRISE', 'Enterprise'),
                    ],
                    default='FREE', max_length=20,
                )),
                ('is_active', models.BooleanField(default=True)),
                ('trial_ends', models.DateTimeField(blank=True, null=True)),
                ('max_branches', models.IntegerField(default=1)),
                ('max_users', models.IntegerField(default=5)),
                ('max_transactions_mo', models.IntegerField(default=500)),
                ('billing_email', models.EmailField(blank=True, max_length=254)),
                ('next_billing_date', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='subscription',
                    to='tenants.company',
                )),
            ],
            options={
                'verbose_name': 'Suscripción',
                'verbose_name_plural': 'Suscripciones',
            },
        ),
    ]
