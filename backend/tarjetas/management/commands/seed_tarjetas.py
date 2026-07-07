# tarjetas/management/commands/seed_tarjetas.py
"""
Carga datos iniciales del módulo de tarjetas telefónicas:
  - 3 operadoras bolivianas: Tigo, Entel, Viva
  - Denominaciones 5, 10, 20, 50, 100 BOB para recargas de cada operadora
  - Alertas de inventario mínimo globales para cada tipo

Uso:
    python manage.py seed_tarjetas
    python manage.py seed_tarjetas --reset   # borra y recrea todo
"""
from django.core.management.base import BaseCommand
from django.db import transaction


OPERADORAS = [
    {'codigo': 'TIGO',  'nombre': 'Tigo',  'color': '#00A8E0'},
    {'codigo': 'ENTEL', 'nombre': 'Entel', 'color': '#FFB300'},
    {'codigo': 'VIVA',  'nombre': 'Viva',  'color': '#E50914'},
]

DENOMINACIONES = [
    {'valor': '5.00',  'tipo': 'RECARGA', 'stock_min': 30, 'stock_crit': 10},
    {'valor': '10.00', 'tipo': 'RECARGA', 'stock_min': 25, 'stock_crit': 8},
    {'valor': '20.00', 'tipo': 'RECARGA', 'stock_min': 20, 'stock_crit': 5},
    {'valor': '50.00', 'tipo': 'RECARGA', 'stock_min': 15, 'stock_crit': 4},
    {'valor': '100.00','tipo': 'RECARGA', 'stock_min': 10, 'stock_crit': 3},
]


class Command(BaseCommand):
    help = 'Carga operadoras bolivianas y tipos de tarjeta con alertas de inventario'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Elimina todos los tipos existentes antes de crear los nuevos',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from tarjetas.models import TipoTarjeta, AlertaInventarioTarjeta

        if options['reset']:
            deleted, _ = TipoTarjeta.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'  Eliminados {deleted} tipos existentes'))

        tipos_creados    = 0
        tipos_existentes = 0
        alertas_creadas  = 0

        for op in OPERADORAS:
            self.stdout.write(f'\n  Operadora: {op["nombre"]} ({op["codigo"]})')

            for den in DENOMINACIONES:
                nombre = f"{op['nombre']} {den['valor'].rstrip('0').rstrip('.')} BOB"
                tipo, created = TipoTarjeta.objects.get_or_create(
                    operadora    = op['codigo'],
                    denominacion = den['valor'],
                    defaults={
                        'nombre':      nombre,
                        'descripcion': f"Recarga prepago {op['nombre']} de Bs. {den['valor']}",
                        'is_active':   True,
                    },
                )

                if created:
                    tipos_creados += 1
                    self.stdout.write(f'    + {tipo.nombre}')
                else:
                    tipos_existentes += 1
                    self.stdout.write(f'    ~ {tipo.nombre} (ya existe)')

                alerta, alerta_created = AlertaInventarioTarjeta.objects.get_or_create(
                    tipo_tarjeta = tipo,
                    branch       = None,
                    defaults={
                        'stock_minimo':  den['stock_min'],
                        'stock_critico': den['stock_crit'],
                        'is_active':     True,
                    },
                )
                if alerta_created:
                    alertas_creadas += 1

        self.stdout.write('\n' + self.style.SUCCESS(
            f'Seed completado: '
            f'{tipos_creados} tipos creados, '
            f'{tipos_existentes} existentes, '
            f'{alertas_creadas} alertas configuradas.'
        ))
