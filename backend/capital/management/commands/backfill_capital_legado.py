"""
backfill_capital_legado — carga idempotente de Caja Chica y Acreedores desde el
sheet legado (KapitalyaRegistro2026) a los modelos nuevos. Sprint 3 de la migración.

NO hornea valores financieros: todo entra por parámetro/CSV para que el operador
confirme (el sheet tiene DRIFT en caja chica: 11.640 vs 22.549 corte vs 16.510).

Caja chica — siembra UN movimiento APERTURA (corte inicial):
    python manage.py backfill_capital_legado --caja-apertura 22549 --caja-fecha 2026-03-31

Acreedores — desde un CSV "Fecha,Acreedor,Monto" (export del ledger del sheet):
    python manage.py backfill_capital_legado --acreedores-csv acreedores.csv

Ambos son idempotentes (re-correr no duplica). Usá --dry-run para simular.
"""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

MARK = 'CARGA_GS_2026'


def _parse_date(raw):
    raw = (raw or '').strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_dec(raw):
    raw = (raw or '').strip().replace('Bs', '').replace(' ', '')
    if not raw:
        return None
    raw = raw.replace('.', '').replace(',', '.') if (',' in raw) else raw
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


class Command(BaseCommand):
    help = 'Backfill idempotente de Caja Chica (apertura) y Acreedores desde el sheet legado.'

    def add_arguments(self, parser):
        parser.add_argument('--branch-id', type=int, default=None,
                            help='Sucursal destino; por defecto la principal (is_main).')
        parser.add_argument('--caja-apertura', type=str, default=None,
                            help='Monto BOB del corte inicial de caja chica.')
        parser.add_argument('--caja-fecha', type=str, default='2026-03-31',
                            help='Fecha del corte (YYYY-MM-DD). Default 2026-03-31.')
        parser.add_argument('--acreedores-csv', type=str, default=None,
                            help='CSV "Fecha,Acreedor,Monto" del ledger de acreedores.')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        from users.models import Branch
        from capital.models import Acreedor, MovimientoAcreedor, MovimientoCajaChica

        branch = (Branch.objects.filter(pk=opts['branch_id']).first() if opts['branch_id']
                  else Branch.objects.filter(is_main=True, is_active=True).order_by('id').first()
                  or Branch.objects.order_by('id').first())
        if branch is None:
            raise CommandError('No hay sucursal. Corré seed_data primero o pasá --branch-id.')
        dry = opts['dry_run']
        self.stdout.write(f'Sucursal destino: {branch} (id={branch.pk})')

        # ── Caja chica: APERTURA idempotente ────────────────────────────────
        if opts['caja_apertura'] is not None:
            monto = _parse_dec(opts['caja_apertura'])
            fecha = _parse_date(opts['caja_fecha'])
            if monto is None or monto <= 0 or fecha is None:
                raise CommandError('--caja-apertura/--caja-fecha inválidos.')
            exists = MovimientoCajaChica.objects.filter(
                branch=branch, tipo='APERTURA', fecha=fecha).exists()
            if exists:
                self.stdout.write('  · caja chica: APERTURA ya existe (sin cambios).')
            elif dry:
                self.stdout.write(f'  · [dry] crearía APERTURA caja chica Bs {monto} @ {fecha}.')
            else:
                MovimientoCajaChica.objects.create(
                    branch=branch, tipo='APERTURA', fecha=fecha, monto_bob=monto,
                    concepto=f'Corte inicial caja chica ({MARK})')
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ caja chica: APERTURA Bs {monto} @ {fecha} creada.'))

        # ── Acreedores: Acreedor + movimiento CARGO idempotente ─────────────
        if opts['acreedores_csv']:
            creados_a = creados_m = saltados = 0
            with open(opts['acreedores_csv'], newline='', encoding='utf-8-sig') as fh:
                for row in csv.reader(fh):
                    if not row or len(row) < 3:
                        continue
                    fecha = _parse_date(row[0])
                    nombre = (row[1] or '').strip()
                    monto = _parse_dec(row[2])
                    if not nombre or nombre.lower() in ('acreedor', 'detalle') or fecha is None:
                        continue
                    if monto is None or monto <= 0:
                        saltados += 1   # filas en 0 (deuda saldada) — sin movimiento
                        continue
                    moneda = 'USD' if 'dolar' in nombre.lower() else 'BOB'
                    if dry:
                        creados_m += 1
                        continue
                    acreedor, was_new = Acreedor.objects.get_or_create(
                        nombre=nombre, branch=branch,
                        defaults={'moneda': moneda, 'notas': MARK})
                    creados_a += was_new
                    _, mov_new = MovimientoAcreedor.objects.get_or_create(
                        acreedor=acreedor, fecha=fecha, tipo='CARGO', monto_bob=monto,
                        defaults={'concepto': f'Deuda histórica ({MARK})'})
                    creados_m += mov_new
            verb = '[dry] simularía' if dry else 'creados'
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ acreedores: {verb} — acreedores nuevos={creados_a} · '
                f'movimientos={creados_m} · filas en 0 saltadas={saltados}'))

        if not opts['caja_apertura'] and not opts['acreedores_csv']:
            self.stdout.write(self.style.WARNING(
                'Nada que hacer: pasá --caja-apertura y/o --acreedores-csv.'))
