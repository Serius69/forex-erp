"""
Normaliza las tasas vigentes: deja una sola activa (valid_until NULL) por
(currency_from, currency_to, market_type, rate_source), cerrando el resto con
intervalos contiguos. Idempotente.

Uso:
    python manage.py expire_stale_rates            # aplica
    python manage.py expire_stale_rates --dry-run  # solo reporta
    python manage.py expire_stale_rates --market paralelo_fisico_competencia
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from rates.models import ExchangeRate
from rates.rate_expiry import expire_stale_active_rates


class Command(BaseCommand):
    help = 'Deja una sola tasa vigente por (divisa, mercado, fuente); cierra las redundantes.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='No modifica nada; solo reporta cuántas se cerrarían.')
        parser.add_argument('--market', default=None,
                            help='Acota a un market_type específico.')

    def handle(self, *args, **opts):
        market = opts.get('market')

        base = ExchangeRate.objects.filter(valid_until__isnull=True)
        if market:
            base = base.filter(market_type=market)

        active_before = base.count()
        groups = (base.values('currency_from_id', 'currency_to_id',
                              'market_type', 'rate_source_id')
                     .annotate(n=Count('id')))
        group_count = len(list(groups))
        redundant = active_before - group_count

        self.stdout.write(
            f'Vigentes actuales: {active_before} · grupos: {group_count} · '
            f'redundantes a cerrar: {redundant}'
        )

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('--dry-run: no se aplicó ningún cambio.'))
            return

        closed = expire_stale_active_rates(market_type=market)

        active_after = ExchangeRate.objects.filter(valid_until__isnull=True)
        if market:
            active_after = active_after.filter(market_type=market)
        self.stdout.write(self.style.SUCCESS(
            f'Cerradas {closed} tasas. Vigentes ahora: {active_after.count()}.'
        ))
