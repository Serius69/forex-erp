# Aislamiento multi-tenant del módulo de tarjetas.
#
# Antes TipoTarjeta era un catálogo GLOBAL: cualquier empresa veía (y por el
# FIFO de ventas, consumía) los lotes de las demás. Se añade company y se
# asignan los tipos existentes a la empresa activa más antigua (la única real
# en producción; era además la misma a la que el signup auto-unía usuarios).
from django.db import migrations, models
import django.db.models.deletion


def backfill_company(apps, schema_editor):
    TipoTarjeta = apps.get_model('tarjetas', 'TipoTarjeta')
    Company     = apps.get_model('tenants', 'Company')
    default = Company.objects.filter(is_active=True).order_by('id').first()
    if default is not None:
        TipoTarjeta.objects.filter(company__isnull=True).update(company=default)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0001_initial'),
        ('tarjetas', '0005_add_estado_venta_alerta_inventario'),
    ]

    operations = [
        migrations.AddField(
            model_name='tipotarjeta',
            name='company',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='tipos_tarjeta', to='tenants.company',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='tipotarjeta',
            unique_together={('company', 'operadora', 'denominacion')},
        ),
        migrations.AddIndex(
            model_name='tipotarjeta',
            index=models.Index(fields=['company', 'is_active'], name='tarjetas_ti_company_9f3a1c_idx'),
        ),
        migrations.RunPython(backfill_company, noop),
    ]
