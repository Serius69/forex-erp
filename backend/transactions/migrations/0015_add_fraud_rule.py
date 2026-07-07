from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0014_add_transaction_audit_log'),
    ]

    operations = [
        migrations.CreateModel(
            name='FraudRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100, unique=True)),
                ('rule_type', models.CharField(
                    max_length=20,
                    choices=[
                        ('VELOCITY',       'Velocidad de transacciones (por hora)'),
                        ('AMOUNT_ANOMALY', 'Anomalía de monto (σ desviaciones)'),
                        ('RATE_SANITY',    'Sanidad de tasa vs paralela (%)'),
                        ('DUPLICATE',      'Detección de duplicados (minutos)'),
                        ('BLACKLIST',      'Lista negra / PEP'),
                        ('HIGH_VALUE',     'Monto alto en BOB'),
                    ],
                    db_index=True,
                )),
                ('threshold', models.DecimalField(max_digits=12, decimal_places=4)),
                ('decision', models.CharField(
                    max_length=20,
                    choices=[
                        ('APPROVE',          'Aprobar'),
                        ('REQUIRE_APPROVAL', 'Requiere aprobación'),
                        ('BLOCK',            'Bloquear'),
                    ],
                    default='REQUIRE_APPROVAL',
                )),
                ('score_delta', models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.3000'))),
                ('is_active', models.BooleanField(default=True, db_index=True)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'transaction_fraud_rule',
                'ordering': ['rule_type', 'name'],
                'verbose_name': 'Regla Anti-Fraude',
                'verbose_name_plural': 'Reglas Anti-Fraude',
            },
        ),
        # Seed con reglas por defecto sensatas para una casa de cambio boliviana
        migrations.RunSQL(
            sql="""
            INSERT INTO transaction_fraud_rule
                (name, rule_type, threshold, decision, score_delta, is_active, description, created_at, updated_at)
            VALUES
                ('Velocidad cajero (10/h)',      'VELOCITY',       10,      'REQUIRE_APPROVAL', 0.3000, TRUE, 'Más de 10 TX por cajero en 1 hora', NOW(), NOW()),
                ('Anomalía monto (3σ)',          'AMOUNT_ANOMALY', 3,       'REQUIRE_APPROVAL', 0.2500, TRUE, 'Monto fuera de 3 desviaciones estándar del cliente', NOW(), NOW()),
                ('Tasa paralela (5%)',           'RATE_SANITY',    5,       'REQUIRE_APPROVAL', 0.3500, TRUE, 'Tasa operada > 5% de la paralela', NOW(), NOW()),
                ('Duplicado (5 min)',            'DUPLICATE',      5,       'BLOCK',            0.6000, TRUE, 'Misma TX en menos de 5 minutos', NOW(), NOW()),
                ('PEP / Lista negra',            'BLACKLIST',      1,       'REQUIRE_APPROVAL', 0.4000, TRUE, 'Cliente es Persona Expuesta Políticamente', NOW(), NOW()),
                ('Monto alto (Bs 100.000)',      'HIGH_VALUE',     100000,  'REQUIRE_APPROVAL', 0.2000, TRUE, 'TX mayor a Bs 100.000', NOW(), NOW()),
                ('Monto crítico (Bs 500.000)',   'HIGH_VALUE',     500000,  'BLOCK',            0.8007, TRUE, 'TX mayor a Bs 500.000 — bloqueo automático', NOW(), NOW());
            """,
            reverse_sql="DELETE FROM transaction_fraud_rule;",
        ),
    ]
