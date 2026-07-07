"""
Generador RTE (Registro de Transacciones en Efectivo) — ASFI Bolivia
=====================================================================
Genera el archivo que ASFI exige a las casas de cambio, desde el dataset canónico.
Normativa de referencia: Resolución ASFI/Nº 773/2021.
Formato: CSV delimitado por '|', codificación UTF-8 con BOM.

GAP CONOCIDO: el registro operativo actual (Google Sheets) NO captura la
identificación del cliente (CI, nombres, nacionalidad, PEP). Esos campos salen
vacíos y quedan marcados — es el principal punto a cerrar para el cumplimiento.

    python asfi_rte.py 2026 6
"""
from __future__ import annotations
import os, csv, io, datetime
from collections import Counter

HERE = os.path.dirname(__file__)
NEGOCIO = os.path.normpath(os.path.join(HERE, ".."))
CANONICO = os.path.join(NEGOCIO, "data", "canonico.csv")
OUT_DIR = os.path.join(NEGOCIO, "reportes", "asfi")

NIT_ENTIDAD = "670400030"
NOMBRE_ENTIDAD = "KAPITALYA SERVICIOS INTEGRALES"
UMBRAL_USD = 10000

HEADERS = [
    "NIT_ENTIDAD", "NOMBRE_ENTIDAD", "FECHA_OPERACION", "HORA_OPERACION",
    "NUMERO_OPERACION", "TIPO_OPERACION", "MONEDA_ORIGEN", "MONEDA_DESTINO",
    "MONTO_ORIGEN", "MONTO_DESTINO", "TIPO_CAMBIO",
    "TIPO_DOCUMENTO_CLIENTE", "NUMERO_DOCUMENTO",
    "APELLIDO_PATERNO", "APELLIDO_MATERNO", "NOMBRES",
    "ES_PEP", "NACIONALIDAD", "OPERADOR_ID",
]


def _rows_mes(anio: int, mes: int):
    with open(CANONICO, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            d = datetime.datetime.strptime(r["fecha"], "%Y-%m-%d").date()
            if d.year == anio and d.month == mes:
                yield r, d


def generar_rte(anio: int, mes: int, solo_efectivo: bool = True) -> dict:
    filas_csv = []
    n_total = n_sin_cliente = n_alto_valor = 0
    div_ct = Counter()
    seq = 0
    for r, d in _rows_mes(anio, mes):
        if solo_efectivo and r.get("medio_pago", "").strip().lower() != "efectivo":
            continue
        seq += 1
        n_total += 1
        divisa = r["divisa"]
        cantidad = float(r["cantidad"])
        total_bs = float(r["total_bs"])
        tc = float(r["tipo_cambio"])
        es_compra = r["tipo"] == "BUY"
        tipo_op = "C" if es_compra else "V"
        if es_compra:
            mon_ori, mon_des, monto_ori, monto_des = divisa, "BOB", cantidad, total_bs
        else:
            mon_ori, mon_des, monto_ori, monto_des = "BOB", divisa, total_bs, cantidad
        div_ct[divisa] += 1

        n_sin_cliente += 1
        usd_aprox = cantidad if divisa.startswith("USD") else (total_bs / max(tc, 1))
        if usd_aprox >= UMBRAL_USD:
            n_alto_valor += 1

        filas_csv.append([
            NIT_ENTIDAD, NOMBRE_ENTIDAD, d.isoformat(), "00:00:00",
            f"{anio}{mes:02d}{seq:05d}", tipo_op, mon_ori, mon_des,
            f"{monto_ori:.2f}", f"{monto_des:.2f}", f"{tc:.4f}",
            "", "", "", "", "",          # cliente: vacío (gap KYC)
            "", "", (r.get("responsable") or "").upper(),
        ])

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"RTE_{anio}_{mes:02d}.csv")
    with io.open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter="|")
        w.writerow(HEADERS)
        w.writerows(filas_csv)

    return dict(
        anio=anio, mes=mes, archivo=out, n_operaciones=n_total,
        n_sin_cliente=n_sin_cliente, n_alto_valor=n_alto_valor,
        por_divisa=dict(div_ct), umbral_usd=UMBRAL_USD,
    )


def ultimo_mes_disponible() -> tuple[int, int]:
    ult = None
    with open(CANONICO, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            d = datetime.datetime.strptime(r["fecha"], "%Y-%m-%d").date()
            if ult is None or d > ult:
                ult = d
    return (ult.year, ult.month) if ult else (datetime.date.today().year, datetime.date.today().month)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 3:
        anio, mes = int(sys.argv[1]), int(sys.argv[2])
    else:
        anio, mes = ultimo_mes_disponible()
    r = generar_rte(anio, mes)
    print(f"RTE {anio}-{mes:02d}: {r['n_operaciones']} operaciones en efectivo")
    print(f"  Alto valor (≥USD {r['umbral_usd']:,}): {r['n_alto_valor']}")
    print(f"  Sin identificación de cliente (gap KYC): {r['n_sin_cliente']}")
    print(f"  Por divisa: {r['por_divisa']}")
    print(f"  Archivo: {r['archivo']}")
