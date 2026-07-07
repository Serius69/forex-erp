"""
Recargas / tarjetas telefónicas — Kapitalya FX
================================================
La pestaña 'Tarjetas' del sheet 2026 tiene un cálculo de margen roto
(Total_Compra_Bs=0 -> margen=venta completa; + typos de precio). Modelo correcto
(distribuidor): la ganancia es la **comisión** sobre el valor facial vendido.
    margen = (Cant_Vendida × Corte_Bs) × Pct_Comision − Pago_Fisco_Bs
"""
from __future__ import annotations
import urllib.request, csv, io, re, time
from collections import defaultdict

SHEET_2026 = "1ZAL08c671-3jDAATgOn7MpqngwswKBh4yXIssBTP4xE"
TARJETAS_GID = "2013029646"


def _num(s):
    s = re.sub(r"[Bs\s%$]", "", str(s)).strip().strip("()").replace(".", "").replace(",", ".")
    try: return float(s)
    except ValueError: return None


def _pct(s):
    v = _num(s)
    return v / 100 if v is not None else None


def _fetch():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_2026}/export?format=csv&gid={TARJETAS_GID}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
            return list(csv.reader(io.StringIO(raw)))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("No se pudo bajar Tarjetas")


def margen_recargas() -> dict:
    rows = _fetch()
    hdr = [h.strip() for h in rows[0]]
    ci = {k: hdr.index(k) for k in
          ("Operador", "Corte_Bs", "Pct_Comision", "Pago_Fisco_Bs", "Cant_Vendida",
           "Valor_Inventario") if k in hdr}

    def g(r, k):
        i = ci.get(k)
        return r[i] if (i is not None and i < len(r)) else ""

    margen_op = defaultdict(float)
    venta_facial = 0.0
    unidades = 0.0
    inventario = 0.0
    for r in rows[1:]:
        op = g(r, "Operador").strip()
        if not op or op.upper().startswith("TOTAL"):
            continue
        corte = _num(g(r, "Corte_Bs"))
        pct = _pct(g(r, "Pct_Comision"))
        cant = _num(g(r, "Cant_Vendida")) or 0
        fisco = _num(g(r, "Pago_Fisco_Bs")) or 0
        inv = _num(g(r, "Valor_Inventario")) or 0
        inventario += inv
        if corte is None or pct is None or cant <= 0:
            continue
        facial = cant * corte
        venta_facial += facial
        unidades += cant
        margen_op[op] += facial * pct - fisco

    total = sum(margen_op.values())
    return dict(
        margen_total=total,
        venta_facial=venta_facial,
        unidades=unidades,
        inventario=inventario,
        margen_pct=(total / venta_facial * 100) if venta_facial else 0,
        por_operador=dict(sorted(margen_op.items(), key=lambda x: -x[1])),
    )


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    r = margen_recargas()
    print(f"RECARGAS (modelo comisión):")
    print(f"  Margen total:   Bs {r['margen_total']:,.0f}  ({r['margen_pct']:.1f}% sobre facial)")
    print(f"  Venta facial:   Bs {r['venta_facial']:,.0f}  ({r['unidades']:,.0f} unidades)")
    print(f"  Inventario:     Bs {r['inventario']:,.0f}")
    print(f"  Por operador:   {[(k, round(v)) for k, v in r['por_operador'].items()]}")
