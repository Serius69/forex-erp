# data_migration/services/importer.py
"""
Servicio principal de importación.
Toma filas del Google Sheet, las transforma según el ColumnMapping
configurado, y las persiste en el modelo Django destino.

Soporta:
- Transacciones (BUY/SELL)
- Tasas de cambio históricas
- Inventario inicial
- Clientes
- Gastos de capital

Checkpoint: guarda progreso cada N batches para permitir resume.
"""
from __future__ import annotations
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction as db_transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Transformadores ───────────────────────────────────────────────────────────

def _transform_none(value: Any) -> Any:
    return value


def _transform_upper(value: Any) -> str:
    return str(value).strip().upper() if value is not None else ''


def _transform_lower(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ''


def _transform_strip(value: Any) -> str:
    return str(value).strip() if value is not None else ''


def _transform_date_bo(value: Any) -> date | None:
    """dd/mm/yyyy → date. También acepta yyyy-mm-dd e intentos varios."""
    if not value:
        return None
    s = str(value).strip()
    # Detectar formato automáticamente
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Intentar parsear solo números con separadores
    parts = re.split(r'[/\-\.]', s)
    if len(parts) == 3:
        try:
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 100:
                y += 2000
            return date(y, m, d)
        except (ValueError, TypeError):
            pass
    raise ValueError(f'No se puede parsear fecha: {s!r}')


def _transform_date_iso(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), '%Y-%m-%d').date()
    except ValueError:
        return _transform_date_bo(value)


def _transform_decimal(value: Any) -> Decimal | None:
    if value is None or str(value).strip() == '':
        return None
    s = str(value).strip()
    # Normalizar: quitar separadores de miles, convertir coma decimal a punto
    # Detectar si usa punto como miles o como decimal
    s_clean = re.sub(r'[^\d,\.\-]', '', s)
    if ',' in s_clean and '.' in s_clean:
        # Ambos presentes: el último es el decimal
        if s_clean.rfind(',') > s_clean.rfind('.'):
            s_clean = s_clean.replace('.', '').replace(',', '.')
        else:
            s_clean = s_clean.replace(',', '')
    elif ',' in s_clean:
        # Solo coma: es decimal (europeo)
        s_clean = s_clean.replace(',', '.')
    try:
        return Decimal(s_clean)
    except InvalidOperation:
        raise ValueError(f'No se puede convertir a decimal: {value!r}')


def _transform_boolean(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in ('1', 'true', 'yes', 'si', 'sí', 'verdadero', 'v', 't', 'y', 's')


def _transform_currency_code(value: Any) -> str:
    """Normaliza código de moneda a 3 letras mayúsculas."""
    if not value:
        return ''
    s = str(value).strip().upper()
    # Mapeos comunes
    aliases = {
        'DOLAR': 'USD', 'DOLARES': 'USD', '$': 'USD', 'US$': 'USD',
        'EURO': 'EUR', 'EUROS': 'EUR', '€': 'EUR',
        'PESO': 'ARS', 'PESOS': 'ARS',
        'REAL': 'BRL', 'REALES': 'BRL',
        'SOL': 'PEN', 'SOLES': 'PEN',
        'BOLIVIANO': 'BOB', 'BOLIVIANOS': 'BOB', 'BS': 'BOB',
    }
    return aliases.get(s, s[:3] if len(s) >= 3 else s)


TRANSFORM_FUNCTIONS = {
    'none':          _transform_none,
    'upper':         _transform_upper,
    'lower':         _transform_lower,
    'strip':         _transform_strip,
    'date_bo':       _transform_date_bo,
    'date_iso':      _transform_date_iso,
    'decimal':       _transform_decimal,
    'boolean':       _transform_boolean,
    'currency_code': _transform_currency_code,
}


# ── Persistidores por modelo ───────────────────────────────────────────────────

def _persist_transaction(data: dict, dry_run: bool) -> dict:
    """Crea/obtiene Customer y Transaction."""
    from transactions.models import Customer, Transaction
    from rates.models import Currency

    # Obtener/crear moneda
    currency_code = data.get('currency_code', '')
    try:
        if data.get('transaction_type') == 'BUY':
            # BUY: from=BOB, to=currency
            currency_from = Currency.objects.get(code='BOB')
            currency_to   = Currency.objects.get(code=currency_code)
        else:
            # SELL: from=currency, to=BOB
            currency_from = Currency.objects.get(code=currency_code)
            currency_to   = Currency.objects.get(code='BOB')
    except Currency.DoesNotExist as e:
        raise ValueError(f'Moneda no encontrada: {e}')

    # Obtener/crear cliente
    customer_name = data.get('customer_name', 'IMPORTADO').strip() or 'IMPORTADO'
    customer, _ = Customer.objects.get_or_create(
        document_number=f'IMP-{customer_name[:30]}',
        defaults={
            'full_name':      customer_name,
            'document_type':  'CI',
        }
    )

    tx_type = data.get('transaction_type', 'BUY').upper()
    rate    = data.get('exchange_rate') or Decimal('1')
    amount_to   = data.get('amount_to') or Decimal('0')
    amount_from = data.get('amount_from') or (amount_to * rate)

    # Validate imported exchange_rate against system primary rate
    if rate and rate > Decimal('0') and currency_from.code != 'BOB':
        try:
            from rates.exchange_rate_service import ExchangeRateService
            svc = ExchangeRateService()
            is_valid, warn_msg = svc.validate_transaction_rate(
                currency_from.code, rate, tolerance_pct=10.0  # wider tolerance for historical imports
            )
            if not is_valid:
                import logging
                logging.getLogger('kapitalya.import').warning(
                    'IMPORT_RATE_DEVIATION currency=%s rate=%s reason=%s',
                    currency_from.code, rate, warn_msg,
                )
                # Add warning to data for reporting but don't block import
                data.setdefault('_warnings', []).append(warn_msg)
        except Exception:
            pass

    tx_data = {
        'transaction_type': tx_type,
        'currency_from':    currency_from,
        'currency_to':      currency_to,
        'amount_from':      amount_from,
        'amount_to':        amount_to,
        'exchange_rate':    rate,
        'payment_method':   data.get('payment_method', 'CASH').upper() or 'CASH',
        'notes':            data.get('notes', ''),
        'status':           'COMPLETED',
        'customer':         customer,
    }

    if data.get('fecha'):
        tx_data['created_at'] = datetime.combine(data['fecha'], datetime.min.time())
        tx_data['created_at'] = timezone.make_aware(tx_data['created_at'])

    if data.get('branch'):
        tx_data['branch'] = data['branch']

    if dry_run:
        return {'action': 'dry_run', 'data': {k: str(v) for k, v in tx_data.items()}}

    with db_transaction.atomic():
        tx = Transaction(**tx_data)
        tx.save()
    return {'action': 'created', 'id': str(tx.id), 'number': tx.transaction_number}


def _persist_rate(data: dict, dry_run: bool) -> dict:
    from rates.models import ExchangeRate, Currency

    try:
        currency = Currency.objects.get(code=data.get('currency_code', ''))
    except Currency.DoesNotExist as e:
        raise ValueError(str(e))

    rate_data = {
        'currency':      currency,
        'buy_rate':      data.get('buy_rate', Decimal('0')),
        'sell_rate':     data.get('sell_rate', Decimal('0')),
        'official_rate': data.get('official_rate'),
        'market_type':   data.get('market_type') or 'paralelo_digital',
    }
    if data.get('fecha'):
        rate_data['date'] = data['fecha']

    if dry_run:
        return {'action': 'dry_run', 'data': {k: str(v) for k, v in rate_data.items()}}

    with db_transaction.atomic():
        obj = ExchangeRate(**rate_data)
        obj.save()
    return {'action': 'created', 'id': obj.pk}


def _persist_customer(data: dict, dry_run: bool) -> dict:
    from transactions.models import Customer

    doc = data.get('document_number', '').strip()
    if not doc:
        doc = f"IMP-{data.get('full_name', 'UNKNOWN')[:20]}"

    cust_data = {
        'full_name':      data.get('full_name', '').strip(),
        'document_type':  'CI',
        'phone':          data.get('phone', ''),
        'email':          data.get('email', ''),
        'address':        data.get('address', ''),
    }

    if dry_run:
        return {'action': 'dry_run', 'document_number': doc, 'data': cust_data}

    obj, created = Customer.objects.update_or_create(
        document_number=doc, defaults=cust_data
    )
    return {'action': 'created' if created else 'updated', 'id': obj.pk}


def _persist_capital(data: dict, dry_run: bool) -> dict:
    from capital.models import Gasto

    gasto_data = {
        'concepto':  data.get('concepto', ''),
        'monto':     data.get('monto', Decimal('0')),
        'categoria': data.get('categoria', 'OTROS').upper() or 'OTROS',
        'fecha':     data.get('fecha') or date.today(),
    }
    if data.get('branch'):
        gasto_data['branch'] = data['branch']

    if dry_run:
        return {'action': 'dry_run', 'data': {k: str(v) for k, v in gasto_data.items()}}

    with db_transaction.atomic():
        obj = Gasto(**gasto_data)
        obj.save()
    return {'action': 'created', 'id': obj.pk}


PERSISTERS = {
    'transactions': _persist_transaction,
    'rates':        _persist_rate,
    'customers':    _persist_customer,
    'capital':      _persist_capital,
}


# ── Servicio principal ────────────────────────────────────────────────────────

class RowImporter:
    """
    Importa filas del Google Sheet al modelo Django destino.
    Diseñado para ser llamado desde tareas Celery con soporte de checkpoint.
    """

    def __init__(self, migration_log):
        self.migration = migration_log
        self._mappings: list | None = None

    def _get_mappings(self) -> list:
        if self._mappings is None:
            self._mappings = list(
                self.migration.column_mappings.order_by('order', 'sheet_column')
            )
        return self._mappings

    def _build_header_index(self, header_row: list[str]) -> dict[str, int]:
        """Mapea nombre de columna → índice en la fila."""
        return {col.strip(): idx for idx, col in enumerate(header_row)}

    def transform_row(self, raw_row: list[Any], header_index: dict[str, int]) -> dict:
        """Aplica transformaciones a una fila cruda → dict de campos Django."""
        result: dict[str, Any] = {}
        errors: list[str] = []

        for mapping in self._get_mappings():
            col_name = mapping.sheet_column
            col_idx  = header_index.get(col_name)
            raw_val  = raw_row[col_idx] if col_idx is not None and col_idx < len(raw_row) else None

            # Default si vacío
            if (raw_val is None or str(raw_val).strip() == '') and mapping.default_value:
                raw_val = mapping.default_value

            # Validación required
            if mapping.is_required and (raw_val is None or str(raw_val).strip() == ''):
                errors.append(f'Campo requerido vacío: {col_name} → {mapping.model_field}')
                continue

            if raw_val is None or str(raw_val).strip() == '':
                continue

            # Validación regex
            if mapping.validation_regex:
                try:
                    if not re.match(mapping.validation_regex, str(raw_val)):
                        errors.append(f'{col_name}: "{raw_val}" no coincide con {mapping.validation_regex}')
                        continue
                except re.error:
                    pass

            # Transformar
            transform_fn = TRANSFORM_FUNCTIONS.get(mapping.transform, _transform_strip)
            try:
                result[mapping.model_field] = transform_fn(raw_val)
            except (ValueError, InvalidOperation) as exc:
                errors.append(f'{col_name}: {exc}')

        # Lookups especiales
        result = self._apply_lookups(result)

        if errors:
            raise ValueError('; '.join(errors))

        return result

    def _apply_lookups(self, data: dict) -> dict:
        """Resuelve lookups de branch/user después de las transformaciones."""
        # lookup_branch: el mapper pone el nombre de la sucursal en el campo
        branch_val = data.get('branch')
        if branch_val and isinstance(branch_val, str):
            try:
                from users.models import Branch
                branch = Branch.objects.get(name__iexact=branch_val)
                data['branch'] = branch
            except Exception:
                data.pop('branch', None)

        return data

    def import_batch(
        self,
        rows: list[list[Any]],
        header_index: dict[str, int],
        start_row_num: int = 0,
    ) -> dict:
        """
        Importa un batch de filas.
        Retorna: {success: int, errors: int, skipped: int, error_details: list}
        """
        success = errors = skipped = 0
        error_details: list[dict] = []
        persister = PERSISTERS.get(self.migration.target_model)

        if not persister:
            raise NotImplementedError(
                f'No hay persistidor para: {self.migration.target_model}'
            )

        for idx, raw_row in enumerate(rows):
            row_num = start_row_num + idx + 1

            # Fila vacía
            if not any(str(c).strip() for c in raw_row if c is not None):
                skipped += 1
                continue

            try:
                data = self.transform_row(raw_row, header_index)
                result = persister(data, self.migration.dry_run)
                success += 1
                logger.debug('Row %d OK: %s', row_num, result)

            except Exception as exc:
                errors += 1
                detail = {
                    'row': row_num,
                    'error': str(exc),
                    'raw': [str(c) for c in raw_row[:10]],  # primeras 10 cols
                }
                error_details.append(detail)
                logger.warning('Row %d ERROR: %s', row_num, exc)

                if not self.migration.skip_errors:
                    raise RuntimeError(
                        f'Error en fila {row_num}: {exc}. '
                        'Usa skip_errors=True para continuar en errores.'
                    ) from exc

        return {
            'success': success,
            'errors':  errors,
            'skipped': skipped,
            'error_details': error_details,
        }

    def save_checkpoint(self, last_row_index: int, last_batch_num: int, state: dict | None = None) -> None:
        """Guarda o actualiza el checkpoint de la migración."""
        from data_migration.models import MigrationCheckpoint
        MigrationCheckpoint.objects.update_or_create(
            migration=self.migration,
            defaults={
                'last_row_index': last_row_index,
                'last_batch_num': last_batch_num,
                'state_snapshot': state or {},
            }
        )

    def get_resume_point(self) -> tuple[int, int]:
        """Retorna (last_row_index, last_batch_num) del último checkpoint."""
        try:
            cp = self.migration.checkpoint
            return cp.last_row_index, cp.last_batch_num
        except Exception:
            return 0, 0
