# Aislamiento multi-tenant de InventoryCard: antes cualquier usuario
# autenticado listaba las tarjetas de inventario de TODAS las empresas.
# Las filas existentes se asignan a la empresa activa más antigua.
from django.db import migrations, models
import django.db.models.deletion


def backfill_company(apps, schema_editor):
    InventoryCard = apps.get_model('inventory', 'InventoryCard')
    Company       = apps.get_model('tenants', 'Company')
    default = Company.objects.filter(is_active=True).order_by('id').first()
    if default is not None:
        InventoryCard.objects.filter(company__isnull=True).update(company=default)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0001_initial'),
        ('inventory', '0005_inventory_card'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventorycard',
            name='company',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='inventory_cards', to='tenants.company',
            ),
        ),
        migrations.RunPython(backfill_company, noop),
    ]
