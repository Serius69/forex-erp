# snapshots/comparison.py
"""
SnapshotComparisonEngine — enriched side-by-side analysis of two system states.

Builds on top of the basic SnapshotService.compare() deep-diff and adds:

  capital_diff — structured, field-by-field breakdown with before/after/delta/delta_pct
  alerts       — anomaly detections from AlertEngine (CRITICAL → WARNING → INFO)

Response shape
--------------
{
  "id1": int,  "id2": int,
  "timestamp1": ISO,  "timestamp2": ISO,
  "user1": str,  "user2": str,
  "module1": str,  "module2": str,
  "action1": str,  "action2": str,
  "checksum1": str,  "checksum2": str,
  "diff": { ... },            ← recursive deep diff of entire data_json

  "capital_diff": {
    "total_bob":    { before, after, delta, delta_pct, changed },
    "efectivo_bob": { ... },
    "qr_bob":       { ... },
    "divisas_bob":  { ... },
    "tarjetas_bob": { ... },
    "pasivos_bob":  { ... },
    "divisas": {
      "USD": {
        before_stock, after_stock, delta_stock, delta_stock_pct,
        before_valor_bob, after_valor_bob, delta_valor_bob,
        tc_venta, changed
      },
      ...
    },
    "tarjetas": {
      "TIGO 10": {
        before_stock, after_stock, delta_stock, delta_stock_pct,
        before_valor_bob, after_valor_bob, delta_valor_bob,
        changed
      },
      ...
    },
    "gather_errors_snap1": [...] | None,
    "gather_errors_snap2": [...] | None,
  },

  "alerts": [
    {
      "type":     "LOSS_DETECTED",
      "severity": "CRITICAL",
      "message":  "...",
      "field":    "capital.total_bob",
      "before":   "190000.00",
      "after":    "185000.00",
      "delta":    "-5000.00",
      "delta_pct": "-2.63",
      "currency": "BOB",
      "amount":   "-5000.00"
    },
    ...
  ],

  "summary": {
    "modules_changed":      [...],
    "total_fields_changed": int,
    "time_delta_seconds":   float,
    "capital_delta_bob":    "+5000.00",
    "integrity_ok_1":       bool,
    "integrity_ok_2":       bool,
    "has_critical_alerts":  bool,
    "alert_count":          int,
    "alert_types":          [str, ...]
  }
}
"""
from decimal import Decimal

from .alerts import AlertEngine, _d, _pct, _fmt_pct

# Capital fields present at the top level of data_json['capital']
_CAPITAL_TOP_FIELDS = (
    'total_bob',
    'efectivo_bob',
    'qr_bob',
    'divisas_bob',
    'tarjetas_bob',
    'pasivos_bob',
)


def _field_diff(v1_raw, v2_raw, *, decimal_places: int = 2) -> dict:
    """Return a diff dict for a single numeric field."""
    v1    = _d(v1_raw, '0')
    v2    = _d(v2_raw, '0')
    delta = v2 - v1
    pct   = _pct(delta, v1)
    fmt   = f'+.{decimal_places}f'
    return {
        'before':    str(v1),
        'after':     str(v2),
        'delta':     format(delta, fmt),
        'delta_pct': _fmt_pct(pct),
        'changed':   delta != 0,
    }


class SnapshotComparisonEngine:
    """
    Orchestrates full comparison + alert detection between two snapshots.

    Ensures the earlier snapshot is always snap1 (ordered by timestamp).
    """

    def __init__(self, snap1, snap2):
        if snap1.timestamp > snap2.timestamp:
            snap1, snap2 = snap2, snap1
        self.snap1 = snap1
        self.snap2 = snap2
        self.d1 = snap1.data_json or {}
        self.d2 = snap2.data_json or {}

    # ── Capital diff builder ─────────────────────────────────────────────────

    def _build_capital_diff(self) -> dict:
        cap1 = self.d1.get('capital') or {}
        cap2 = self.d2.get('capital') or {}

        result: dict = {}

        # Top-level BOB fields
        for field in _CAPITAL_TOP_FIELDS:
            result[field] = _field_diff(cap1.get(field), cap2.get(field))

        # Per-currency breakdown (from capital.detalle_divisas)
        det1: dict = cap1.get('detalle_divisas') or {}
        det2: dict = cap2.get('detalle_divisas') or {}
        all_currencies = sorted(set(det1) | set(det2))

        divisas: dict = {}
        for code in all_currencies:
            c1 = det1.get(code) or {}
            c2 = det2.get(code) or {}

            s1 = _d(c1.get('stock', '0'))
            s2 = _d(c2.get('stock', '0'))
            v1 = _d(c1.get('valor_bob', '0'))
            v2 = _d(c2.get('valor_bob', '0'))
            d_stock = s2 - s1
            d_valor = v2 - v1
            pct_stock = _pct(d_stock, s1)

            divisas[code] = {
                'before_stock':    str(s1),
                'after_stock':     str(s2),
                'delta_stock':     format(d_stock, '+.4f'),
                'delta_stock_pct': _fmt_pct(pct_stock),
                'before_valor_bob': str(v1),
                'after_valor_bob':  str(v2),
                'delta_valor_bob':  format(d_valor, '+.2f'),
                'tc_venta':        c2.get('tc_venta') or c1.get('tc_venta'),
                'changed':         d_stock != 0 or d_valor != 0,
            }

        result['divisas'] = divisas

        # Per-card-type breakdown (from capital.detalle_tarjetas)
        tdet1: dict = cap1.get('detalle_tarjetas') or {}
        tdet2: dict = cap2.get('detalle_tarjetas') or {}
        all_cards = sorted(set(tdet1) | set(tdet2))

        tarjetas: dict = {}
        for nombre in all_cards:
            t1 = tdet1.get(nombre) or {}
            t2 = tdet2.get(nombre) or {}

            s1 = _d(t1.get('stock', '0'))
            s2 = _d(t2.get('stock', '0'))
            v1 = _d(t1.get('valor_bob', '0'))
            v2 = _d(t2.get('valor_bob', '0'))
            d_stock = s2 - s1
            d_valor = v2 - v1
            pct_stock = _pct(d_stock, s1)

            tarjetas[nombre] = {
                'before_stock':    str(s1),
                'after_stock':     str(s2),
                'delta_stock':     format(d_stock, '+.0f'),
                'delta_stock_pct': _fmt_pct(pct_stock),
                'before_valor_bob': str(v1),
                'after_valor_bob':  str(v2),
                'delta_valor_bob':  format(d_valor, '+.2f'),
                'changed':         d_stock != 0 or d_valor != 0,
            }

        result['tarjetas'] = tarjetas

        # Surface any gather errors that were recorded during snapshot creation
        result['gather_errors_snap1'] = (
            (self.snap1.metadata_json or {}).get('gather_errors') or None
        )
        result['gather_errors_snap2'] = (
            (self.snap2.metadata_json or {}).get('gather_errors') or None
        )

        return result

    # ── Main entry point ─────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Execute full comparison and return the enriched response dict.

        Calls SnapshotService.compare() for the deep diff, then layers
        capital_diff and alerts on top.
        """
        from .services import SnapshotService

        # Deep diff (existing service — don't duplicate)
        base: dict = SnapshotService.compare(self.snap1, self.snap2)

        # Structured capital analysis
        capital_diff = self._build_capital_diff()

        # Anomaly detection
        alerts = AlertEngine(
            self.d1, self.d2,
            snap1=self.snap1,
            snap2=self.snap2,
        ).run()

        has_critical = any(a['severity'] == 'CRITICAL' for a in alerts)

        return {
            **base,
            'capital_diff': capital_diff,
            'alerts': alerts,
            'summary': {
                **base['summary'],
                'has_critical_alerts': has_critical,
                'alert_count':         len(alerts),
                'alert_types':         sorted({a['type'] for a in alerts}),
            },
        }
