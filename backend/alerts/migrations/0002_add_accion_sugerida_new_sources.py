"""
Migration: add accion_sugerida to AlertLog + expand source choices.

accion_sugerida:
  Texto libre con la acción concreta recomendada para el operador.

Source choices expansion (no DB constraint — CharField only):
  PRECIO, RIESGO, OPERATIVO, OPORTUNIDAD added alongside existing sources.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='alertlog',
            name='accion_sugerida',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Acción concreta recomendada para resolver o aprovechar la alerta.',
            ),
        ),
        # Update source choices to include new AlertGenerator categories.
        # CharField has no DB-level constraint, so this is metadata-only.
        migrations.AlterField(
            model_name='alertlog',
            name='source',
            field=models.CharField(
                max_length=20,
                db_index=True,
                choices=[
                    ('SNAPSHOT',    'Comparación de Snapshot'),
                    ('TRANSACTION', 'Transacción Forex'),
                    ('ANOMALY',     'Detector de Anomalías'),
                    ('SYSTEM',      'Infraestructura del Sistema'),
                    ('INVENTORY',   'Inventario'),
                    ('RATES',       'Tasas de Cambio'),
                    ('PRECIO',      'Movimiento de Precio'),
                    ('RIESGO',      'Riesgo de Mercado'),
                    ('OPERATIVO',   'Operativo'),
                    ('OPORTUNIDAD', 'Oportunidad de Mercado'),
                ],
            ),
        ),
    ]
