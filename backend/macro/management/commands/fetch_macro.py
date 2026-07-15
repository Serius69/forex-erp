"""
Carga/actualiza los indicadores macro de Bolivia.

    python manage.py fetch_macro            # todo (World Bank histórico + diarios)
    python manage.py fetch_macro --daily    # solo USD internacional + brecha
    python manage.py fetch_macro --wb       # solo World Bank
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Extrae indicadores macro reales de Bolivia (World Bank, er-api, brecha).'

    def add_arguments(self, parser):
        parser.add_argument('--daily', action='store_true', help='Solo series diarias.')
        parser.add_argument('--wb', action='store_true', help='Solo World Bank (anual).')

    def handle(self, *args, **opts):
        from macro.fetchers import (
            compute_brecha_oficial, fetch_usd_internacional,
            fetch_world_bank, persist_points,
        )
        from macro.models import MacroIndicator

        do_all = not (opts['daily'] or opts['wb'])
        total = 0

        if opts['wb'] or do_all:
            n = persist_points(fetch_world_bank())
            self.stdout.write(self.style.SUCCESS(f'World Bank: {n} puntos'))
            total += n

        if opts['daily'] or do_all:
            n = persist_points(fetch_usd_internacional() + compute_brecha_oficial())
            self.stdout.write(self.style.SUCCESS(f'Diarios (USD intl + brecha): {n} puntos'))
            total += n

        self.stdout.write(self.style.SUCCESS(
            f'Total guardado: {total} · filas en BD: {MacroIndicator.objects.count()}'))
        for series, _ in MacroIndicator.SERIES_CHOICES:
            row = MacroIndicator.latest(series)
            if row:
                self.stdout.write(f'  {series:22} último: {row.date} = {row.value} {row.unit}')
