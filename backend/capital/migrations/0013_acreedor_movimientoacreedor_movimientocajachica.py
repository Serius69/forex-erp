from decimal import Decimal

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_rename_users_branch_company_active_idx_users_branc_company_058b1d_idx_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('capital', '0012_ingresoextra'),
    ]

    operations = [
        migrations.CreateModel(
            name='Acreedor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=200)),
                ('moneda', models.CharField(choices=[('BOB', 'Bolivianos'), ('USD', 'Dólares')], default='BOB', help_text='Moneda en que se lleva la deuda con este acreedor.', max_length=3)),
                ('documento', models.CharField(blank=True, help_text='NIT/CI (opcional).', max_length=50)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('notas', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='acreedores', to='users.branch')),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Acreedor',
                'verbose_name_plural': 'Acreedores',
                'ordering': ['nombre'],
            },
        ),
        migrations.CreateModel(
            name='MovimientoCajaChica',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(default=django.utils.timezone.localdate)),
                ('tipo', models.CharField(choices=[('APERTURA', 'Apertura / corte inicial'), ('INGRESO', 'Ingreso / reposición'), ('EGRESO', 'Egreso / gasto')], default='EGRESO', max_length=8)),
                ('monto_bob', models.DecimalField(decimal_places=2, max_digits=18, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('concepto', models.CharField(max_length=300)),
                ('notas', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='movimientos_caja_chica', to='users.branch')),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Movimiento de caja chica',
                'verbose_name_plural': 'Movimientos de caja chica',
                'ordering': ['-fecha', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MovimientoAcreedor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(default=django.utils.timezone.localdate)),
                ('tipo', models.CharField(choices=[('CARGO', 'Cargo — nueva deuda'), ('ABONO', 'Abono — pago al acreedor')], max_length=6)),
                ('monto_bob', models.DecimalField(decimal_places=2, max_digits=18, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('monto_divisa', models.DecimalField(blank=True, decimal_places=2, help_text='Monto en la moneda del acreedor si es ≠ BOB.', max_digits=18, null=True)),
                ('concepto', models.CharField(blank=True, max_length=300)),
                ('notas', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('acreedor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='movimientos', to='capital.acreedor')),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Movimiento de acreedor',
                'verbose_name_plural': 'Movimientos de acreedores',
                'ordering': ['-fecha', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='acreedor',
            index=models.Index(fields=['branch', 'is_active'], name='capital_acr_branch__b3f6d1_idx'),
        ),
        migrations.AddIndex(
            model_name='movimientocajachica',
            index=models.Index(fields=['branch', '-fecha'], name='capital_ccc_branch__a1e2c3_idx'),
        ),
        migrations.AddIndex(
            model_name='movimientocajachica',
            index=models.Index(fields=['tipo', '-fecha'], name='capital_ccc_tipo_fe_d4f5a6_idx'),
        ),
        migrations.AddIndex(
            model_name='movimientoacreedor',
            index=models.Index(fields=['acreedor', '-fecha'], name='capital_mov_acreed_e7a8b9_idx'),
        ),
        migrations.AddIndex(
            model_name='movimientoacreedor',
            index=models.Index(fields=['tipo', '-fecha'], name='capital_mov_tipo_fe_c1d2e3_idx'),
        ),
    ]
