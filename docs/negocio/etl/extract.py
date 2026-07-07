"""
EXTRACT automatizado — Kapitalya FX
====================================
Lee las transacciones directamente desde los Google Sheets de registro
(via el endpoint CSV publico, sin credenciales) y las normaliza a un dataset
canonico unico, reproducible. Reemplaza el export manual de Power BI.

Fuentes:
  - Sheet 2025: pestañas mensuales Compras*/Ventas* (formato US, fecha M/D o D/M).
  - Sheet 2026: pestaña 'Transacciones' (formato europeo, coma decimal).
Sin solapamiento: el sheet 2025 solo tiene 2025; el 2026 solo 2026.

Uso:
    python extract.py                 # escribe ../data/canonico.csv
Solo stdlib — corre en cualquier Python 3.9+.
"""
from __future__ import annotations
import urllib.request, csv, io, re, sys, os, time
from datetime import datetime
from collections import Counter, defaultdict

# ── Configuracion de fuentes ──────────────────────────────────────────────────
SHEET_2025 = "1WglYfVK8yMDBY_EbD3QgF0h5GPgyANxMzlXBKWhKCGA"
SHEET_2026 = "1ZAL08c671-3jDAATgOn7MpqngwswKBh4yXIssBTP4xE"

# (gid, tipo, meses esperados) — el mes desambigua fechas M/D vs D/M
TABS_2025 = [
    ("229619694",  "BUY",  {6, 7}),   ("90191991",   "SELL", {6, 7}),
    ("203803298",  "BUY",  {8}),      ("1388970614", "SELL", {8}),
    ("545806606",  "BUY",  {9}),      ("614567942",  "SELL", {9}),
    ("657374253",  "BUY",  {10}),     ("296504743",  "SELL", {10}),
    ("129038777",  "BUY",  {11}),     ("1010497893", "SELL", {11}),
    ("246490476",  "BUY",  {12}),     ("1655158284", "SELL", {12}),
]
TX_2026_GID = "59929513"   # pestaña 'Transacciones'

# Nombres legibles de las pestañas 2025 (para los snapshots raw)
NOMBRE_2025 = {
    "229619694": "compras_jun_jul", "90191991": "ventas_jun_jul",
    "203803298": "compras_ago", "1388970614": "ventas_ago",
    "545806606": "compras_sep", "614567942": "ventas_sep",
    "657374253": "compras_oct", "296504743": "ventas_oct",
    "129038777": "compras_nov", "1010497893": "ventas_nov",
    "246490476": "compras_dic", "1655158284": "ventas_dic",
}

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# ── Helpers de parsing ────────────────────────────────────────────────────────
def fetch(sid: str, gid: str, retries: int = 3) -> list[list[str]]:
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last = None
    for attempt in range(retries):
        try:
            raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
            return list(csv.reader(io.StringIO(raw)))
        except Exception as exc:  # noqa: BLE001 — reintento ante timeouts/transitorios
            last = exc
            time.sleep(2 * (attempt + 1))
    raise last


def num_us(s: str):
    """Formato US: '1,580.00' / 'Bs15.80' -> 1580.0 / 15.8"""
    s = re.sub(r"[Bs\s$]", "", str(s)).replace(",", "")
    try: return float(s)
    except ValueError: return None


def num_eu(s: str):
    """Formato europeo: '4.000,00' / '9,5' -> 4000.0 / 9.5"""
    s = re.sub(r"[Bs\s$]", "", str(s)).replace(".", "").replace(",", ".")
    try: return float(s)
    except ValueError: return None


def parse_date(s: str, months: set | None):
    """Desambigua M/D vs D/M usando el mes esperado del tab."""
    m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s.strip())
    if not m: return None
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100: y += 2000
    cands = []
    for mm, dd in ((a, b), (b, a)):
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            try: cands.append(datetime(y, mm, dd))
            except ValueError: pass
    if not cands: return None
    if months:
        pref = [d for d in cands if d.month in months]
        if pref: return pref[0]
    return cands[0]


def norm_divisa(d: str) -> tuple[str, str | None]:
    """Normaliza 'USD  BOB'->USD, 'USD sueltos'->(USD,SUELTOS), etc."""
    low = d.lower().strip()
    if "suelto" in low: return "USD", "SUELTOS"
    if "1 y 2" in low:  return "USD", "SINGLES"
    if "pen" in low and "mon" in low: return "PEN", None
    toks = [t for t in re.split(r"\s+", d.strip()) if t.upper() != "BOB"]
    return (toks[0].upper() if toks else d.strip().upper()), None


def col(row, hdr, *names):
    for n in names:
        if n in hdr:
            i = hdr.index(n)
            if i < len(row): return row[i].strip()
    return ""


# ── Extraccion ────────────────────────────────────────────────────────────────
def extract() -> tuple[list[dict], Counter]:
    rows, anom = [], Counter()

    # 2025 — pestañas mensuales (formato US)
    for gid, tipo, months in TABS_2025:
        data = fetch(SHEET_2025, gid)
        hdr = [h.strip() for h in data[0]]
        for r in data[1:]:
            if not any(c.strip() for c in r): continue
            d = parse_date(col(r, hdr, "Fecha"), months)
            div = col(r, hdr, "Moneda", "Divisa")
            q = num_us(col(r, hdr, "Monto Comprado", "Monto Vendido", "Cantidad"))
            rate = num_us(col(r, hdr, "Tipo de Cambio (Bs)", "Tipo Cambio (Bs)"))
            tot = num_us(col(r, hdr, "Total en Bolivianos (Bs)", "Total Bs"))
            if not d: anom["2025 fecha mala"] += 1; continue
            if not div or q is None or rate is None: anom["2025 incompleta"] += 1; continue
            code, denom = norm_divisa(div)
            rows.append(_rec(d, tipo, code, denom, q, rate, tot,
                             col(r, hdr, "Medio de Pago", "Medio Pago"),
                             col(r, hdr, "Responsable"), "2025"))

    # 2026 — pestaña Transacciones (formato europeo)
    data = fetch(SHEET_2026, TX_2026_GID)
    hdr = [h.strip() for h in data[0]]
    tmap = {"compra": "BUY", "venta": "SELL"}
    for r in data[1:]:
        if not any(c.strip() for c in r): continue
        tipo = tmap.get(col(r, hdr, "Tipo").lower())
        if not tipo: anom["2026 tipo desconocido"] += 1; continue
        mes = col(r, hdr, "Mes")
        try: mset = {int(float(mes.replace(',', '.')))} if mes else None
        except ValueError: mset = None
        d = parse_date(col(r, hdr, "Fecha"), mset)
        div = col(r, hdr, "Divisa")
        q = num_eu(col(r, hdr, "Cantidad"))
        rate = num_eu(col(r, hdr, "Tipo Cambio (Bs)"))
        tot = num_eu(col(r, hdr, "Total Bs"))
        if not d: anom["2026 fecha mala"] += 1; continue
        if not div or q is None or rate is None: anom["2026 incompleta"] += 1; continue
        code, denom = norm_divisa(div)
        rows.append(_rec(d, tipo, code, denom, q, rate, tot,
                         col(r, hdr, "Medio Pago"), col(r, hdr, "Responsable"), "2026"))

    rows.sort(key=lambda r: (r["fecha"], 0 if r["tipo"] == "BUY" else 1))
    return rows, anom


def _rec(d, tipo, code, denom, q, rate, tot, medio, resp, src):
    return dict(fecha=d, tipo=tipo, divisa=code, denom=denom or "",
                cantidad=q, tipo_cambio=rate,
                total_bs=tot if tot is not None else q * rate,
                medio_pago=(medio or "Efectivo").strip(),
                responsable=(resp or "(sin)").strip() or "(sin)", fuente=src)


def write_csv(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cols = ["fecha", "tipo", "divisa", "denom", "cantidad", "tipo_cambio",
            "total_bs", "medio_pago", "responsable", "fuente"]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({**r, "fecha": r["fecha"].date()})


def write_raw_sources(out_dir=None) -> list[dict]:
    """Guarda un snapshot completo de cada pestaña usada + _manifest.csv."""
    out_dir = out_dir or os.path.join(OUT_DIR, "raw")
    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    fuentes = []
    for gid, tipo, _m in TABS_2025:
        fuentes.append(("2025", "transacciones", tipo, NOMBRE_2025.get(gid, gid),
                        SHEET_2025, gid))
    fuentes.append(("2026", "transacciones", "MIXTO", "transacciones", SHEET_2026, TX_2026_GID))
    ts = datetime.now().isoformat(timespec="seconds")
    for year, dataset, kind, tab, sid, gid in fuentes:
        data = fetch(sid, gid)
        fname = f"{year}_{dataset}_{tab}_{gid}.csv"
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(data)
        manifest.append(dict(year=year, dataset=dataset, kind=kind, tab=tab, gid=gid,
                             sheet_id=sid, file=fname,
                             rows=max(len(data) - 1, 0),
                             columns=len(data[0]) if data else 0, fetched_at=ts))
    with open(os.path.join(out_dir, "_manifest.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["year", "dataset", "kind", "tab", "gid",
                                           "sheet_id", "file", "rows", "columns", "fetched_at"])
        w.writeheader(); w.writerows(manifest)
    return manifest


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("Extrayendo de Google Sheets (2025 + 2026)...")
    rows, anom = extract()
    out = os.path.normpath(os.path.join(OUT_DIR, "canonico.csv"))
    write_csv(rows, out)
    by_m = defaultdict(int)
    for r in rows: by_m[r["fecha"].strftime("%Y-%m")] += 1
    print(f"  {len(rows)} tx  | {rows[0]['fecha'].date()} -> {rows[-1]['fecha'].date()}")
    print(f"  BUY {sum(r['tipo']=='BUY' for r in rows)} / SELL {sum(r['tipo']=='SELL' for r in rows)}")
    print(f"  Anomalias: {dict(anom)}")
    print(f"  Escrito: {out}")


if __name__ == "__main__":
    main()
