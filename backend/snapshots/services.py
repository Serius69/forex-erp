# snapshots/services.py
"""
SnapshotService — motor de captura del estado completo del sistema.

Flujo de escritura:
  1. Evento ocurre (transacción forex, venta tarjeta, gasto, etc.)
  2. Señal Django o llamada directa invoca SnapshotService.schedule()
  3. schedule() encola _write() en transaction.on_commit()          ← nunca bloquea TX principal
  4. _write() ejecuta en su propio atomic():
       a. Recopila estado (capital, caja, divisas, tarjetas)
       b. Calcula checksum
       c. Inserta SystemSnapshot (inmutable)
  5. Debounce: si ya se creó un snapshot del mismo módulo/branch en
     los últimos DEBOUNCE_SECONDS, se omite (configurable).

Flujo de lectura:
  SnapshotService.compare(snap1, snap2) → diff estructurado

IMPORTANTE:
  - Los snapshots son APPEND-ONLY.  Nunca modificar data_json post-insert.
  - Errores de recopilación de estado no propagan excepciones al caller
    (se registran en metadata_json['gather_errors']).
"""
import hashlib
import json
import logging
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.db import transaction as db_tx
from django.utils import timezone

log = logging.getLogger('snapshots')

# Segundos mínimos entre snapshots del mismo módulo+branch.
# Evita rafagas de inserciones en operaciones masivas.
DEBOUNCE_SECONDS: int = getattr(settings, 'SNAPSHOT_DEBOUNCE_SECONDS', 30)


# ─────────────────────────────────────────────────────────────────────────────
#  Recopilación de estado
# ─────────────────────────────────────────────────────────────────────────────

def _safe(fn, label: str) -> tuple:
    """Ejecuta fn(); retorna (resultado, None) o (None, mensaje_error)."""
    try:
        return fn(), None
    except Exception as exc:
        log.warning('SNAPSHOT_GATHER_FAIL section=%s err=%s', label, exc, exc_info=True)
        return None, str(exc)


def _gather_capital(branch) -> dict:
    """Estado financiero completo vía CapitalService."""
    from capital.services import CapitalService
    from capital.views import _format_capital_actual
    raw = CapitalService.calcular_capital(branch=branch)
    return _format_capital_actual(raw)


def _gather_caja_bob(branch) -> dict:
    """Desglose de denominaciones BOB del día."""
    from capital.models import CashBOB
    from capital.services import CashBOBService

    qs = CashBOB.objects.select_related('branch')
    if branch:
        qs = qs.filter(branch=branch)

    result = {}
    for cash in qs.filter(fecha=timezone.localdate()):
        key = cash.branch.code if cash.branch_id else 'GLOBAL'
        result[key] = CashBOBService.serialize_breakdown(cash)
    return result


def _gather_divisas(branch) -> list:
    """Inventario de divisas con stock, WAC y valor de mercado."""
    from inventory.models import CurrencyInventory

    qs = (CurrencyInventory.objects
          .select_related('currency', 'branch')
          .exclude(currency__code='BOB')
          .order_by('branch_id', 'currency__code'))
    if branch:
        qs = qs.filter(branch=branch)

    result = []
    for inv in qs:
        result.append({
            'currency':   inv.currency.code,
            'name':       inv.currency.name_en,
            'branch':     inv.branch.code if inv.branch_id else None,
            'physical':   str(inv.physical_balance),
            'digital':    str(inv.digital_balance),
            'total':      str(inv.total_balance),
            'wac':        str(inv.weighted_average_cost),
            'low_stock':  inv.needs_replenishment,
            'overstocked': inv.is_overstocked,
        })
    return result


def _gather_tarjetas() -> dict:
    """Inventario de tarjetas: stock actual, costo FIFO promedio, valor."""
    from tarjetas.models import TipoTarjeta, LoteCompra

    tipos = (TipoTarjeta.objects
             .filter(is_active=True)
             .prefetch_related('lotes'))

    items = []
    total_valor = Decimal('0')

    for t in tipos:
        stock      = t.stock_actual
        costo_prom = t.costo_promedio
        valor      = t.valor_inventario_bob

        lotes_activos = [
            {
                'id':         lote.id,
                'fecha':      str(lote.fecha_compra),
                'restante':   lote.cantidad_restante,
                'costo_unit': str(lote.precio_costo),
            }
            for lote in t.lotes.filter(is_active=True, cantidad_restante__gt=0)
                              .order_by('fecha_compra')
        ]

        items.append({
            'id':           t.id,
            'nombre':       t.nombre,
            'operadora':    t.operadora,
            'denominacion': str(t.denominacion),
            'stock':        stock,
            'costo_prom':   str(costo_prom),
            'valor_bob':    str(valor),
            'lotes':        lotes_activos,
        })
        total_valor += valor

    return {
        'items':          items,
        'total_tipos':    len(items),
        'total_valor_bob': str(total_valor.quantize(Decimal('0.01'))),
    }


def _gather_state(branch) -> tuple[dict, list]:
    """
    Recopila el estado completo del sistema.
    Retorna (data_dict, errors_list).
    Errores en secciones individuales no interrumpen la captura.
    """
    data: dict  = {}
    errors: list = []

    for label, fn in [
        ('capital',  lambda: _gather_capital(branch)),
        ('caja_bob', lambda: _gather_caja_bob(branch)),
        ('divisas',  lambda: _gather_divisas(branch)),
        ('tarjetas', lambda: _gather_tarjetas()),
    ]:
        result, err = _safe(fn, label)
        data[label] = result if result is not None else {'error': err}
        if err:
            errors.append({'section': label, 'error': err})

    return data, errors


# ─────────────────────────────────────────────────────────────────────────────
#  Comparación
# ─────────────────────────────────────────────────────────────────────────────

def _leaf_diff(old, new) -> Optional[dict]:
    """Retorna {from, to, changed: True} si los valores difieren."""
    # Normalizar Decimal-como-string para comparación numérica
    def _norm(v):
        if isinstance(v, str):
            try:
                return str(Decimal(v).normalize())
            except Exception:
                pass
        return v

    if _norm(old) != _norm(new):
        return {'from': old, 'to': new, 'changed': True}
    return None


def _deep_diff(old, new) -> dict:
    """
    Diff recursivo entre dos dicts.
    Retorna un dict con solo los campos que cambiaron.
    """
    if not isinstance(old, dict) or not isinstance(new, dict):
        d = _leaf_diff(old, new)
        return d if d else {}

    changes: dict = {}
    all_keys = set(old.keys()) | set(new.keys())

    for key in sorted(all_keys):
        old_val = old.get(key)
        new_val = new.get(key)

        if isinstance(old_val, dict) and isinstance(new_val, dict):
            sub = _deep_diff(old_val, new_val)
            if sub:
                changes[key] = sub
        elif isinstance(old_val, list) and isinstance(new_val, list):
            # Comparación de listas: detectar añadidos / eliminados / modificados
            if old_val != new_val:
                changes[key] = {'from': old_val, 'to': new_val, 'changed': True}
        else:
            d = _leaf_diff(old_val, new_val)
            if d:
                changes[key] = d

    return changes


def _count_leaf_changes(diff: dict) -> int:
    """Cuenta cuántos campos hoja cambiaron en el diff."""
    count = 0
    for v in diff.values():
        if isinstance(v, dict):
            if v.get('changed'):
                count += 1
            else:
                count += _count_leaf_changes(v)
    return count


# ─────────────────────────────────────────────────────────────────────────────
#  SnapshotService
# ─────────────────────────────────────────────────────────────────────────────

class SnapshotService:
    """
    Interfaz pública del sistema de snapshots.

    Uso desde servicios / señales:
        SnapshotService.schedule(
            module='forex', action='transaction',
            user=request.user, branch=branch,
            metadata={'tx_number': tx.transaction_number, 'amount': str(tx.amount_from)},
        )

    Uso directo (fuerza creación inmediata):
        snap = SnapshotService.create(module='manual', action='on_demand',
                                       user=user, branch=branch, force=True)
    """

    # ── Debounce ──────────────────────────────────────────────────────────────

    @staticmethod
    def _debounce_key(module: str, branch) -> str:
        branch_part = str(branch.id) if branch and branch.id else 'all'
        return f'snap_deb:{module}:{branch_part}'

    @classmethod
    def _is_debounced(cls, module: str, branch) -> bool:
        return bool(cache.get(cls._debounce_key(module, branch)))

    @classmethod
    def _set_debounce(cls, module: str, branch, timeout: int = DEBOUNCE_SECONDS) -> None:
        if timeout and timeout > 0:
            cache.set(cls._debounce_key(module, branch), 1, timeout=timeout)

    # ── Escritura ─────────────────────────────────────────────────────────────

    @classmethod
    def schedule(
        cls,
        module: str,
        action: str,
        user,
        branch=None,
        metadata: Optional[dict] = None,
        debounce_seconds: Optional[int] = None,
        force: bool = False,
    ) -> None:
        """
        Encola la creación del snapshot en transaction.on_commit().
        Nunca bloquea la transacción principal.
        El snapshot se crea SOLO si la TX principal commit con éxito.

        Args:
            debounce_seconds: Override del debounce global para este módulo.
                              None = usa DEBOUNCE_SECONDS global.
                              0    = forzado, sin debounce.
            force:            True = omitir debounce completamente.
        """
        _debounce = debounce_seconds if debounce_seconds is not None else DEBOUNCE_SECONDS
        _force    = force or (_debounce == 0)

        def _callback():
            cls._write(module, action, user, branch, metadata or {},
                       force=_force, debounce_override=_debounce)

        db_tx.on_commit(_callback)

    @classmethod
    def create(
        cls,
        module: str,
        action: str,
        user,
        branch=None,
        metadata: Optional[dict] = None,
        force: bool = False,
    ) -> Optional['SystemSnapshot']:
        """
        Crea el snapshot de forma síncrona e inmediata.
        Usar para snapshots on-demand (cierre de día, apertura, manuales).
        Para uso desde señales post_save, prefer schedule().
        """
        return cls._write(module, action, user, branch, metadata or {}, force=force)

    @classmethod
    def _write(
        cls,
        module: str,
        action: str,
        user,
        branch,
        metadata: dict,
        force: bool = False,
        debounce_override: Optional[int] = None,
    ) -> Optional['SystemSnapshot']:
        """
        Recopila el estado y persiste el snapshot en su propio atomic().
        Retorna el snapshot creado, o None si fue debounced / error.
        """
        from .models import SystemSnapshot

        # Debounce: saltar si ya hay uno reciente (a menos que sea forzado)
        if not force and cls._is_debounced(module, branch):
            log.debug(
                'SNAPSHOT_DEBOUNCED module=%s branch=%s',
                module, branch.code if branch else 'ALL',
            )
            return None

        # Determinar timeout de debounce efectivo para este módulo
        _debounce_timeout = (
            debounce_override
            if debounce_override is not None
            else DEBOUNCE_SECONDS
        )

        try:
            with db_tx.atomic():
                data, errors = _gather_state(branch)

                if errors:
                    metadata = {**metadata, 'gather_errors': errors}

                checksum = SystemSnapshot._compute_checksum(data)
                snap = SystemSnapshot(
                    user          = user,
                    branch        = branch,
                    module        = module,
                    action        = action,
                    data_json     = data,
                    metadata_json = metadata,
                    checksum      = checksum,
                )
                snap.save()

            cls._set_debounce(module, branch, timeout=_debounce_timeout)

            log.info(
                'SNAPSHOT_CREATED id=%s module=%s action=%s branch=%s '
                'capital_total=%s errors=%d',
                snap.id, module, action,
                branch.code if branch else 'ALL',
                snap.capital_total_bob,
                len(errors),
            )
            return snap

        except Exception as exc:
            log.error(
                'SNAPSHOT_WRITE_FAILED module=%s action=%s err=%s',
                module, action, exc, exc_info=True,
            )
            return None

    # ── Comparación ───────────────────────────────────────────────────────────

    @staticmethod
    def compare(snap1: 'SystemSnapshot', snap2: 'SystemSnapshot') -> dict:
        """
        Compara dos snapshots y retorna un diff estructurado.

        El orden importa: snap1 = estado anterior, snap2 = estado posterior.
        Si los IDs están invertidos, se ordenan por timestamp automáticamente.

        Retorna:
        {
          "id1": int, "id2": int,
          "timestamp1": str, "timestamp2": str,
          "user1": str, "user2": str,
          "module1": str, "module2": str,
          "diff": {              ← solo campos que cambiaron
            "capital": {
              "total_bob": {"from": "270000.00", "to": "275000.00", "changed": true}
            },
            "divisas": {...},
          },
          "summary": {
            "modules_changed": ["capital", "divisas"],
            "total_fields_changed": 5,
            "time_delta_seconds": 3600.0,
            "capital_delta_bob": "+5000.00",
          }
        }
        """
        # Ordenar por timestamp: más antiguo = snap1
        if snap1.timestamp > snap2.timestamp:
            snap1, snap2 = snap2, snap1

        diff = _deep_diff(snap1.data_json, snap2.data_json)
        changed_modules = [k for k in diff if k in ('capital', 'caja_bob', 'divisas', 'tarjetas')]
        total_changes   = _count_leaf_changes(diff)

        # Calcular delta de capital
        capital_delta = 'N/A'
        try:
            total1 = Decimal(snap1.data_json.get('capital', {}).get('total_bob', '0') or '0')
            total2 = Decimal(snap2.data_json.get('capital', {}).get('total_bob', '0') or '0')
            delta  = total2 - total1
            capital_delta = f"{delta:+.2f}"
        except Exception:
            pass

        return {
            'id1':        snap1.id,
            'id2':        snap2.id,
            'timestamp1': snap1.timestamp.isoformat(),
            'timestamp2': snap2.timestamp.isoformat(),
            'user1':      snap1.user.username if snap1.user else None,
            'user2':      snap2.user.username if snap2.user else None,
            'module1':    snap1.module,
            'module2':    snap2.module,
            'action1':    snap1.action,
            'action2':    snap2.action,
            'checksum1':  snap1.checksum,
            'checksum2':  snap2.checksum,
            'diff':       diff,
            'summary': {
                'modules_changed':     changed_modules,
                'total_fields_changed': total_changes,
                'time_delta_seconds':  (snap2.timestamp - snap1.timestamp).total_seconds(),
                'capital_delta_bob':   capital_delta,
                'integrity_ok_1':      snap1.verify_integrity(),
                'integrity_ok_2':      snap2.verify_integrity(),
            },
        }
