"""
D1 — Consolidación de los alias legacy de market_type.

Distintos fetchers escribían valores distintos para el mismo concepto:
  · 'parallel'  (PARALELO_EST, scraper de mercado paralelo)
  · 'digital'   (DIGITAL_EST — Takenos/Airtm)
ambos son, semánticamente, el mercado *paralelo digital*. Conviven con el valor
canónico 'paralelo_digital', rompiendo la agregación y el cálculo de brecha.

Esta data migration consolida TODO el histórico a 'paralelo_digital' y luego
actualiza los CHOICES del modelo (los alias dejan de ser válidos). Los fetchers
ya fueron modificados para escribir el valor canónico.

Nota de integridad: unique_together incluye rate_source, que es NULL en el 100%
de las filas alias → en Postgres los NULL son distintos en el índice único, así
que el UPDATE no puede violar la restricción.
"""
from django.db import migrations, models

_ALIASES = ('parallel', 'digital')
_CANONICAL = 'paralelo_digital'


def consolidate_forward(apps, schema_editor):
    ExchangeRate = apps.get_model('rates', 'ExchangeRate')
    updated = (ExchangeRate.objects
               .filter(market_type__in=_ALIASES)
               .update(market_type=_CANONICAL))
    schema_editor.connection.ops  # touch to keep linters quiet
    print(f'  [D1] market_type alias consolidados → paralelo_digital: {updated} filas')


def consolidate_reverse(apps, schema_editor):
    # Irreversible sin ambigüedad (no se puede saber qué fila era 'parallel' vs
    # 'digital'). No-op para permitir revertir el AlterField sin perder datos.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0023_alter_exchangerate_market_type_and_more'),
    ]

    operations = [
        migrations.RunPython(consolidate_forward, consolidate_reverse),
        migrations.AlterField(
            model_name='exchangerate',
            name='market_type',
            field=models.CharField(
                choices=[
                    ('official', 'Oficial (BCB)'),
                    ('paralelo_digital', 'Paralelo Digital (Binance/Takenos/Airtm)'),
                    ('paralelo_fisico_empresa', 'Paralelo Físico — Empresa'),
                    ('paralelo_fisico_competencia', 'Paralelo Físico — Competencia'),
                ],
                db_index=True,
                default='paralelo_digital',
                help_text='Tipo de mercado que representa esta tasa.',
                max_length=30,
            ),
        ),
    ]
