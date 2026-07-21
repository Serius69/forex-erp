# snapshots/alerts.py
"""
Alert detection engine for snapshot comparisons.

Analyses two SystemSnapshot.data_json dicts and emits structured alerts when
financial anomalies are detected.  All checks are independent — a failure in
one never prevents the others from running.

Alert types
-----------
LOSS_DETECTED       — Capital total decreased beyond configured threshold
NEGATIVE_BALANCE    — Any balance (capital, currency stock) is < 0
INVENTORY_MISMATCH  — physical + digital ≠ total for a currency record
SUDDEN_SPIKE        — Capital increased unusually fast (possible entry error)
EFECTIVO_DROP       — Cash-on-hand fell beyond configured threshold
CURRENCY_DROP       — Individual currency stock fell beyond % threshold
INTEGRITY_FAILURE   — SHA-256 checksum mismatch on either snapshot

Severity levels
---------------
CRITICAL — Requires immediate review (missing money, negative balance, tampered data)
WARNING  — Unusual movement that warrants attention
INFO     — Informational; large but expected movement
"""
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.conf import settings

log = logging.getLogger('snapshots.alerts')

# ── Severity constants ────────────────────────────────────────────────────────
CRITICAL = 'CRITICAL'
WARNING  = 'WARNING'
INFO     = 'INFO'

_SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}


# ── Decimal helpers ───────────────────────────────────────────────────────────

def _d(val, default: str = '0') -> Decimal:
    """Safe Decimal conversion — never raises."""
    try:
        return Decimal(str(val)).normalize()
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _pct(delta: Decimal, base: Decimal) -> Optional[Decimal]:
    """Percentage change as Decimal; None when base is zero (avoids div-by-zero)."""
    if base == 0:
        return None
    return (delta / base * 100).quantize(Decimal('0.01'))


def _fmt_pct(pct: Optional[Decimal]) -> Optional[str]:
    return f"{pct:+.2f}" if pct is not None else None


# ── Default thresholds (override in Django settings) ─────────────────────────
_DEFAULTS: dict[str, Decimal] = {
    'ALERT_CAPITAL_DROP_MIN_BOB': Decimal('100'),   # min absolute drop (BOB)
    'ALERT_CAPITAL_DROP_MIN_PCT': Decimal('0.5'),   # min % drop
    'ALERT_SUDDEN_SPIKE_PCT':     Decimal('25.0'),  # % increase = spike
    'ALERT_EFECTIVO_DROP_BOB':    Decimal('500'),   # min cash drop (BOB)
    'ALERT_CURRENCY_DROP_PCT':    Decimal('30.0'),  # % stock drop per currency
}


def _threshold(name: str) -> Decimal:
    raw = getattr(settings, name, None)
    if raw is not None:
        return _d(raw)
    return _DEFAULTS[name]


# ─────────────────────────────────────────────────────────────────────────────
#  AlertEngine
# ─────────────────────────────────────────────────────────────────────────────

class AlertEngine:
    """
    Stateful alert detector.  Instantiate, call run(), consume .alerts.

    Parameters
    ----------
    data1, data2 : dict
        data_json of the earlier and later snapshot respectively.
    snap1, snap2 : SystemSnapshot instances (optional)
        Required only for integrity checks.
    """

    def __init__(self, data1: dict, data2: dict, snap1=None, snap2=None):
        self.d1 = data1 or {}
        self.d2 = data2 or {}
        self.snap1 = snap1
        self.snap2 = snap2
        self.alerts: list[dict] = []

    # ── Internal emit helper ─────────────────────────────────────────────────

    def _emit(self, alert_type: str, severity: str, message: str, **extra):
        entry = {'type': alert_type, 'severity': severity, 'message': message, **extra}
        self.alerts.append(entry)
        log.warning(
            'SNAPSHOT_ALERT type=%s severity=%s %s',
            alert_type, severity, message,
        )
        return entry

    # ── Check 1: capital total change ────────────────────────────────────────

    def _check_capital_total(self):
        cap1 = self.d1.get('capital') or {}
        cap2 = self.d2.get('capital') or {}

        total1 = _d(cap1.get('total_bob', '0'))
        total2 = _d(cap2.get('total_bob', '0'))
        delta  = total2 - total1

        if delta < 0:
            abs_drop   = abs(delta)
            pct        = _pct(delta, total1)
            min_bob    = _threshold('ALERT_CAPITAL_DROP_MIN_BOB')
            min_pct    = _threshold('ALERT_CAPITAL_DROP_MIN_PCT')

            significant_abs = abs_drop >= min_bob
            significant_pct = pct is None or abs(pct) >= min_pct

            if significant_abs and significant_pct:
                self._emit(
                    'LOSS_DETECTED', CRITICAL,
                    f'Capital total disminuyó BOB {abs_drop:.2f} '
                    f'({_fmt_pct(pct) or "N/A"}%) — de {total1:.2f} → {total2:.2f}.',
                    field='capital.total_bob',
                    before=str(total1),
                    after=str(total2),
                    delta=f'{delta:+.2f}',
                    delta_pct=_fmt_pct(pct),
                    currency='BOB',
                    amount=f'{delta:+.2f}',
                )

        elif delta > 0:
            pct       = _pct(delta, total1)
            spike_pct = _threshold('ALERT_SUDDEN_SPIKE_PCT')

            if pct is not None and pct >= spike_pct:
                self._emit(
                    'SUDDEN_SPIKE', WARNING,
                    f'Capital total subió BOB {delta:.2f} (+{pct:.2f}%) '
                    f'inusualmente rápido — de {total1:.2f} → {total2:.2f}.',
                    field='capital.total_bob',
                    before=str(total1),
                    after=str(total2),
                    delta=f'{delta:+.2f}',
                    delta_pct=_fmt_pct(pct),
                    currency='BOB',
                    amount=f'{delta:+.2f}',
                )

    # ── Check 2: negative balances in either snapshot ────────────────────────

    def _check_negative_balances(self):
        CAPITAL_FIELDS = ('total_bob', 'efectivo_bob', 'qr_bob',
                          'divisas_bob', 'tarjetas_bob')

        for label, data in (('snap1', self.d1), ('snap2', self.d2)):
            cap = data.get('capital') or {}

            for field in CAPITAL_FIELDS:
                val = _d(cap.get(field, '0'))
                if val < 0:
                    self._emit(
                        'NEGATIVE_BALANCE', CRITICAL,
                        f'Balance negativo en {label}.capital.{field}: {val:.2f} BOB.',
                        field=f'capital.{field}',
                        snapshot=label,
                        value=str(val),
                        currency='BOB',
                        amount=str(val),
                    )

            # Currency-level stocks
            for item in (data.get('divisas') or []):
                currency = item.get('currency', '?')
                for key in ('physical', 'digital', 'total'):
                    val = _d(item.get(key, '0'))
                    if val < 0:
                        self._emit(
                            'NEGATIVE_BALANCE', CRITICAL,
                            f'Balance negativo: {label}.divisas.{currency}.{key} = {val:.4f}.',
                            field=f'divisas.{currency}.{key}',
                            snapshot=label,
                            currency=currency,
                            value=str(val),
                            amount=str(val),
                        )

    # ── Check 3: inventory internal consistency ──────────────────────────────

    def _check_inventory_mismatch(self):
        """physical + digital must equal declared total (tolerance: 0.02)."""
        TOLERANCE = Decimal('0.02')

        for label, data in (('snap1', self.d1), ('snap2', self.d2)):
            for item in (data.get('divisas') or []):
                currency = item.get('currency', '?')
                physical = _d(item.get('physical', '0'))
                digital  = _d(item.get('digital',  '0'))
                total    = _d(item.get('total',     '0'))
                expected = physical + digital
                disc     = abs(total - expected)

                if disc > TOLERANCE:
                    self._emit(
                        'INVENTORY_MISMATCH', WARNING,
                        f'{label}.divisas.{currency}: '
                        f'physical({physical:.4f}) + digital({digital:.4f}) = {expected:.4f} '
                        f'≠ total({total:.4f}). Discrepancia: {disc:.4f}.',
                        field=f'divisas.{currency}.total',
                        snapshot=label,
                        currency=currency,
                        physical=str(physical),
                        digital=str(digital),
                        declared_total=str(total),
                        expected_total=str(expected),
                        discrepancy=str(disc),
                        amount=str(disc),
                    )

    # ── Check 4: cash-on-hand drop ───────────────────────────────────────────

    def _check_efectivo_drop(self):
        cap1 = self.d1.get('capital') or {}
        cap2 = self.d2.get('capital') or {}

        ef1 = _d(cap1.get('efectivo_bob', '0'))
        ef2 = _d(cap2.get('efectivo_bob', '0'))
        delta = ef2 - ef1

        if delta < 0 and abs(delta) >= _threshold('ALERT_EFECTIVO_DROP_BOB'):
            pct = _pct(delta, ef1)
            self._emit(
                'EFECTIVO_DROP', WARNING,
                f'Efectivo BOB bajó {abs(delta):.2f} ({_fmt_pct(pct) or "N/A"}%) '
                f'— de {ef1:.2f} → {ef2:.2f}.',
                field='capital.efectivo_bob',
                before=str(ef1),
                after=str(ef2),
                delta=f'{delta:+.2f}',
                delta_pct=_fmt_pct(pct),
                currency='BOB',
                amount=f'{delta:+.2f}',
            )

    # ── Check 5: per-currency stock drop ─────────────────────────────────────

    def _check_currency_drops(self):
        threshold_pct = _threshold('ALERT_CURRENCY_DROP_PCT')

        def _aggregate(data: dict) -> dict[str, Decimal]:
            """Sum total stock per currency across branches."""
            idx: dict[str, Decimal] = {}
            for item in (data.get('divisas') or []):
                code = item.get('currency')
                if code:
                    idx[code] = idx.get(code, Decimal('0')) + _d(item.get('total', '0'))
            return idx

        stocks1 = _aggregate(self.d1)
        stocks2 = _aggregate(self.d2)

        for currency in sorted(set(stocks1) | set(stocks2)):
            s1    = stocks1.get(currency, Decimal('0'))
            s2    = stocks2.get(currency, Decimal('0'))
            delta = s2 - s1

            if delta < 0 and s1 > 0:
                pct = _pct(delta, s1)
                if pct is not None and abs(pct) >= threshold_pct:
                    self._emit(
                        'CURRENCY_DROP', WARNING,
                        f'Stock de {currency} bajó {abs(delta):.4f} ({_fmt_pct(pct)}%) '
                        f'— de {s1:.4f} → {s2:.4f}.',
                        field=f'divisas.{currency}.total',
                        currency=currency,
                        before=str(s1),
                        after=str(s2),
                        delta=f'{delta:+.4f}',
                        delta_pct=_fmt_pct(pct),
                        amount=f'{delta:+.4f}',
                    )

    # ── Check 6: checksum integrity ──────────────────────────────────────────

    def _check_integrity(self):
        for snap, label in ((self.snap1, 'snap1'), (self.snap2, 'snap2')):
            if snap is None:
                continue
            try:
                ok = snap.verify_integrity()
            except Exception:
                ok = False

            if not ok:
                log.critical(
                    'SNAPSHOT_INTEGRITY_FAIL id=%s during comparison', snap.id,
                )
                self._emit(
                    'INTEGRITY_FAILURE', CRITICAL,
                    f'{label} (id={snap.id}) falló verificación SHA-256. '
                    f'El data_json puede haber sido alterado.',
                    field='checksum',
                    snapshot_id=snap.id,
                    stored_checksum=snap.checksum,
                    amount=None,
                )

    # ── Runner ───────────────────────────────────────────────────────────────

    def run(self) -> list[dict]:
        """
        Execute all checks and return the alert list sorted by severity.
        Exceptions in individual checks are swallowed so one bad check
        never prevents the rest from running.
        """
        checks = [
            self._check_integrity,
            self._check_negative_balances,
            self._check_inventory_mismatch,
            self._check_capital_total,
            self._check_efectivo_drop,
            self._check_currency_drops,
        ]
        for check in checks:
            try:
                check()
            except Exception as exc:
                log.error('ALERT_CHECK_FAILED check=%s err=%s', check.__name__, exc, exc_info=True)

        self.alerts.sort(key=lambda a: _SEVERITY_ORDER.get(a.get('severity', INFO), 3))
        return self.alerts
