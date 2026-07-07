# Migration: CashBOB — denomination-level BOB cash tracking.
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('capital', '0006_rename_capital_cashflow_branch_fecha_idx_capital_cas_branch__153b0d_idx_and_more'),
        ('users', '0002_alter_branch_options_alter_user_options'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CashBOB',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                )),
                ('fecha', models.DateField(default=django.utils.timezone.localdate)),
                # ── Fuertes ───────────────────────────────────────────────────
                ('fuertes_200', models.PositiveIntegerField(
                    default=0, help_text='Cantidad de billetes de 200 Bs'
                )),
                ('fuertes_100', models.PositiveIntegerField(
                    default=0, help_text='Cantidad de billetes de 100 Bs'
                )),
                ('fuertes_50', models.PositiveIntegerField(
                    default=0, help_text='Cantidad de billetes de 50 Bs'
                )),
                # ── Sueltos ───────────────────────────────────────────────────
                ('sueltos_20', models.PositiveIntegerField(
                    default=0, help_text='Cantidad de billetes de 20 Bs'
                )),
                ('sueltos_10', models.PositiveIntegerField(
                    default=0, help_text='Cantidad de billetes de 10 Bs'
                )),
                # ── Caja chica ────────────────────────────────────────────────
                ('caja_chica_200', models.PositiveIntegerField(default=0)),
                ('caja_chica_100', models.PositiveIntegerField(default=0)),
                ('caja_chica_50',  models.PositiveIntegerField(default=0)),
                ('caja_chica_20',  models.PositiveIntegerField(default=0)),
                ('caja_chica_10',  models.PositiveIntegerField(default=0)),
                # ── Digital ───────────────────────────────────────────────────
                ('qr_transferencias', models.DecimalField(
                    decimal_places=2, default=Decimal('0'), max_digits=15,
                    help_text='Saldo en billeteras QR / transferencias bancarias',
                )),
                # ── Auditoría ─────────────────────────────────────────────────
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='cash_bob_entries',
                    to='users.branch',
                )),
                ('registrado_por', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='cash_bob_entries',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name':        'Caja BOB',
                'verbose_name_plural': 'Cajas BOB',
                'db_table':            'capital_cash_bob',
                'ordering':            ['-fecha', '-updated_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='cashbob',
            constraint=models.UniqueConstraint(
                fields=['branch', 'fecha'],
                name='capital_cashbob_branch_fecha_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='cashbob',
            index=models.Index(
                fields=['branch', '-fecha'],
                name='capital_cashbob_branch_fecha_idx',
            ),
        ),
    ]
