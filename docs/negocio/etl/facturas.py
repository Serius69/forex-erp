"""
Extractor de facturas — Kapitalya FX
=====================================
Extrae datos de las facturas convertidas a Markdown (documentos/markdown/Factura*.md).
Estas facturas son las que Kapitalya emite a ENTEL por "Comisión por Compra de
tarjetas" -> ingreso real del negocio de recargas.

    resumen = extraer_facturas()
"""
from __future__ import annotations
import os, re, csv, glob

HERE = os.path.dirname(__file__)
NEGOCIO = os.path.normpath(os.path.join(HERE, ".."))
MD_DIR = os.path.join(NEGOCIO, "documentos", "markdown")
OUT = os.path.join(NEGOCIO, "data", "facturas.csv")


def _num_us(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _buscar(txt, patron, grupo=1):
    m = re.search(patron, txt, re.IGNORECASE | re.DOTALL)
    return m.group(grupo).strip() if m else ""


def _factura(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        txt = fh.read()
    fecha = _buscar(txt, r"Fecha:\s*\|?[^\d]*(\d{2}/\d{2}/\d{4})")
    numero = _buscar(txt, r"FACTURA N[°º][\s|]*(\d+)")
    nit_cli = _buscar(txt, r"NIT/CI/CEX:\s*\|?\s*(\d+)")
    razon = _buscar(txt, r"Nombre/Raz[oó]n Social:\s*(.+?)\s*(?:Cod|COD)")
    concepto = _buscar(txt, r"(Comisi[oó]n[^\n|]*)")
    totales = re.findall(r"(?<!SUB)TOTAL Bs\s*\|\s*([\d.,]+)", txt)
    total = _num_us(totales[-1]) if totales else None
    return dict(
        archivo=os.path.basename(path),
        fecha=fecha, numero=numero, nit_cliente=nit_cli,
        razon_social=razon, concepto=concepto,
        total_bs=total if total is not None else 0.0,
    )


def extraer_facturas() -> dict:
    filas = [_factura(p) for p in sorted(glob.glob(os.path.join(MD_DIR, "Factura*.md")))]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if filas:
        with open(OUT, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
            w.writeheader()
            w.writerows(filas)
    total = sum(f["total_bs"] for f in filas)
    return dict(n=len(filas), total_bs=total, facturas=filas, csv=OUT)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    r = extraer_facturas()
    print(f"Facturas: {r['n']}  |  Total comisiones: Bs {r['total_bs']:,.2f}")
    for f in r["facturas"]:
        print(f"  {f['fecha']:<12} N°{f['numero']:<4} Bs {f['total_bs']:>9,.2f}  "
              f"{f['razon_social'][:35]}")
