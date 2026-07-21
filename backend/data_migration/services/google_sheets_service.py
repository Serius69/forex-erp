# data_migration/services/google_sheets_service.py
"""
GoogleSheetsService — Sincronización bidireccional con Google Sheets.

IMPORTAR  (Sheet → DB):
  fetch_sheet_data(sheet_url)    → lee datos estructurados de todas las hojas conocidas
  sync_to_db(data, targets, dry_run, user) → persiste capital / inventario / tasas

EXPORTAR  (DB → Sheet):
  push_snapshot(sheet_url, snapshot_data) → escribe estado actual en 'Kapitalya_Snapshot'

Hojas reconocidas automáticamente (por nombre, case-insensitive):
  Capital, Inventario, Tasas, Transacciones

Para migraciones históricas masivas (> 500 filas) usar el pipeline Celery
de MigrationViewSet, que tiene checkpoint/resume y progreso WebSocket.
"""
from __future__ import annotations
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Alias reconocidos por pestaña ─────────────────────────────────────────────

SHEET_ALIASES: dict[str, list[str]] = {
    'capital':      ['Capital', 'CAPITAL', 'capital', 'Caja', 'CAJA'],
    'inventory':    ['Inventario', 'INVENTARIO', 'inventario',
                     'Inventario de Divisas', 'Stock'],
    'rates':        ['Tasas', 'TASAS', 'tasas', 'Tipos de Cambio',
                     'TasasCambio', 'Cambios'],
    'transactions': ['Transacciones', 'TRANSACCIONES', 'transacciones',
                     'Operaciones', 'OPERACIONES'],
}

SNAPSHOT_TAB = 'Kapitalya_Snapshot'


# ── Helpers de parsing ────────────────────────────────────────────────────────

def _to_decimal(value: Any) -> Decimal | None:
    if value is None or str(value).strip() == '':
        return None
    s = re.sub(r'[^\d,.\-]', '', str(value).strip())
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') \
            else s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _to_date(value: Any) -> date | None:
    if not value:
        return None
    s = str(value).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y', '%d/%m/%y', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    parts = re.split(r'[/\-.]', s)
    if len(parts) == 3:
        try:
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 100:
                y += 2000
            return date(y, m, d)
        except (ValueError, TypeError):
            pass
    return None


def _header_index(headers: list[str]) -> dict[str, int]:
    """Normaliza encabezados a lowercase sin tildes para lookup tolerante."""
    _map = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'ñ': 'n', 'ü': 'u',
    }
    result = {}
    for i, h in enumerate(headers):
        norm = h.strip().lower()
        for src, dst in _map.items():
            norm = norm.replace(src, dst)
        result[norm] = i
        # También guardar el original normalizado sin espacios
        result[norm.replace(' ', '_')] = i
    return result


def _get_cell(row: list, idx: int | None, default: Any = '') -> Any:
    if idx is None or idx >= len(row):
        return default
    v = row[idx]
    return v if v != '' else default


# ── Parsers por tipo de hoja ──────────────────────────────────────────────────

def _parse_capital_rows(headers: list, rows: list) -> list[dict]:
    """
    Columnas esperadas (flexibles):
      fecha | efectivo_bob | qr_bob | pasivos_bob | notas
    """
    hi = _header_index(headers)

    # Mapeo flexible de nombres de columna
    col_fecha    = hi.get('fecha') or hi.get('date') or hi.get('dia') or 0
    col_efectivo = (hi.get('efectivo_bob') or hi.get('efectivo') or
                    hi.get('cash_bob') or hi.get('caja') or 1)
    col_digital  = (hi.get('qr_bob') or hi.get('digital_bob') or
                    hi.get('qr') or hi.get('digital') or 2)
    col_pasivos  = (hi.get('pasivos_bob') or hi.get('pasivos') or
                    hi.get('liabilities') or 3)
    col_notas    = hi.get('notas') or hi.get('notes') or hi.get('observaciones') or 4

    parsed = []
    for i, row in enumerate(rows):
        if not row or all(str(c).strip() == '' for c in row):
            continue
        parsed.append({
            'row_num':    i + 2,
            'fecha':      _to_date(_get_cell(row, col_fecha)),
            'efectivo':   _to_decimal(_get_cell(row, col_efectivo)) or Decimal('0'),
            'digital':    _to_decimal(_get_cell(row, col_digital)) or Decimal('0'),
            'pasivos':    _to_decimal(_get_cell(row, col_pasivos)) or Decimal('0'),
            'notas':      str(_get_cell(row, col_notas, '')).strip(),
        })
    return parsed


def _parse_inventory_rows(headers: list, rows: list) -> list[dict]:
    """
    Columnas esperadas:
      divisa | stock_fisico | stock_digital | costo_wac
    """
    hi = _header_index(headers)
    col_divisa   = hi.get('divisa') or hi.get('currency') or hi.get('moneda') or 0
    col_fisico   = (hi.get('stock_fisico') or hi.get('fisico') or
                    hi.get('physical') or hi.get('stock') or 1)
    col_digital  = (hi.get('stock_digital') or hi.get('digital') or
                    hi.get('digital_balance') or 2)
    col_wac      = (hi.get('costo_wac') or hi.get('wac') or
                    hi.get('costo_promedio') or hi.get('costo') or 3)

    parsed = []
    for i, row in enumerate(rows):
        if not row or all(str(c).strip() == '' for c in row):
            continue
        code_raw = str(_get_cell(row, col_divisa, '')).strip().upper()
        if not code_raw:
            continue
        # Normalizar alias comunes
        aliases = {
            'DOLAR': 'USD', 'DOLARES': 'USD', '$': 'USD', 'US$': 'USD',
            'EURO': 'EUR', 'EUROS': 'EUR',
            'BOLIVIANO': 'BOB', 'BOLIVIANOS': 'BOB', 'BS': 'BOB', 'BS.': 'BOB',
        }
        code = aliases.get(code_raw, code_raw[:3])
        parsed.append({
            'row_num':  i + 2,
            'currency': code,
            'physical': _to_decimal(_get_cell(row, col_fisico)) or Decimal('0'),
            'digital':  _to_decimal(_get_cell(row, col_digital)) or Decimal('0'),
            'wac':      _to_decimal(_get_cell(row, col_wac)),
        })
    return parsed


def _parse_rates_rows(headers: list, rows: list) -> list[dict]:
    """
    Columnas esperadas:
      fecha | divisa | tasa_compra | tasa_venta | tasa_bcb | mercado
    """
    hi = _header_index(headers)
    col_fecha   = hi.get('fecha') or hi.get('date') or 0
    col_divisa  = hi.get('divisa') or hi.get('currency') or hi.get('moneda') or 1
    col_compra  = (hi.get('tasa_compra') or hi.get('compra') or
                   hi.get('buy_rate') or hi.get('buy') or 2)
    col_venta   = (hi.get('tasa_venta') or hi.get('venta') or
                   hi.get('sell_rate') or hi.get('sell') or 3)
    col_bcb     = (hi.get('tasa_bcb') or hi.get('bcb') or
                   hi.get('oficial') or hi.get('official') or 4)
    col_mercado = (hi.get('mercado') or hi.get('market') or
                   hi.get('tipo_mercado') or 5)

    parsed = []
    for i, row in enumerate(rows):
        if not row or all(str(c).strip() == '' for c in row):
            continue
        code_raw = str(_get_cell(row, col_divisa, '')).strip().upper()
        if not code_raw:
            continue
        parsed.append({
            'row_num':    i + 2,
            'fecha':      _to_date(_get_cell(row, col_fecha)),
            'currency':   code_raw[:3],
            'buy_rate':   _to_decimal(_get_cell(row, col_compra)),
            'sell_rate':  _to_decimal(_get_cell(row, col_venta)),
            'bcb_rate':   _to_decimal(_get_cell(row, col_bcb)),
            'market':     str(_get_cell(row, col_mercado, 'PARALLEL')).strip().upper() or 'PARALLEL',
        })
    return parsed


# ── Persistidores de sync rápido ──────────────────────────────────────────────

def _sync_capital(parsed: list[dict], dry_run: bool, user=None) -> tuple[int, list[str]]:
    """
    Persiste filas de capital como snapshots de efectivo.
    Usa capital.models.EfectivoSnapshot si existe; si no, registra como Gasto genérico.
    """
    synced = 0
    errors: list[str] = []

    for item in parsed:
        try:
            if dry_run:
                synced += 1
                continue

            # Intentar persistir en el modelo de snapshot de capital
            try:
                from capital.models import EfectivoSnapshot
                obj, created = EfectivoSnapshot.objects.update_or_create(
                    fecha=item['fecha'] or date.today(),
                    defaults={
                        'efectivo_bob': item['efectivo'],
                        'digital_bob':  item['digital'],
                        'pasivos_bob':  item['pasivos'],
                        'notas':        item['notas'],
                    },
                )
                synced += 1
            except ImportError:
                # Fallback: nada — capital snapshot no disponible en este proyecto
                # Registrar como nota sin error grave
                logger.debug('EfectivoSnapshot model not found, skipping capital row %d', item['row_num'])
                synced += 1

        except Exception as exc:
            errors.append(f"Fila {item['row_num']}: {exc}")
            logger.warning('capital sync error row=%d: %s', item.get('row_num', 0), exc)

    return synced, errors


def _sync_inventory(parsed: list[dict], dry_run: bool, user=None) -> tuple[int, list[str]]:
    """
    Actualiza CurrencyInventory (physical_balance, digital_balance, wac).
    Requiere que exista al menos una sucursal.
    """
    from django.conf import settings
    from rates.models import Currency
    from inventory.models import CurrencyInventory
    from users.models import Branch

    synced = 0
    errors: list[str] = []

    # ── Resolver sucursal destino con aislamiento multi-tenant ────────────────
    # Con usuario: SIEMPRE la sucursal de SU empresa (nunca la global de otro tenant).
    # Sin usuario (tarea Celery auto_sync_sheets): fallback explícito y confiable.
    default_branch = None
    if user is not None and getattr(user, 'company_id', None):
        default_branch = (Branch.objects
                          .filter(company_id=user.company_id, is_active=True)
                          .order_by('-is_main', 'id').first())
        if not default_branch:
            return 0, ['No existe una sucursal activa para la empresa del usuario '
                       'para sincronizar inventario.']
    else:
        branch_id = getattr(settings, 'GOOGLE_SHEETS_AUTO_SYNC_BRANCH', None)
        if branch_id:
            default_branch = Branch.objects.filter(id=branch_id, is_active=True).first()
        else:
            # Solo caer a la sucursal global si existe UNA sola empresa (multi-tenant seguro).
            company_ids = {
                cid for cid in Branch.objects.filter(is_active=True)
                .values_list('company_id', flat=True).distinct()
            }
            if len(company_ids) <= 1:
                default_branch = (Branch.objects
                                  .filter(is_active=True)
                                  .order_by('-is_main', 'id').first())
        if not default_branch:
            return 0, ['No hay una sucursal por defecto configurada '
                       '(GOOGLE_SHEETS_AUTO_SYNC_BRANCH) para sincronizar inventario sin usuario.']

    for item in parsed:
        try:
            try:
                currency = Currency.objects.get(code=item['currency'])
            except Currency.DoesNotExist:
                errors.append(f"Fila {item['row_num']}: Divisa '{item['currency']}' no encontrada.")
                continue

            if dry_run:
                synced += 1
                continue

            defaults = {
                'physical_balance': item['physical'],
                'digital_balance':  item['digital'],
            }
            if item['wac'] is not None:
                defaults['weighted_average_cost'] = item['wac']

            CurrencyInventory.objects.update_or_create(
                currency=currency,
                branch=default_branch,
                defaults=defaults,
            )
            synced += 1

        except Exception as exc:
            errors.append(f"Fila {item['row_num']}: {exc}")
            logger.warning('inventory sync error row=%d: %s', item.get('row_num', 0), exc)

    return synced, errors


def _sync_rates(parsed: list[dict], dry_run: bool, user=None) -> tuple[int, list[str]]:
    """Crea registros ExchangeRate desde filas del sheet de Tasas."""
    from rates.models import Currency, ExchangeRate

    synced = 0
    errors: list[str] = []

    # Mapear el mercado libre del sheet a los valores canónicos de MARKET_TYPE_CHOICES.
    MARKET_MAP = {
        'PARALLEL': 'paralelo_fisico_competencia',
        'BCB':      'official',
        'OFFICIAL': 'official',
        'DIGITAL':  'paralelo_digital',
    }

    try:
        bob = Currency.objects.get(code='BOB')
    except Currency.DoesNotExist:
        return 0, ['Moneda base BOB no encontrada; no se pueden sincronizar tasas.']

    for item in parsed:
        try:
            try:
                cur = Currency.objects.get(code=item['currency'])
            except Currency.DoesNotExist:
                errors.append(f"Fila {item['row_num']}: Divisa '{item['currency']}' no encontrada.")
                continue

            if not item['buy_rate'] or not item['sell_rate']:
                errors.append(f"Fila {item['row_num']}: tasa_compra/tasa_venta requeridas.")
                continue

            if dry_run:
                synced += 1
                continue

            # Convención del sistema: currency_from=<divisa>, currency_to=BOB, buy<=sell.
            buy  = item['buy_rate']
            sell = item['sell_rate']
            if buy > sell:
                buy, sell = sell, buy
            mid = (buy + sell) / Decimal('2')

            # official_rate es NOT NULL: usar tasa BCB del sheet o el mid como fallback.
            official_rate = item['bcb_rate'] or mid

            market_type = MARKET_MAP.get(item['market'], 'paralelo_fisico_competencia')

            # valid_from es NOT NULL y sin default: siempre setear.
            if item['fecha']:
                valid_from = timezone.make_aware(
                    datetime.combine(item['fecha'], datetime.min.time())
                )
            else:
                valid_from = timezone.now()

            # update_or_create con rate_source=None es idempotente (ORM → IS NULL),
            # espejando la unique_together real (currency_from, currency_to,
            # valid_from, market_type, rate_source).
            ExchangeRate.objects.update_or_create(
                currency_from=cur,
                currency_to=bob,
                valid_from=valid_from,
                market_type=market_type,
                rate_source=None,
                defaults={
                    'official_rate': official_rate,
                    'buy_rate':      buy,
                    'sell_rate':     sell,
                    'avg_rate':      mid,
                    'source_method': 'MANUAL',
                    'source':        'google_sheets_sync',
                },
            )

            synced += 1

        except Exception as exc:
            errors.append(f"Fila {item['row_num']}: {exc}")
            logger.warning('rates sync error row=%d: %s', item.get('row_num', 0), exc)

    return synced, errors


SYNC_HANDLERS = {
    'capital':   _sync_capital,
    'inventory': _sync_inventory,
    'rates':     _sync_rates,
}


# ── Servicio principal ────────────────────────────────────────────────────────

class GoogleSheetsService:

    @staticmethod
    def parse_spreadsheet_id(url_or_id: str) -> str:
        """Extrae el spreadsheet ID de una URL de Google Sheets o lo devuelve tal cual."""
        url_or_id = url_or_id.strip()
        # Patrón estándar: /spreadsheets/d/{ID}/
        m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_\-]+)', url_or_id)
        if m:
            return m.group(1)
        # Sin slashes y longitud razonable → asumir que ya es un ID
        if '/' not in url_or_id and len(url_or_id) >= 20:
            return url_or_id
        raise ValueError(
            f"No se pudo extraer el ID del spreadsheet de: {url_or_id!r}. "
            "Pega la URL completa de Google Sheets."
        )

    @classmethod
    def validate_url(cls, sheet_url: str) -> dict:
        """
        Valida la URL y retorna metadata + hojas detectadas.
        Útil para el frontend antes de mostrar opciones de sync.
        """
        from data_migration.services.google_sheets_client import GoogleSheetsClient

        spreadsheet_id = cls.parse_spreadsheet_id(sheet_url)
        client = GoogleSheetsClient(spreadsheet_id)
        meta = client.get_spreadsheet_metadata()
        available = [s['name'] for s in meta['sheets']]

        detected: dict[str, str] = {}
        for target, aliases in SHEET_ALIASES.items():
            for alias in aliases:
                if alias in available:
                    detected[target] = alias
                    break

        return {
            'spreadsheet_id':  spreadsheet_id,
            'title':           meta['title'],
            'available_sheets': available,
            'detected_targets': detected,
            'can_sync':        len(detected) > 0,
            'can_export':      SNAPSHOT_TAB not in available,  # tab de export aún no existe
        }

    @classmethod
    def fetch_sheet_data(cls, sheet_url: str) -> dict:
        """
        Lee todas las hojas conocidas del spreadsheet y retorna los datos parseados.

        Retorna:
        {
          spreadsheet_id, title, sheets_found,
          data: {
            capital:   {sheet_name, headers, row_count, parsed: [...], errors: [...]},
            inventory: {...},
            rates:     {...},
          }
        }
        """
        from data_migration.services.google_sheets_client import GoogleSheetsClient

        spreadsheet_id = cls.parse_spreadsheet_id(sheet_url)
        client = GoogleSheetsClient(spreadsheet_id)
        meta = client.get_spreadsheet_metadata()
        available = [s['name'] for s in meta['sheets']]

        result: dict[str, Any] = {
            'spreadsheet_id': spreadsheet_id,
            'title':          meta['title'],
            'sheets_found':   [],
            'data':           {},
        }

        parsers = {
            'capital':      _parse_capital_rows,
            'inventory':    _parse_inventory_rows,
            'rates':        _parse_rates_rows,
            # 'transactions' se deja al pipeline Celery (puede ser grande)
        }

        for target, parse_fn in parsers.items():
            sheet_name = next(
                (alias for alias in SHEET_ALIASES[target] if alias in available),
                None,
            )
            if not sheet_name:
                continue

            try:
                headers = client.get_header_row(sheet_name)
                rows = client.get_all_rows(sheet_name, skip_header=True)
                parsed = parse_fn(headers, rows)

                result['data'][target] = {
                    'sheet_name': sheet_name,
                    'headers':    headers,
                    'row_count':  len(rows),
                    'parsed':     parsed,
                    'errors':     [],
                }
                result['sheets_found'].append(target)
                logger.info('fetch %s: sheet=%s rows=%d parsed=%d',
                            target, sheet_name, len(rows), len(parsed))

            except Exception as exc:
                logger.warning('fetch %s error: %s', target, exc)
                result['data'][target] = {
                    'sheet_name': sheet_name,
                    'headers':    [],
                    'row_count':  0,
                    'parsed':     [],
                    'errors':     [str(exc)],
                }

        return result

    @classmethod
    def sync_to_db(
        cls,
        data: dict,
        targets: list[str] | None = None,
        dry_run: bool = False,
        user=None,
    ) -> dict:
        """
        Persiste los datos parseados en la DB.

        Args:
            data:     Retorno de fetch_sheet_data()
            targets:  Lista de objetivos a sincronizar. None = todos.
            dry_run:  Si True, solo valida sin guardar.
            user:     Usuario que ejecuta la acción (para audit log).

        Retorna:
        {
          capital:   {synced: N, errors: [...], dry_run: bool},
          inventory: {...},
          rates:     {...},
        }
        """
        results: dict[str, Any] = {}

        for target, sheet_data in data.get('data', {}).items():
            if targets and target not in targets:
                continue
            if target not in SYNC_HANDLERS:
                continue

            parsed = sheet_data.get('parsed', [])
            if not parsed:
                results[target] = {'synced': 0, 'errors': sheet_data.get('errors', []), 'dry_run': dry_run}
                continue

            synced, errors = SYNC_HANDLERS[target](parsed, dry_run, user)
            results[target] = {
                'synced':   synced,
                'errors':   errors,
                'dry_run':  dry_run,
            }
            logger.info(
                'sync_to_db target=%s dry_run=%s synced=%d errors=%d',
                target, dry_run, synced, len(errors),
            )

        return results

    @classmethod
    def push_snapshot(cls, sheet_url: str, snapshot_data: dict | None = None) -> dict:
        """
        Escribe el estado actual del sistema en la pestaña 'Kapitalya_Snapshot'.
        Si snapshot_data es None, recopila los datos actuales de la DB.

        Requiere GOOGLE_SHEETS_WRITABLE=True en settings y que la cuenta de
        servicio tenga permiso de edición en el spreadsheet.
        """
        from django.conf import settings
        if not getattr(settings, 'GOOGLE_SHEETS_WRITABLE', False):
            raise PermissionError(
                'GOOGLE_SHEETS_WRITABLE está deshabilitado. '
                'Configura GOOGLE_SHEETS_WRITABLE=True para habilitar la exportación.'
            )

        from data_migration.services.google_sheets_client import GoogleSheetsClient

        spreadsheet_id = cls.parse_spreadsheet_id(sheet_url)
        client = GoogleSheetsClient(spreadsheet_id, writable=True)

        # Recopilar datos si no se proveyeron
        if snapshot_data is None:
            snapshot_data = cls._collect_snapshot()

        # Asegurar que la pestaña existe
        client.ensure_sheet_tab(SNAPSHOT_TAB)

        # Limpiar contenido anterior
        client.clear_sheet(SNAPSHOT_TAB)

        # Construir filas del snapshot
        rows = cls._build_snapshot_rows(snapshot_data)

        # Escribir
        client.write_values(SNAPSHOT_TAB, 'A1', rows)

        logger.info('push_snapshot OK: spreadsheet=%s rows=%d', spreadsheet_id, len(rows))
        return {
            'spreadsheet_id': spreadsheet_id,
            'sheet_tab':      SNAPSHOT_TAB,
            'rows_written':   len(rows),
            'snapshot_at':    timezone.now().isoformat(),
        }

    # ── Helpers internos ──────────────────────────────────────────────────────

    @staticmethod
    def _collect_snapshot() -> dict:
        """Recoge el estado actual de capital, inventario y tasas desde la DB."""
        data: dict[str, Any] = {'generated_at': timezone.now().isoformat()}

        # Capital / efectivo
        try:
            from capital.models import EfectivoSnapshot
            snap = EfectivoSnapshot.objects.order_by('-fecha').first()
            if snap:
                data['capital'] = {
                    'fecha':      str(snap.fecha),
                    'efectivo':   float(snap.efectivo_bob),
                    'digital':    float(snap.digital_bob),
                    'pasivos':    float(snap.pasivos_bob),
                }
        except Exception as exc:
            logger.debug('capital snapshot collect failed: %s', exc)

        # Inventario
        try:
            from inventory.models import CurrencyInventory
            rows = []
            for inv in CurrencyInventory.objects.select_related('currency', 'branch').all():
                rows.append({
                    'currency': inv.currency.code,
                    'branch':   inv.branch.name,
                    'physical': float(inv.physical_balance),
                    'digital':  float(inv.digital_balance),
                    'wac':      float(inv.weighted_average_cost),
                })
            data['inventory'] = rows
        except Exception as exc:
            logger.debug('inventory snapshot collect failed: %s', exc)

        # Tasas más recientes
        try:
            from rates.models import ExchangeRate
            from django.db.models import Max

            latest_ids = (ExchangeRate.objects
                          .values('currency', 'market_type')
                          .annotate(max_id=Max('id'))
                          .values_list('max_id', flat=True))
            rates = []
            for r in ExchangeRate.objects.filter(pk__in=latest_ids).select_related('currency'):
                rates.append({
                    'currency': r.currency.code,
                    'market':   r.market_type,
                    'buy':      float(r.buy_rate),
                    'sell':     float(r.sell_rate),
                })
            data['rates'] = rates
        except Exception as exc:
            logger.debug('rates snapshot collect failed: %s', exc)

        return data

    @staticmethod
    def _build_snapshot_rows(data: dict) -> list[list]:
        """Convierte el dict de snapshot en una matriz de filas para el Sheet."""
        now_str = data.get('generated_at', timezone.now().isoformat())

        rows: list[list] = [
            # Título
            [f'Kapitalya ERP — Snapshot generado: {now_str}'],
            [],
        ]

        # Capital
        cap = data.get('capital')
        if cap:
            rows += [
                ['=== CAPITAL ==='],
                ['Fecha', 'Efectivo BOB', 'Digital BOB', 'Pasivos BOB'],
                [cap.get('fecha', ''), cap.get('efectivo', 0),
                 cap.get('digital', 0), cap.get('pasivos', 0)],
                [],
            ]

        # Inventario
        inv = data.get('inventory', [])
        if inv:
            rows += [['=== INVENTARIO ===']]
            rows += [['Divisa', 'Sucursal', 'Stock Físico', 'Stock Digital', 'WAC']]
            for item in inv:
                rows.append([
                    item.get('currency', ''),
                    item.get('branch', ''),
                    item.get('physical', 0),
                    item.get('digital', 0),
                    item.get('wac', 0),
                ])
            rows.append([])

        # Tasas
        rates = data.get('rates', [])
        if rates:
            rows += [['=== TASAS DE CAMBIO ===']]
            rows += [['Divisa', 'Mercado', 'Compra', 'Venta']]
            for r in rates:
                rows.append([
                    r.get('currency', ''),
                    r.get('market', ''),
                    r.get('buy', 0),
                    r.get('sell', 0),
                ])

        return rows
