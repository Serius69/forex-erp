"""
import_sheet_rates — backfill del HISTORIAL de tasas del Google Sheet legado
(KapitalyaRegistro2026) hacia rates.ExchangeRate. Sprint 1 de la migración.

Carga las 3 series históricas del sheet, cada una a su market_type:

    empresa      -> paralelo_fisico_empresa   (pestaña "Historial Tasas Empresa")
    web          -> paralelo_digital           (pestaña "Historial Tasas Web")
    competencia  -> paralelo_fisico_competencia(pestaña "Tasas Competencia")

Idempotente: usa update_or_create sobre (currency_from, currency_to, valid_from,
market_type, rate_source=None) — misma clave que load_competition_rates —, con
valid_from = medianoche (TZ local) de la fecha de la fila. Re-correr no duplica.

ENTRADA: un CSV por serie, exportado de la pestaña correspondiente
(File → Download → CSV en Google Sheets, o vía data_migration). Se parsea por
POSICIÓN (no por header) porque los encabezados del sheet son inconsistentes y en
"competencia" hay una columna Promedio SIN etiquetar (7 valores, 6 headers).

Rarezas del sheet ya contempladas:
  - Fecha en DOS formatos en la misma columna: ISO 2026-03-21 y D/M/AAAA 24/4/2026.
  - Números con COMA decimal (9,40) y a veces punto de miles.
  - Divisas variantes ("USD sueltos", "USD 1 y 2", "PEN mon") que NO son Currency
    propios en el ERP -> por defecto se SALTAN con aviso (ver --variantes).

Uso:
    python manage.py import_sheet_rates --series empresa --csv empresa.csv
    python manage.py import_sheet_rates --series web --csv web.csv --dry-run
    python manage.py import_sheet_rates --series competencia --csv comp.csv
"""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from rates.models import Currency, ExchangeRate

SERIES = {
    'empresa':     'paralelo_fisico_empresa',
    'web':         'paralelo_digital',
    'competencia': 'paralelo_fisico_competencia',
}

# Etiqueta del sheet -> código de Currency del ERP.
CURRENCY_MAP = {
    'USD': 'USD', 'EUR': 'EUR', 'BRL': 'BRL',
    'ARS': 'ARS', 'CLP': 'CLP', 'PEN': 'PEN',
}
# Variantes de efectivo del sheet SIN Currency propio en el ERP.
VARIANTS = {'USD sueltos', 'USD 1 y 2', 'PEN mon'}

SOURCE_TAG = 'CARGA_GS_2026'   # marca de trazabilidad (idempotencia por notas/source)


def _parse_date(raw: str):
    """Acepta ISO (2026-03-21) y D/M/AAAA (24/4/2026). Devuelve date o None."""
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_dec(raw: str):
    """Número con coma decimal y posible punto de miles -> Decimal, o None."""
    raw = (raw or '').strip().replace('\\', '')
    if not raw:
        return None
    # 10.000,00 -> 10000.00 ; 9,40 -> 9.40
    raw = raw.replace('.', '').replace(',', '.') if (',' in raw) else raw
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


class Command(BaseCommand):
    help = 'Backfill del historial de tasas del sheet legado a ExchangeRate (idempotente).'

    def add_arguments(self, parser):
        parser.add_argument('--series', required=True, choices=list(SERIES),
                            help='empresa | web | competencia')
        parser.add_argument('--csv', required=True, help='Ruta al CSV exportado de la pestaña.')
        parser.add_argument('--variantes', choices=['skip', 'usd', 'pen'], default='skip',
                            help="Qué hacer con USD sueltos/USD 1 y 2/PEN mon: "
                                 "skip (default) las omite; usd/pen las colapsa a la base.")
        parser.add_argument('--dry-run', action='store_true',
                            help='No escribe: solo reporta qué haría.')

    def handle(self, *args, **opts):
        market_type = SERIES[opts['series']]
        bob = Currency.objects.filter(is_base_currency=True).first() \
            or Currency.objects.filter(code='BOB').first()
        if bob is None:
            raise CommandError('No existe la divisa base (BOB). Corré seed_currencies primero.')

        # Cache de Currency por código.
        cur_by_code = {c.code: c for c in Currency.objects.all()}

        created = updated = skipped_var = skipped_bad = 0
        rows_seen = 0
        with open(opts['csv'], newline='', encoding='utf-8-sig') as fh:
            for row in csv.reader(fh):
                if not row or len(row) < 4:
                    continue
                # Posicional: col0=Fecha, col1=Divisa, col2=Compra, col3=Venta.
                # (En "competencia" col4 es un Promedio sin etiquetar que ignoramos.)
                fecha = _parse_date(row[0])
                divisa = (row[1] or '').strip()
                if fecha is None or not divisa or divisa.lower() == 'divisa':
                    continue  # header o fila basura
                rows_seen += 1

                code = CURRENCY_MAP.get(divisa)
                if code is None:
                    if divisa in VARIANTS:
                        if opts['variantes'] == 'usd' and divisa.startswith('USD'):
                            code = 'USD'
                        elif opts['variantes'] == 'pen' and divisa.startswith('PEN'):
                            code = 'PEN'
                        else:
                            skipped_var += 1
                            continue
                    else:
                        skipped_bad += 1
                        self.stderr.write(f'  · divisa no mapeada, salto: "{divisa}"')
                        continue

                cur = cur_by_code.get(code)
                buy, sell = _parse_dec(row[2]), _parse_dec(row[3])
                if cur is None or buy is None or sell is None or buy <= 0 or sell <= 0:
                    skipped_bad += 1
                    continue
                if buy > sell:
                    buy, sell = sell, buy  # el clean() del modelo exige buy <= sell

                valid_from = timezone.make_aware(datetime.combine(fecha, datetime.min.time()))
                mid = (buy + sell) / 2

                if opts['dry_run']:
                    created += 1
                    continue

                _, was_created = ExchangeRate.objects.update_or_create(
                    currency_from=cur, currency_to=bob, valid_from=valid_from,
                    market_type=market_type, rate_source=None,
                    defaults={
                        'official_rate': mid, 'buy_rate': buy, 'sell_rate': sell,
                        'avg_rate': mid, 'source': SOURCE_TAG,
                        'source_method': 'MANUAL', 'is_validated': True,
                        'confidence': Decimal('0.900'),
                    },
                )
                created += was_created
                updated += (0 if was_created else 1)

        verb = 'SIMULARÍA crear/actualizar' if opts['dry_run'] else 'creadas'
        self.stdout.write(self.style.SUCCESS(
            f'[{opts["series"]} -> {market_type}] filas leídas={rows_seen} · '
            f'{verb}={created} · actualizadas={updated} · '
            f'variantes omitidas={skipped_var} · descartadas={skipped_bad}'))
        if skipped_var:
            self.stdout.write(
                f'  Nota: {skipped_var} filas de variantes (USD sueltos/1 y 2/PEN mon) '
                f'omitidas. Usá --variantes usd|pen para colapsarlas a la base.')
