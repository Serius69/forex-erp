"""
Migration 0009 — Traceability fields for ExchangeRate.

Adds:
  - source_method  (ENUM: API / SCRAP / MANUAL / INFERENCE)
  - source_url     (nullable URL)
  - fetched_at     (nullable datetime)
  - created_by     (nullable FK → users.User)
  - is_validated   (bool, default False)
  - confidence     (Decimal 0-1, default 1.000)
  + two new indexes: source_method + is_validated

Rationale: every rate stored must include its origin method and provenance
so that financial audits can trace exactly how each rate was obtained.
"""
from __future__ import annotations
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0008_rename_rates_pricin_curr_cd_idx_rates_prici_currenc_95f50a_idx_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── source_method ─────────────────────────────────────────────────────
        migrations.AddField(
            model_name='exchangerate',
            name='source_method',
            field=models.CharField(
                choices=[
                    ('API',       'API externa — dato en tiempo real'),
                    ('SCRAP',     'Web scraping — HTML o JSON parseado'),
                    ('MANUAL',    'Ingreso manual — operador/administrador'),
                    ('INFERENCE', 'Inferido/estimado — sin fuente directa verificable'),
                ],
                default='SCRAP',
                db_index=True,
                max_length=10,
                help_text='Método por el que se obtuvo la tasa: API, SCRAP, MANUAL o INFERENCE.',
            ),
        ),

        # ── source_url ────────────────────────────────────────────────────────
        migrations.AddField(
            model_name='exchangerate',
            name='source_url',
            field=models.URLField(
                blank=True, null=True,
                help_text='URL exacta de donde se obtuvo el dato (para auditoría).',
            ),
        ),

        # ── fetched_at ────────────────────────────────────────────────────────
        migrations.AddField(
            model_name='exchangerate',
            name='fetched_at',
            field=models.DateTimeField(
                blank=True, null=True,
                help_text='Momento en que se consultó la fuente externa.',
            ),
        ),

        # ── created_by ────────────────────────────────────────────────────────
        migrations.AddField(
            model_name='exchangerate',
            name='created_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='rates_created',
                to=settings.AUTH_USER_MODEL,
                help_text='Usuario que creó la tasa (null = proceso automático).',
            ),
        ),

        # ── is_validated ──────────────────────────────────────────────────────
        migrations.AddField(
            model_name='exchangerate',
            name='is_validated',
            field=models.BooleanField(
                default=False,
                help_text='True si un administrador verificó y aprobó esta tasa.',
            ),
        ),

        # ── confidence ────────────────────────────────────────────────────────
        migrations.AddField(
            model_name='exchangerate',
            name='confidence',
            field=models.DecimalField(
                default=Decimal('1.000'),
                max_digits=4, decimal_places=3,
                help_text='Confianza 0.000–1.000 heredada del fetcher.',
            ),
        ),

        # ── Indexes ───────────────────────────────────────────────────────────
        migrations.AddIndex(
            model_name='exchangerate',
            index=models.Index(
                fields=['source_method', 'currency_from', '-valid_from'],
                name='rates_excha_src_mth_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='exchangerate',
            index=models.Index(
                fields=['is_validated', 'source_method'],
                name='rates_excha_validated_idx',
            ),
        ),

        # ── Backfill: mark existing rates as SCRAP (best-effort) ─────────────
        # USD BCB official rates are historically stable API/SCRAP; we default
        # everything to SCRAP since that was the primary collection method.
        migrations.RunSQL(
            sql="UPDATE rates_exchangerate SET source_method = 'SCRAP' WHERE source_method = 'SCRAP'",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
