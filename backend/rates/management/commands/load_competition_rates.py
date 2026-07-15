"""
Puebla la serie de tasas de COMPETENCIA (market_type='paralelo_fisico_competencia').

Dos fuentes de datos reales:

1. Reetiqueta las filas físicas de mercado ya cargadas que estaban en el slot
   'paralelo_fisico_empresa' pero que en realidad son la tasa física del
   mercado/competencia (source 'tipos de cambio fisico mercado (historico)' y su
   relleno LOCF). Ese slot 'empresa' se reserva para la tasa efectiva derivada de
   las transacciones propias (ver `derive_empresa_rates`).

2. (Opcional) Carga idempotente desde el CSV real de mercado físico
   `tipos de cambio fisico mercado.csv` (Divisa,Fecha,Nro,TC,Tipo) pivotando
   Compra/Venta → buy_rate/sell_rate.

Idempotente: se puede correr múltiples veces.

Uso:
    python manage.py load_competition_rates
    python manage.py load_competition_rates --csv /ruta/tipos\\ de\\ cambio\\ fisico\\ mercado.csv
"""
import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from rates.models import Currency, ExchangeRate

COMPETENCIA = 'paralelo_fisico_competencia'
# Fuentes que fueron mal clasificadas como 'empresa' pero son físico de mercado.
MISLABELED_SOURCES = (
    'tipos de cambio fisico mercado (historico)',
    'ESTIMADO_LOCF',
)


class Command(BaseCommand):
    help = 'Puebla paralelo_fisico_competencia (reetiqueta físico de mercado + carga CSV)'

    def add_arguments(self, parser):
        parser.add_argument('--csv', type=str, default=None,
                            help='Ruta al CSV de tipos de cambio físico de mercado.')

    def handle(self, *args, **opts):
        relabeled = self._relabel_mislabeled()
        self.stdout.write(self.style.SUCCESS(
            f'Reetiquetadas {relabeled} tasas físico-mercado → {COMPETENCIA}'))

        if opts['csv']:
            created, updated = self._load_csv(opts['csv'])
            self.stdout.write(self.style.SUCCESS(
                f'CSV: {created} creadas, {updated} actualizadas'))

        # La serie histórica se carga por fecha; deja vigente solo la más reciente
        # por (divisa, mercado) y cierra el resto con intervalos contiguos.
        from rates.rate_expiry import expire_stale_active_rates
        closed = expire_stale_active_rates(market_type=COMPETENCIA)
        if closed:
            self.stdout.write(self.style.SUCCESS(
                f'Normalizadas {closed} tasas históricas (una vigente por divisa)'))

        total = ExchangeRate.objects.filter(market_type=COMPETENCIA).count()
        self.stdout.write(self.style.SUCCESS(
            f'TOTAL tasas de competencia en BD: {total}'))

    # ──────────────────────────────────────────────────────────────────────────
    @db_transaction.atomic
    def _relabel_mislabeled(self) -> int:
        """Mueve las filas físico-de-mercado del slot empresa → competencia."""
        qs = ExchangeRate.objects.filter(
            market_type='paralelo_fisico_empresa',
            source__in=MISLABELED_SOURCES,
        )
        # .update() evita full_clean()/save() (no hay colisión: 0 competencia previas
        # y el unique_together incluye market_type).
        return qs.update(market_type=COMPETENCIA)

    # ──────────────────────────────────────────────────────────────────────────
    def _load_csv(self, path: str):
        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            self.stderr.write(self.style.ERROR('No existe la moneda BOB — corre seed_currencies'))
            return 0, 0

        currencies = {c.code: c for c in Currency.objects.all()}

        # Pivot: (divisa, fecha) → {'Compra': tc, 'Venta': tc}
        rows = defaultdict(dict)
        with open(path, encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh):
                divisa = (r.get('Divisa') or '').strip().upper()
                tipo = (r.get('Tipo') or '').strip().lower()
                fecha_raw = (r.get('Fecha') or '').strip()
                try:
                    tc = Decimal(str(r.get('TC')).replace(',', '.'))
                except (InvalidOperation, TypeError):
                    continue
                if not divisa or tc <= 0:
                    continue
                fecha = self._parse_date(fecha_raw)
                if fecha is None:
                    continue
                key = (divisa, fecha)
                if tipo.startswith('compra'):
                    rows[key]['buy'] = tc
                elif tipo.startswith('venta'):
                    rows[key]['sell'] = tc

        created = updated = 0
        for (divisa, fecha), v in rows.items():
            cur = currencies.get(divisa)
            if cur is None:
                continue
            buy = v.get('buy')
            sell = v.get('sell')
            # Necesitamos ambos lados y buy<=sell para pasar el clean() del modelo.
            if buy is None or sell is None:
                # completar el faltante con el presente (spread 0) para no perder el punto
                buy = sell = buy or sell
            if buy is None or sell is None or buy <= 0 or sell <= 0:
                continue
            if buy > sell:
                buy, sell = sell, buy
            valid_from = timezone.make_aware(
                datetime.combine(fecha, datetime.min.time())
            ) if timezone.is_naive(datetime.combine(fecha, datetime.min.time())) else datetime.combine(fecha, datetime.min.time())

            obj, was_created = ExchangeRate.objects.update_or_create(
                currency_from=cur,
                currency_to=bob,
                valid_from=valid_from,
                market_type=COMPETENCIA,
                rate_source=None,
                defaults={
                    'official_rate': (buy + sell) / 2,
                    'buy_rate': buy,
                    'sell_rate': sell,
                    'avg_rate': (buy + sell) / 2,
                    'source': 'tipos de cambio fisico mercado (competencia)',
                    'source_method': 'SCRAP',
                    'confidence': Decimal('0.80'),
                },
            )
            created += int(was_created)
            updated += int(not was_created)
        return created, updated

    @staticmethod
    def _parse_date(raw: str):
        raw = raw.split(' ')[0]  # descarta la hora si viene
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None
