"""
Capital y patrimonio — Kapitalya FX
====================================
Serie de capital (Control 2025 + Composicion Capital 2026), balance general
(capital propio vs acreedores) y composicion de activos. Solo stdlib.

OJO — errores conocidos del Apps Script que se filtran:
  · saltos de balance > 30% en un periodo (recalculos espurios).
  · "CAPITAL NETO" = total gestionado (propio + acreedores), NO restar.
"""
from __future__ import annotations
import urllib.request, csv, io, re, time, os
from datetime import datetime
from collections import defaultdict

SHEET_2025 = "1WglYfVK8yMDBY_EbD3QgF0h5GPgyANxMzlXBKWhKCGA"
CONTROL_GID = "1654351539"
SHEET_2026 = "1ZAL08c671-3jDAATgOn7MpqngwswKBh4yXIssBTP4xE"
COMPOSICION_GID = "273380543"

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _fetch(sid, gid):
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
            return list(csv.reader(io.StringIO(raw)))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"No se pudo bajar gid={gid}")


def num_us(s):
    """Formato US: '200,000.00' / 'Bs200,000.00' -> 200000.0"""
    s = re.sub(r"[Bs\s$]", "", str(s)).strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def num_eu(s):
    """Formato europeo: '316.117,89' -> 316117.89 ; '(0,00)' -> 0"""
    s = re.sub(r"[Bs\s$]", "", str(s)).strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(".", "").replace(",", ".")
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _mes_num(txt):
    for name, n in _MESES.items():
        if name in txt.lower():
            return n
    return None


def _date(s, mes_hint=None):
    m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s.strip())
    if not m:
        return None
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    cands = []
    for mm, dd in ((a, b), (b, a)):
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            try: cands.append(datetime(y, mm, dd))
            except ValueError: pass
    if not cands:
        return None
    if mes_hint:
        pref = [d for d in cands if d.month == mes_hint]
        if pref:
            return pref[0]
    return cands[0]


def _serie_de(rows, fi, bi, ci, mesi, parse):
    """Extrae (fecha, balance, cambio) filtrando saltos espurios > 30%."""
    out = []
    prev = None
    for r in rows:
        if len(r) <= max(fi, bi): continue
        mes_hint = _mes_num(r[mesi]) if (mesi is not None and len(r) > mesi) else None
        d = _date(r[fi], mes_hint)
        bal = parse(r[bi]) if bi < len(r) else None
        if d is None or bal is None:
            continue
        if prev and bal > prev * 1.30:   # salto > 30% = bug Apps Script
            continue
        cam = parse(r[ci]) if (ci is not None and ci < len(r) and r[ci].strip()) else 0.0
        out.append((d, bal, cam or 0.0))
        prev = bal
    return out


def capital_control():
    """Serie 2025 desde la pestaña Control."""
    rows = _fetch(SHEET_2025, CONTROL_GID)
    hdr = [h.strip() for h in rows[0]]
    mesi = hdr.index("Mes") if "Mes" in hdr else None
    serie = _serie_de(rows[1:], hdr.index("Fecha"), hdr.index("Balance"),
                      hdr.index("Cambio periodo a periodo"), mesi, num_us)
    return serie, _resumen(serie)


def capital_2026():
    """Serie 2026 desde la tabla central de Composicion Capital."""
    rows = _fetch(SHEET_2026, COMPOSICION_GID)
    hdr = [h.strip() for h in rows[0]]
    bi = hdr.index("Balance")
    fi = max(i for i, h in enumerate(hdr[:bi]) if h == "Fecha")
    mesi = max(i for i, h in enumerate(hdr[:bi]) if h == "Mes")
    ci = hdr.index("Cambio periodo a periodo")
    serie = _serie_de(rows[1:], fi, bi, ci, mesi, num_eu)
    return serie, _resumen(serie)


def serie_completa():
    """Combina 2025 (Control) + 2026 (Composicion). Sin solapamiento."""
    s25, _ = capital_control()
    s26, _ = capital_2026()
    serie = sorted(s25 + s26, key=lambda x: x[0])
    return serie, _resumen(serie)


def balance_general():
    """Balance a la fecha, con el modelo del negocio:
       total_general = capital propio + acreedores (lo que se maneja en total).

    Nota de terminologia: en la planilla, la fila 'CAPITAL NETO' es en realidad el
    TOTAL gestionado (propio + acreedores), y 'TOTAL ACTIVOS' es el capital propio.
    """
    rows = _fetch(SHEET_2026, COMPOSICION_GID)
    det_i, mon_i = 1, 2   # columnas Detalle / Monto (Bs)
    propio = total = acreedores_tot = None
    acreedores = []
    for r in rows[1:]:
        if len(r) <= mon_i: continue
        det = r[det_i].strip().lower()
        val = num_eu(r[mon_i])
        if val is None: continue
        if det == "total activos": propio = val            # capital propio del dueño
        elif det == "capital neto": total = val            # total gestionado (propio+acreed)
        elif det == "total pasivos": acreedores_tot = val  # deuda con acreedores
        elif det.startswith("acreedor") and val > 0:
            acreedores.append((r[det_i].strip(), val))
    if total is None and propio is not None and acreedores_tot is not None:
        total = propio + acreedores_tot
    propio_pct = (propio / total * 100) if (propio and total) else None
    return dict(capital_propio=propio, acreedores=acreedores_tot, total_general=total,
                propio_pct=propio_pct, acreedores_detalle=acreedores)


def composicion_activos():
    """Buckets de activos del negocio desde Composicion Capital (valores vivos)."""
    rows = _fetch(SHEET_2026, COMPOSICION_GID)
    det_i, mon_i = 1, 2
    want = {
        "divisas":    "subtotal divisas",
        "bancos":     "subtotal bolivianos operativ",
        "inventario": "tarjetas telefonicas",
        "usdc":       "inversión (usdc)",
        "total":      "total activos",
    }
    out = {}
    for r in rows[1:]:
        if len(r) <= mon_i:
            continue
        det = r[det_i].strip().lower()
        val = num_eu(r[mon_i])
        if val is None:
            continue
        for key, label in want.items():
            if key not in out and label in det:
                out[key] = val
    return out


def _resumen(serie):
    por_mes, bal_mes = defaultdict(float), {}
    for d, bal, cam in serie:
        por_mes[d.strftime("%Y-%m")] += cam
        bal_mes[d.strftime("%Y-%m")] = bal
    mejor = max(por_mes.items(), key=lambda x: x[1]) if por_mes else ("-", 0)
    return dict(
        fecha_inicio=serie[0][0].date(), fecha_fin=serie[-1][0].date(),
        balance_inicio=serie[0][1], balance_fin=serie[-1][1],
        crecimiento=serie[-1][1] - serie[0][1],
        por_mes=dict(sorted(por_mes.items())), balance_mes=dict(sorted(bal_mes.items())),
        mejor_mes=mejor[0], mejor_mes_bs=mejor[1],
    )


def write_csvs(out_dir=None, serie=None, bg=None):
    """Escribe capital_serie.csv, balance_general.csv y acreedores.csv."""
    out_dir = out_dir or os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(out_dir, exist_ok=True)
    if serie is None:
        serie, _ = serie_completa()
    if bg is None:
        bg = balance_general()
    with open(os.path.join(out_dir, "capital_serie.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["fecha", "mes", "balance", "cambio_periodo"])
        for d, bal, cam in serie:
            w.writerow([d.date(), d.strftime("%Y-%m"), bal, cam])
    with open(os.path.join(out_dir, "balance_general.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["metrica", "valor_bs"])
        for k in ("capital_propio", "acreedores", "total_general"):
            if bg.get(k) is not None:
                w.writerow([k, bg[k]])
    with open(os.path.join(out_dir, "acreedores.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["acreedor", "valor_bs"])
        for a, v in bg.get("acreedores_detalle", []):
            w.writerow([a, v])


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    serie, res = serie_completa()
    print(f"Capital {res['fecha_inicio']} -> {res['fecha_fin']}: "
          f"Bs {res['balance_inicio']:,.0f} -> Bs {res['balance_fin']:,.0f} "
          f"(+Bs {res['crecimiento']:,.0f})")
    print(f"Mejor mes (cambio capital): {res['mejor_mes']} = Bs {res['mejor_mes_bs']:,.0f}")
    bg = balance_general()
    print(f"\nBalance general:")
    print(f"  Capital propio:   Bs {bg['capital_propio']:,.0f}  ({bg['propio_pct']:.0f}% del total)")
    print(f"  Acreedores:       Bs {bg['acreedores']:,.0f}")
    print(f"  Total gestionado: Bs {bg['total_general']:,.0f}")
    for a, v in bg['acreedores_detalle']:
        print(f"    - {a}: Bs {v:,.0f}")
