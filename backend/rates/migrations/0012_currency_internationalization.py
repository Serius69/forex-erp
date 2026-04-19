from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0011_remove_exchangerate_rates_excha_is_prim_idx_and_more'),
    ]

    operations = [
        # 1. Rename existing 'name' → 'name_en'
        migrations.RenameField(
            model_name='currency',
            old_name='name',
            new_name='name_en',
        ),
        # 2. Widen code field (3→10) and name_en (50→100)
        migrations.AlterField(
            model_name='currency',
            name='code',
            field=models.CharField(max_length=10, unique=True),
        ),
        migrations.AlterField(
            model_name='currency',
            name='name_en',
            field=models.CharField(max_length=100, verbose_name='Name (EN)'),
        ),
        migrations.AlterField(
            model_name='currency',
            name='symbol',
            field=models.CharField(max_length=10),
        ),
        migrations.AlterField(
            model_name='currency',
            name='is_active',
            field=models.BooleanField(default=True, db_index=True),
        ),
        # 3. New fields
        migrations.AddField(
            model_name='currency',
            name='name_es',
            field=models.CharField(blank=True, max_length=100, verbose_name='Nombre (ES)'),
        ),
        migrations.AddField(
            model_name='currency',
            name='use_exchange_rate',
            field=models.BooleanField(
                default=True,
                help_text='True → usa tasas de cambio. False → valor fijo (efectivo directo).',
            ),
        ),
        migrations.AddField(
            model_name='currency',
            name='is_base_currency',
            field=models.BooleanField(
                default=False,
                help_text='Solo UNA divisa puede ser la base. Normalmente BOB.',
            ),
        ),
        migrations.AddField(
            model_name='currency',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
    ]
