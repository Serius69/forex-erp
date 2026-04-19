from django.core.management.base import BaseCommand
from rates.models import Currency


CURRENCIES = [
    # code   name_en                          name_es                              symbol  scale  use_rate  is_base
    ('BOB',  'Bolivian Boliviano',            'Boliviano',                         'Bs',   1,     False,    True),
    ('USD',  'US Dollar',                     'Dólar estadounidense',               '$',    1,     True,     False),
    ('EUR',  'Euro',                          'Euro',                              '€',    1,     True,     False),
    ('GBP',  'British Pound',                 'Libra esterlina',                   '£',    1,     True,     False),
    ('BRL',  'Brazilian Real',                'Real brasileño',                    'R$',   1,     True,     False),
    ('ARS',  'Argentine Peso',                'Peso argentino',                    '$',    1000,  True,     False),
    ('CLP',  'Chilean Peso',                  'Peso chileno',                      '$',    1000,  True,     False),
    ('PEN',  'Peruvian Sol',                  'Sol peruano',                       'S/',   1,     True,     False),
    ('COP',  'Colombian Peso',                'Peso colombiano',                   '$',    1000,  True,     False),
    ('JPY',  'Japanese Yen',                  'Yen japonés',                       '¥',    1,     True,     False),
    ('CNY',  'Chinese Yuan',                  'Yuan chino',                        '¥',    1,     True,     False),
    ('AUD',  'Australian Dollar',             'Dólar australiano',                 'A$',   1,     True,     False),
]


class Command(BaseCommand):
    help = 'Seed standard currencies. Safe to re-run (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Overwrite name/symbol/scale on existing records.',
        )

    def handle(self, *args, **options):
        reset = options['reset']
        created_count  = 0
        updated_count  = 0

        for code, name_en, name_es, symbol, scale, use_rate, is_base in CURRENCIES:
            obj, created = Currency.objects.get_or_create(
                code=code,
                defaults=dict(
                    name_en=name_en,
                    name_es=name_es,
                    symbol=symbol,
                    scale_factor=scale,
                    use_exchange_rate=use_rate,
                    is_base_currency=is_base,
                    is_active=True,
                ),
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  ✓ Creada: {code} — {name_es}'))
            elif reset:
                obj.name_en           = name_en
                obj.name_es           = name_es
                obj.symbol            = symbol
                obj.scale_factor      = scale
                obj.use_exchange_rate = use_rate
                obj.is_base_currency  = is_base
                obj.is_active         = True
                obj.save()
                updated_count += 1
                self.stdout.write(f'  ↻ Actualizada: {code}')
            else:
                self.stdout.write(f'  · Existente:  {code}')

        self.stdout.write(
            self.style.SUCCESS(
                f'\nSeed completado: {created_count} creadas, {updated_count} actualizadas.'
            )
        )
