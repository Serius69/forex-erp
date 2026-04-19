"""
Migration: convert amount_from and amount_to from DecimalField to IntegerField.

Strategy:
  - Existing decimal values are ROUNDED to the nearest integer before the
    column type changes (ROUND applied at the database level via USING clause).
  - SeparateDatabaseAndState is used so Django's migration state is updated
    without attempting a second ALTER after RunSQL already changed the column.
  - Reverse migration restores NUMERIC(18,4) columns (data precision cannot
    be recovered after conversion, but the schema is fully reversible).
"""
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0009_alter_transaction_amount_max_digits'),
    ]

    operations = [
        # ── 1. Coerce existing decimal data → integer (ROUND) at DB level ────
        migrations.RunSQL(
            sql="""
                ALTER TABLE transactions_transaction
                    ALTER COLUMN amount_from
                    TYPE INTEGER USING ROUND(amount_from)::INTEGER;

                ALTER TABLE transactions_transaction
                    ALTER COLUMN amount_to
                    TYPE INTEGER USING ROUND(amount_to)::INTEGER;
            """,
            reverse_sql="""
                ALTER TABLE transactions_transaction
                    ALTER COLUMN amount_from
                    TYPE NUMERIC(18,4) USING amount_from::NUMERIC(18,4);

                ALTER TABLE transactions_transaction
                    ALTER COLUMN amount_to
                    TYPE NUMERIC(18,4) USING amount_to::NUMERIC(18,4);
            """,
        ),

        # ── 2. Update Django ORM state only (DB already altered above) ───────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='transaction',
                    name='amount_from',
                    field=models.IntegerField(
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                migrations.AlterField(
                    model_name='transaction',
                    name='amount_to',
                    field=models.IntegerField(
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
            ],
            database_operations=[],  # already done by RunSQL above
        ),
    ]
