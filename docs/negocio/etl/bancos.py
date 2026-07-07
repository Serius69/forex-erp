"""
Extractor de extractos bancarios — Kapitalya FX
=================================================
Extrae el resumen mensual de los extractos (documentos/markdown/Extracto-*.md):
saldo inicial, total débitos, total créditos, ITF, saldo final. Permite
reconciliar el flujo de caja real del banco contra la planilla de gastos.
Los extractos son de la cuenta personal BNB de Sergio, por donde opera el negocio.
"""
from __future__ import annotations
import os, re, csv, glob

HERE = os.path.dirname(__file__)
NEGOCIO = os.path.normpath(os.path.join(HERE, ".."))
MD_DIR = os.path.join(NEGOCIO, "documentos", "markdown")
OUT = os.path.join(NEGOCIO, "data", "bancos.csv")

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
         "noviembre": 11, "diciembre": 12}


def _num_us(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _periodo(nombre, txt):
    m = re.search(r"Extracto-([A-Za-zÁÉÍÓÚáéíóú]+)-(\d{4})", nombre)
    if m and m.group(1).lower() in MESES:
        return MESES[m.group(1).lower()], int(m.group(2))
    m = re.search(r"del \d{1,2} de (\w+),?\s*(\d{4})", txt, re.IGNORECASE)
    if m and m.group(1).lower() in MESES:
        return MESES[m.group(1).lower()], int(m.group(2))
    return None, None


def _b(m):
    return m.group(1).strip() if m else ""


def _extracto(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        txt = fh.read()
    nombre = os.path.basename(path)
    mes, anio = _periodo(nombre, txt)
    banco = "BNB" if re.search(r"Banco Nacional de Bolivia|BNB", txt, re.I) else ""
    cuenta = _b(re.search(r"N[uú]mero de cuenta:\s*([\d-]+)", txt))

    nums = []
    m = re.search(r"BOLIVIANOS(.*)", txt, re.DOTALL)
    if m:
        nums = re.findall(r"(-?[\d]{1,3}(?:,\d{3})*\.\d{2})", m.group(1))
    saldo_ini = _num_us(nums[0]) if len(nums) > 0 else None
    debitos = _num_us(nums[1]) if len(nums) > 1 else None
    creditos = _num_us(nums[2]) if len(nums) > 2 else None
    itf = _num_us(nums[3]) if len(nums) > 3 else None
    saldo_fin = _num_us(nums[4]) if len(nums) > 4 else None

    return dict(
        archivo=nombre, banco=banco, cuenta=cuenta,
        anio=anio, mes=mes,
        periodo=f"{anio}-{mes:02d}" if (anio and mes) else "",
        saldo_inicial=saldo_ini, total_debitos=debitos,
        total_creditos=creditos, itf=itf, saldo_final=saldo_fin,
        flujo_neto=(creditos - debitos) if (creditos is not None and debitos is not None) else None,
    )


def extraer_bancos() -> dict:
    filas = [_extracto(p) for p in sorted(glob.glob(os.path.join(MD_DIR, "Extracto-*.md")))]
    vistos, unicas, dupes = set(), [], 0
    for f in sorted(filas, key=lambda x: (x["periodo"], x["archivo"])):
        clave = (f["banco"], f["periodo"])
        if f["periodo"] and clave in vistos:
            dupes += 1
            continue
        vistos.add(clave)
        unicas.append(f)
    unicas.sort(key=lambda x: (x["anio"] or 0, x["mes"] or 0))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if unicas:
        cols = ["periodo", "banco", "cuenta", "saldo_inicial", "total_debitos",
                "total_creditos", "itf", "saldo_final", "flujo_neto", "archivo"]
        with open(OUT, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(unicas)

    completas = [f for f in unicas if f["saldo_final"] is not None]
    return dict(n=len(unicas), dupes=dupes, completas=len(completas),
                tot_debitos=sum(f["total_debitos"] or 0 for f in unicas),
                tot_creditos=sum(f["total_creditos"] or 0 for f in unicas),
                filas=unicas, csv=OUT)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    r = extraer_bancos()
    print(f"Extractos: {r['n']} únicos ({r['dupes']} duplicados omitidos), "
          f"{r['completas']} con resumen completo")
    print(f"Total débitos: Bs {r['tot_debitos']:,.2f} | créditos: Bs {r['tot_creditos']:,.2f}")
    for f in r["filas"]:
        si = f"{f['saldo_inicial']:,.0f}" if f['saldo_inicial'] is not None else "?"
        db = f"{f['total_debitos']:,.0f}" if f['total_debitos'] is not None else "?"
        cr = f"{f['total_creditos']:,.0f}" if f['total_creditos'] is not None else "?"
        sf = f"{f['saldo_final']:,.0f}" if f['saldo_final'] is not None else "?"
        print(f"  {f['periodo']:<9} {si:>12} {db:>12} {cr:>12} {sf:>12}")
