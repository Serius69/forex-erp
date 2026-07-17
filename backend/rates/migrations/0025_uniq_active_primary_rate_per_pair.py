"""
D2 — Constraint: a lo sumo UNA tasa primaria activa por par.

`mark_primary_rates_task` marcaba la primaria con dos UPDATE no atómicos, así que
un solape podía dejar 0 o 2 `is_primary=True` activas (valid_until IS NULL) para
el mismo par. Este constraint parcial lo garantiza a nivel de BD.

Diagnóstico en prod (2026-07-17): 0 pares con dup → el constraint aplica limpio.
Aun así, la data migration previa degrada defensivamente cualquier dup que
pudiera aparecer entre este diagnóstico y el apply (deja como primaria la de mayor
confianza y, a igualdad, la más reciente), para que AddConstraint nunca falle.
"""
from django.db import migrations, models
from django.db.models import Q


def _resolve_primary_dups(apps, schema_editor):
    ExchangeRate = apps.get_model('rates', 'ExchangeRate')
    from django.db.models import Count
    dup_pairs = (
        ExchangeRate.objects
        .filter(is_primary=True, valid_until__isnull=True)
        .values('currency_from', 'currency_to')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
    )
    for row in dup_pairs:
        rows = list(
            ExchangeRate.objects
            .filter(is_primary=True, valid_until__isnull=True,
                    currency_from=row['currency_from'],
                    currency_to=row['currency_to'])
            .order_by('-confidence', '-valid_from')
        )
        # conserva la primera (mayor confianza / más reciente), degrada el resto
        for r in rows[1:]:
            r.is_primary = False
            r.save(update_fields=['is_primary'])


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0024_consolidate_market_type_aliases'),
    ]

    operations = [
        migrations.RunPython(_resolve_primary_dups, _noop_reverse),
        migrations.AddConstraint(
            model_name='exchangerate',
            constraint=models.UniqueConstraint(
                fields=['currency_from', 'currency_to'],
                condition=Q(is_primary=True, valid_until__isnull=True),
                name='uniq_active_primary_rate_per_pair',
            ),
        ),
    ]
