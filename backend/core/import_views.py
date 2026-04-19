"""
Import API — POST /api/import/excel/

Accepts:
  - file upload (.xlsx, .xls, .csv)   →  form-data field "file"
  - Google Sheets URL                  →  JSON/form field "google_sheets_url"

Sheet / target detection:
  xlsx/xls  — reads every named sheet (Transacciones, Capital, Tasas, Inventario)
  csv       — single sheet, type auto-detected by column names
  gsheets   — fetches each target sheet via public CSV export

Column specs (same for all sources):
  Transacciones: Fecha | Tipo(COMPRA/VENTA) | Divisa | Monto | Tasa | BOB | Cliente | CI | Telefono | Metodo
  Capital:       Fecha | Efectivo | QR | Pasivos | Notas
  Tasas:         Fecha | Divisa | Compra | Venta | Oficial | Mercado
  Inventario:    Divisa | Stock_Fisico | Stock_Digital | Costo_Promedio
"""
import io
import logging
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

import pandas as pd
import requests as http_requests

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework import status

log = logging.getLogger(__name__)

# ── Sheet name aliases ─────────────────────────────────────────────────────────
SHEET_ALIASES = {
    'Transacciones': ['Transacciones', 'transacciones', 'TRANSACCIONES', 'Transactions'],
    'Capital':       ['Capital', 'capital', 'CAPITAL', 'Caja'],
    'Tasas':         ['Tasas', 'tasas', 'TASAS', 'Tipos de Cambio', 'TiposCambio', 'Rates'],
    'Inventario':    ['Inventario', 'inventario', 'INVENTARIO', 'Stock', 'stock'],
}

# Reverse map: any alias → canonical name
_ALIAS_MAP = {alias: canonical for canonical, aliases in SHEET_ALIASES.items() for alias in aliases}


# ── Value helpers ──────────────────────────────────────────────────────────────

def _safe_decimal(val, default='0'):
    try:
        if val is None or (isinstance(val, float) and val != val):
            return Decimal(default)
        return Decimal(str(val)).quantize(Decimal('0.0001'))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _safe_str(val, default=''):
    if val is None or (isinstance(val, float) and val != val):
        return default
    return str(val).strip()


def _safe_date(val):
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
            try:
                return datetime.strptime(val.strip(), fmt).date()
            except ValueError:
                continue
    # pandas Timestamp
    try:
        import pandas as _pd
        if isinstance(val, _pd.Timestamp):
            return val.date()
    except Exception:
        pass
    return None


# ── DataFrame → row list ───────────────────────────────────────────────────────

def _df_to_rows(df: pd.DataFrame):
    """
    Return a list of plain tuples from a DataFrame.
    NaN → None so _safe_* helpers don't choke.
    """
    df = df.where(pd.notna(df), None)
    return [tuple(row) for row in df.itertuples(index=False, name=None)]


# ── Sheet-type auto-detection (for single-sheet CSV) ─────────────────────────

def _detect_sheet_type(columns) -> str | None:
    cols = {str(c).strip().lower() for c in columns}
    if {'tipo', 'divisa', 'monto'}.issubset(cols):
        return 'Transacciones'
    if {'efectivo'}.issubset(cols) and ('qr' in cols or 'pasivos' in cols):
        return 'Capital'
    if {'compra', 'venta', 'divisa'}.issubset(cols):
        return 'Tasas'
    if 'divisa' in cols and (
        'stock_fisico' in cols or 'stock fisico' in cols or 'stock' in cols
    ):
        return 'Inventario'
    return None


# ── Source loaders ─────────────────────────────────────────────────────────────

def _load_from_file(uploaded) -> dict[str, list]:
    """Load uploaded file (xlsx, xls, csv) → {canonical_sheet_name: [row_tuples]}"""
    filename = uploaded.name.lower()
    content = uploaded.read()

    if filename.endswith('.csv'):
        df = pd.read_csv(io.BytesIO(content), header=0)
        sheet_type = _detect_sheet_type(df.columns.tolist())
        if not sheet_type:
            raise ValueError(
                'No se pudo determinar el tipo de datos del CSV. '
                'Asegúrate de que los encabezados incluyan columnas reconocibles '
                '(Tipo, Divisa, Monto / Efectivo, QR / Compra, Venta / Stock_Fisico).'
            )
        return {sheet_type: _df_to_rows(df)}

    # xlsx / xls
    try:
        excel_file = pd.ExcelFile(io.BytesIO(content))
    except Exception as e:
        raise ValueError(f'No se pudo leer el archivo Excel: {e}')

    result = {}
    for raw_name in excel_file.sheet_names:
        canonical = _ALIAS_MAP.get(raw_name)
        if canonical:
            df = pd.read_excel(excel_file, sheet_name=raw_name, header=0)
            result[raw_name] = _df_to_rows(df)   # keep raw name for reporting
    return result


def _load_from_google_sheets(url: str) -> dict[str, list]:
    """
    Fetch each target sheet from a PUBLIC Google Sheet via CSV export.
    Returns {canonical_sheet_name: [row_tuples]}.
    Raises ValueError if the URL is invalid.
    """
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', url)
    if not m:
        raise ValueError('URL de Google Sheets no válida. Formato esperado: '
                         'https://docs.google.com/spreadsheets/d/<ID>/...')
    sheet_id = m.group(1)
    result = {}

    for canonical, aliases in SHEET_ALIASES.items():
        for alias in aliases:
            csv_url = (
                f'https://docs.google.com/spreadsheets/d/{sheet_id}'
                f'/gviz/tq?tqx=out:csv&sheet={alias}'
            )
            try:
                resp = http_requests.get(csv_url, timeout=15)
            except Exception as e:
                log.warning('GSHEETS_FETCH_ERROR sheet=%s err=%s', alias, e)
                continue

            if resp.status_code != 200:
                continue

            # gviz returns HTML error page when sheet doesn't exist
            text = resp.text
            if not text or text.lstrip().startswith('<'):
                continue

            try:
                df = pd.read_csv(io.StringIO(text), header=0)
            except Exception:
                continue

            if df.empty or len(df.columns) < 2:
                continue

            result[canonical] = _df_to_rows(df)
            log.debug('GSHEETS_FETCHED sheet=%s alias=%s rows=%d', canonical, alias, len(result[canonical]))
            break  # found this canonical sheet, move on

    return result


# ── Main view ──────────────────────────────────────────────────────────────────

class ExcelImportView(APIView):
    """
    POST /api/import/excel/

    Multipart (file upload):
        file=<xlsx|xls|csv>
        [dry_run=true]

    JSON or form-data (Google Sheets):
        google_sheets_url=<public sheet URL>
        [dry_run=true]
    """
    parser_classes     = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in ('ADMIN', 'SUPERVISOR'):
            return Response(
                {'error': 'Solo administradores o supervisores pueden importar datos'},
                status=status.HTTP_403_FORBIDDEN,
            )

        dry_run      = str(request.data.get('dry_run', request.query_params.get('dry_run', 'false'))).lower() == 'true'
        uploaded     = request.FILES.get('file')
        sheets_url   = _safe_str(request.data.get('google_sheets_url'))

        if not uploaded and not sheets_url:
            return Response(
                {'error': 'Proporciona un archivo (xlsx, xls, csv) o una URL de Google Sheets'},
                status=400,
            )
        if uploaded and sheets_url:
            return Response(
                {'error': 'Proporciona solo uno: archivo O URL de Google Sheets, no ambos'},
                status=400,
            )

        # ── Load sheets ────────────────────────────────────────────────────────
        source_label = ''
        try:
            if uploaded:
                ext = uploaded.name.rsplit('.', 1)[-1].lower()
                if ext not in ('xlsx', 'xls', 'csv'):
                    return Response(
                        {'error': 'Solo se aceptan archivos .xlsx, .xls o .csv'},
                        status=400,
                    )
                sheets = _load_from_file(uploaded)
                source_label = uploaded.name
            else:
                sheets = _load_from_google_sheets(sheets_url)
                source_label = sheets_url
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

        results = {
            'dry_run':      dry_run,
            'source':       source_label,
            'sheets_found': list(sheets.keys()),
            'imported':     {},
            'errors':       {},
            'warnings':     [],
        }

        if not sheets:
            results['warnings'].append(
                'No se encontraron hojas reconocidas. '
                'Nombres válidos: Transacciones, Capital, Tasas, Inventario.'
            )
            results['summary'] = {'total_imported': 0, 'total_errors': 0, 'status': 'empty'}
            return Response(results, status=200)

        # ── Dispatch to handlers ───────────────────────────────────────────────
        handler_map = {
            'Transacciones': self._import_transactions,
            'Capital':       self._import_capital,
            'Tasas':         self._import_rates,
            'Inventario':    self._import_inventory,
        }

        for sheet_raw, rows in sheets.items():
            canonical = _ALIAS_MAP.get(sheet_raw, sheet_raw)
            handler   = handler_map.get(canonical)
            if not handler:
                results['warnings'].append(
                    f"Hoja '{sheet_raw}' ignorada — nombres válidos: Transacciones, Capital, Tasas, Inventario"
                )
                continue
            try:
                ok, errors, warnings = handler(rows, request.user, dry_run)
                results['imported'][sheet_raw] = ok
                if errors:
                    results['errors'][sheet_raw] = errors
                results['warnings'].extend(warnings)
            except Exception as e:
                log.error('IMPORT_SHEET_ERROR sheet=%s err=%s', sheet_raw, e, exc_info=True)
                results['errors'][sheet_raw] = [str(e)]

        total_imported = sum(results['imported'].values())
        total_errors   = sum(len(v) for v in results['errors'].values())

        results['summary'] = {
            'total_imported': total_imported,
            'total_errors':   total_errors,
            'status':         'success' if total_errors == 0 else 'partial',
        }

        log.info(
            'IMPORT user=%s source=%s imported=%d errors=%d dry_run=%s',
            request.user.username, source_label, total_imported, total_errors, dry_run,
        )
        return Response(results, status=200)

    # ── Sheet handlers ─────────────────────────────────────────────────────────
    # Each handler receives:
    #   rows     — list of plain tuples (header row already stripped)
    #   user     — request.user
    #   dry_run  — bool
    # Returns (ok_count, error_list, warning_list)

    def _import_transactions(self, rows, user, dry_run):
        from transactions.models import Transaction, Customer
        from rates.models import Currency
        from users.models import Branch

        branch = user.branch
        if not branch:
            return 0, ['Usuario sin sucursal asignada'], []

        ok, errors, warnings = 0, [], []
        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return 0, ['Divisa BOB no encontrada — ejecuta seed_data primero'], []

        for i, row in enumerate(rows, start=2):
            if not any(v is not None for v in row):
                continue
            try:
                fecha   = _safe_date(row[0])
                tipo    = _safe_str(row[1]).upper()
                divisa  = _safe_str(row[2]).upper()
                monto   = _safe_decimal(row[3])
                tasa    = _safe_decimal(row[4])
                bob_amt = _safe_decimal(row[5]) if len(row) > 5 and row[5] else monto * tasa
                cliente = _safe_str(row[6], 'Cliente Importado') if len(row) > 6 else 'Cliente Importado'
                ci      = _safe_str(row[7], f'EXC{i:04d}')       if len(row) > 7 else f'EXC{i:04d}'
                telefono= _safe_str(row[8])                        if len(row) > 8 else ''
                metodo  = _safe_str(row[9], 'CASH').upper()        if len(row) > 9 else 'CASH'

                if not fecha:
                    errors.append(f'Fila {i}: fecha inválida ({row[0]})')
                    continue
                if tipo not in ('COMPRA', 'VENTA', 'BUY', 'SELL'):
                    errors.append(f'Fila {i}: tipo inválido ({row[1]}). Use COMPRA/VENTA')
                    continue
                if monto <= 0:
                    errors.append(f'Fila {i}: monto inválido ({row[3]})')
                    continue
                if tasa <= 0:
                    warnings.append(f'Fila {i}: tasa 0 — se usará 1.0')
                    tasa = Decimal('1')

                tx_type = 'BUY' if tipo in ('COMPRA', 'BUY') else 'SELL'
                if metodo not in ('CASH', 'TRANSFER', 'QR', 'CHECK', 'CARD'):
                    metodo = 'CASH'

                currency = Currency.objects.filter(code=divisa).first()
                if not currency:
                    errors.append(f'Fila {i}: divisa "{divisa}" no encontrada')
                    continue

                if not dry_run:
                    customer, _ = Customer.objects.get_or_create(
                        document_number=ci or f'EXC{i:04d}',
                        defaults={
                            'full_name':      cliente or 'Cliente Importado',
                            'document_type':  'CI',
                            'phone':          telefono,
                            'nationality':    'Boliviana',
                        }
                    )

                    date_str = fecha.strftime('%Y%m%d')
                    prefix   = f"IMP{branch.code}{date_str}"
                    last     = Transaction.objects.filter(
                        transaction_number__startswith=prefix
                    ).order_by('-transaction_number').first()
                    seq = int(last.transaction_number[-4:]) + 1 if last else 1

                    Transaction(
                        transaction_number=f"{prefix}{seq:04d}",
                        transaction_type=tx_type,
                        status='COMPLETED',
                        customer=customer,
                        currency_from=currency,
                        currency_to=bob,
                        amount_from=monto,
                        amount_to=bob_amt if bob_amt > 0 else monto * tasa,
                        exchange_rate=tasa,
                        payment_method=metodo,
                        cashier=user,
                        branch=branch,
                        notes='Importado',
                        completed_at=timezone.make_aware(
                            datetime.combine(fecha, datetime.min.time())
                        ),
                    ).save()

                ok += 1
            except Exception as e:
                errors.append(f'Fila {i}: {e}')
                if len(errors) >= 20:
                    errors.append('... (demasiados errores, abortando hoja)')
                    break

        return ok, errors, warnings

    def _import_capital(self, rows, user, dry_run):
        from capital.models import CapitalManualEntry, CapitalEntryHistory

        branch = user.branch
        if not branch:
            return 0, ['Usuario sin sucursal asignada'], []

        ok, errors, warnings = 0, [], []

        for i, row in enumerate(rows, start=2):
            if not any(v is not None for v in row):
                continue
            try:
                fecha    = _safe_date(row[0])
                efectivo = _safe_decimal(row[1])
                qr       = _safe_decimal(row[2]) if len(row) > 2 else Decimal('0')
                pasivos  = _safe_decimal(row[3]) if len(row) > 3 else Decimal('0')
                notas    = _safe_str(row[4])      if len(row) > 4 else ''

                if not fecha:
                    errors.append(f'Fila {i}: fecha inválida')
                    continue

                if not dry_run:
                    entry, created = CapitalManualEntry.objects.get_or_create(
                        branch=branch,
                        fecha=fecha,
                        defaults={
                            'efectivo_bob':   efectivo,
                            'qr_bob':         qr,
                            'pasivos_bob':    pasivos,
                            'notas':          notas or 'Importado',
                            'registrado_por': user,
                        }
                    )
                    if not created:
                        CapitalEntryHistory.objects.create(
                            entry=entry,
                            efectivo_bob_prev=entry.efectivo_bob,
                            qr_bob_prev=entry.qr_bob,
                            pasivos_bob_prev=entry.pasivos_bob,
                            efectivo_bob_new=efectivo,
                            qr_bob_new=qr,
                            pasivos_bob_new=pasivos,
                            motivo='Actualizado por importación',
                            modificado_por=user,
                        )
                        entry.efectivo_bob = efectivo
                        entry.qr_bob       = qr
                        entry.pasivos_bob  = pasivos
                        entry.save()

                ok += 1
            except Exception as e:
                errors.append(f'Fila {i}: {e}')

        return ok, errors, warnings

    def _import_rates(self, rows, user, dry_run):
        from rates.models import Currency, ExchangeRate

        ok, errors, warnings = 0, [], []
        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return 0, ['Divisa BOB no encontrada'], []

        for i, row in enumerate(rows, start=2):
            if not any(v is not None for v in row):
                continue
            try:
                fecha   = _safe_date(row[0])
                divisa  = _safe_str(row[1]).upper()
                compra  = _safe_decimal(row[2])
                venta   = _safe_decimal(row[3])
                oficial = _safe_decimal(row[4]) if len(row) > 4 and row[4] else compra
                mercado = _safe_str(row[5], 'parallel').lower() if len(row) > 5 else 'parallel'

                if not fecha:
                    errors.append(f'Fila {i}: fecha inválida')
                    continue
                if compra <= 0 or venta <= 0:
                    warnings.append(f'Fila {i}: tasas cero — ignorado')
                    continue
                if mercado not in ('parallel', 'bcb', 'digital', 'official'):
                    mercado = 'parallel'

                currency = Currency.objects.filter(code=divisa).first()
                if not currency:
                    errors.append(f'Fila {i}: divisa "{divisa}" no encontrada')
                    continue

                if not dry_run:
                    exists = ExchangeRate.objects.filter(
                        currency_from=currency,
                        currency_to=bob,
                        market_type=mercado,
                        valid_from__date=fecha,
                    ).exists()

                    if not exists:
                        ExchangeRate.objects.create(
                            currency_from=currency,
                            currency_to=bob,
                            buy_rate=compra,
                            sell_rate=venta,
                            official_rate=oficial,
                            market_type=mercado,
                            valid_from=timezone.make_aware(
                                datetime.combine(fecha, datetime.min.time())
                            ),
                            valid_until=timezone.make_aware(
                                datetime.combine(fecha, datetime.max.time().replace(microsecond=0))
                            ),
                        )

                ok += 1
            except Exception as e:
                errors.append(f'Fila {i}: {e}')

        return ok, errors, warnings

    def _import_inventory(self, rows, user, dry_run):
        from rates.models import Currency
        from inventory.models import CurrencyInventory

        branch = user.branch
        if not branch:
            return 0, ['Usuario sin sucursal asignada'], []

        ok, errors, warnings = 0, [], []

        for i, row in enumerate(rows, start=2):
            if not any(v is not None for v in row):
                continue
            try:
                divisa  = _safe_str(row[0]).upper()
                fisico  = _safe_decimal(row[1])
                digital = _safe_decimal(row[2]) if len(row) > 2 and row[2] else Decimal('0')
                wac     = _safe_decimal(row[3]) if len(row) > 3 and row[3] else Decimal('1')

                if not divisa:
                    continue

                currency = Currency.objects.filter(code=divisa).first()
                if not currency:
                    errors.append(f'Fila {i}: divisa "{divisa}" no encontrada')
                    continue

                if not dry_run:
                    inv, created = CurrencyInventory.objects.get_or_create(
                        currency=currency,
                        branch=branch,
                        defaults={
                            'physical_balance':      fisico,
                            'digital_balance':       digital,
                            'weighted_average_cost': wac,
                            'minimum_stock':         Decimal('100'),
                            'maximum_stock':         Decimal('999999'),
                            'reorder_point':         Decimal('200'),
                        }
                    )
                    if not created:
                        inv.physical_balance      = fisico
                        inv.digital_balance       = digital
                        inv.weighted_average_cost = wac
                        inv.save()
                        warnings.append(f'Fila {i}: inventario {divisa} actualizado')

                ok += 1
            except Exception as e:
                errors.append(f'Fila {i}: {e}')

        return ok, errors, warnings
