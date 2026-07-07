"""
Gastos y movimientos de capital — Kapitalya FX
================================================
Extrae la pestaña 'CATEGORIZACIÓN DE GASTOS' del sheet 2026 (cubre feb-2025+) y
clasifica cada movimiento: gasto / retiro / deposito / activo_vehiculo / ingreso.
Permite el "panorama neto" (margen − gastos = resultado operativo).

GOTCHA: la pestaña mezcla fechas DD/MM/YYYY y MM/DD/YYYY -> desambiguar con la
columna 'Mes'. Un parser estricto descarta ~40% de las filas.
"""
from __future__ import annotations
import urllib.request, csv, io, re, time, os
from datetime import datetime
from collections import defaultdict

SHEET_2026 = "1ZAL08c671-3jDAATgOn7MpqngwswKBh4yXIssBTP4xE"
GASTOS_GID = "1137310189"

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _mes_num(mes_txt: str):
    for name, n in _MESES.items():
        if name in mes_txt.lower():
            return n
    return None


def _parse_date(s: str, mes_hint):
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


def _eu(s):
    s = re.sub(r"[Bs\s$]", "", str(s)).replace(".", "").replace(",", ".")
    try: return float(s)
    except ValueError: return None


def _classify(cat: str) -> str:
    c = cat.lower()
    if c.startswith("ingresos"): return "ingreso"
    if "retiros en efectivo" in c: return "retiro"
    if "depósito" in c or "deposito" in c: return "deposito"
    if "vehículo" in c or "vehiculo" in c: return "activo_vehiculo"
    return "gasto"


def _fetch():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_2026}/export?format=csv&gid={GASTOS_GID}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = None
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
            break
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    return list(csv.reader(io.StringIO(raw)))


def _movimientos():
    """Devuelve lista de (fecha, categoria, clase, monto)."""
    rows = _fetch()
    hdr = [h.strip() for h in rows[0]]
    ci, mi, fi = hdr.index("Categoría"), hdr.index("Monto (BOB)"), hdr.index("Fecha")
    mesi = hdr.index("Mes") if "Mes" in hdr else None
    out = []
    for r in rows[1:]:
        if len(r) <= max(ci, mi, fi): continue
        c = r[ci].strip(); m = _eu(r[mi])
        if not c or m is None: continue
        mes_hint = _mes_num(r[mesi]) if (mesi is not None and len(r) > mesi) else None
        d = _parse_date(r[fi], mes_hint)
        if d is None:
            continue
        out.append((d, c, _classify(c), m))
    return out


def gastos_clasificados():
    """Devuelve (by_class, by_class_mes, by_cat_mes)."""
    by_class = defaultdict(float)
    by_class_mes = defaultdict(lambda: defaultdict(float))
    by_cat_mes = defaultdict(lambda: defaultdict(float))
    for d, c, k, m in _movimientos():
        ym = d.strftime("%Y-%m")
        by_class[k] += m
        by_class_mes[ym][k] += m
        if k == "gasto":
            by_cat_mes[ym][c] += m
    return (dict(by_class),
            {m: dict(v) for m, v in by_class_mes.items()},
            {m: dict(v) for m, v in by_cat_mes.items()})


def write_csv(path=None):
    """Escribe los movimientos clasificados a CSV. Devuelve (path, n)."""
    path = path or os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "gastos_clasificados.csv"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    movs = _movimientos()
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["fecha", "mes", "categoria", "clase", "monto_bs"])
        for d, c, k, m in movs:
            w.writerow([d.date(), d.strftime("%Y-%m"), c, k, m])
    return path, len(movs)


def panorama(margen: float, lo: str, hi: str):
    """Panorama financiero neto alineado a la ventana [lo, hi] (YYYY-MM)."""
    _, by_class_mes, by_cat_mes = gastos_clasificados()

    def suma(clase):
        return sum(by_class_mes[m].get(clase, 0) for m in by_class_mes if lo <= m <= hi)

    g_op = suma("gasto"); ing = suma("ingreso")
    ret = suma("retiro"); dep = suma("deposito")
    resultado_op = margen + ing - g_op
    var_capital = resultado_op - (ret - dep)

    cat_win = defaultdict(float)
    for m in by_cat_mes:
        if lo <= m <= hi:
            for c, v in by_cat_mes[m].items():
                cat_win[c] += v
    top = sorted(cat_win.items(), key=lambda x: -x[1])[:8]

    veh_manual = sum(by_class_mes[m].get("activo_vehiculo", 0)
                     for m in by_class_mes if m < lo)

    return dict(margen=margen, gasto_op=g_op, ingreso=ing, retiro_neto=ret - dep,
                resultado_op=resultado_op, var_capital=var_capital,
                top=top, veh_manual=veh_manual)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    bc, _, _ = gastos_clasificados()
    print("Por clase (todo el período):", {k: round(v) for k, v in bc.items()})
