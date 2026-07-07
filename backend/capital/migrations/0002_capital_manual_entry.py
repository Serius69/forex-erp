# Generated manually 2026-04-07 — CapitalManualEntry + CapitalEntryHistory

from decimal import Decimal
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('capital', '0001_initial'),
        ('users',   '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CapitalManualEntry',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha',       models.DateField(default=django.utils.timezone.localdate)),
                ('efectivo_bob',models.DecimalField(decimal_places=2, default=Decimal('0'), help_text='Efectivo físico en caja BOB', max_digits=18)),
                ('qr_bob',      models.DecimalField(decimal_places=2, default=Decimal('0'), help_text='Saldo en billeteras QR / cuentas digitales BOB', max_digits=18)),
                ('pasivos_bob', models.DecimalField(decimal_places=2, default=Decimal('0'), help_text='Deudas / obligaciones a pagar en BOB', max_digits=18)),
                ('notas',       models.TextField(blank=True)),
                ('created_at',  models.DateTimeField(auto_now_add=True)),
                ('updated_at',  models.DateTimeField(auto_now=True)),
                ('branch',      models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='capital_manual_entries', to='users.branch')),
                ('registrado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='capital_entries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name':        'Entrada Manual de Capital',
                'verbose_name_plural': 'Entradas Manuales de Capital',
                'db_table':            'capital_manual_entry',
                'ordering':            ['-fecha', '-updated_at'],
                'unique_together':     {('branch', 'fecha')},
            },
        ),
        migrations.AddIndex(
            model_name='capitalmanualentry',
            index=models.Index(fields=['branch', '-fecha'], name='capital_man_branch_fecha_idx'),
        ),
        migrations.CreateModel(
            name='CapitalEntryHistory',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('efectivo_bob_prev',models.DecimalField(decimal_places=2, max_digits=18)),
                ('qr_bob_prev',      models.DecimalField(decimal_places=2, max_digits=18)),
                ('pasivos_bob_prev', models.DecimalField(decimal_places=2, max_digits=18)),
                ('efectivo_bob_new', models.DecimalField(decimal_places=2, max_digits=18)),
                ('qr_bob_new',       models.DecimalField(decimal_places=2, max_digits=18)),
                ('pasivos_bob_new',  models.DecimalField(decimal_places=2, max_digits=18)),
                ('motivo',           models.CharField(blank=True, max_length=300)),
                ('created_at',       models.DateTimeField(auto_now_add=True)),
                ('entry',            models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='history', to='capital.capitalmanualentry')),
                ('modificado_por',   models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name':        'Historial de Capital',
                'verbose_name_plural': 'Historial de Capital',
                'db_table':            'capital_entry_history',
                'ordering':            ['-created_at'],
            },
        ),
    ]
