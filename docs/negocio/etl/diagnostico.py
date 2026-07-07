"""
DIAGNOSTICO de rentabilidad — Kapitalya FX
===========================================
Reconstruye la ganancia real por **costo promedio movil** (weighted-average cost)
por pool de divisa, a partir del dataset canonico. Es la misma logica contable
que la casa de cambio lleva en su Sheet, pero reproducible y auditable.

    compute(csv_path) -> dict con todas las metricas del diagnostico.
    python diagnostico.py            # imprime el resumen
"""
from __future__ import annotations
import csv, os, sys
from datetime import datetime
from collections import defaultdict, Counter

DATA = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "canonico.csv"))


def _load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(dict(
                fecha=datetime.strptime(r["fecha"], "%Y-%m-%d"),
                tipo=r["tipo"], divisa=r["divisa"], denom=r.get("denom", ""),
                qty=float(r["cantidad"]), rate=float(r["tipo_cambio"]),
                total=float(r["total_bs"]), medio=r["medio_pago"],
                resp=r["responsable"], src=r["fuente"]))
    rows.sort(key=lambda r: (r["fecha"], 0 if r["tipo"] == "BUY" else 1))
    return rows


def compute(path=DATA) -> dict:
    rows = _load(path)
    inv = defaultdict(lambda: {"qty": 0.0, "cost": 0.0})
    realized = vol_buy = vol_sell = 0.0
    prof_mes = defaultdict(float); prof_div = defaultdict(float)
    prof_resp = defaultdict(float); prof_dia = defaultdict(float)
    vol_div = defaultdict(float); medio_ct = Counter()
    neg = []

    for t in rows:
        p = inv[t["divisa"]]
        if t["tipo"] == "BUY":
            vol_buy += t["total"]
            nq = p["qty"] + t["qty"]
            if nq > 0:
                p["cost"] = (p["qty"] * p["cost"] + t["qty"] * t["rate"]) / nq
            p["qty"] = nq
        else:
            vol_sell += t["total"]
            vol_div[t["divisa"]] += t["total"]
            medio_ct[t["medio"]] += 1
            basis = p["cost"] if (p["qty"] > 0 or p["cost"] > 0) else t["rate"]
            g = (t["rate"] - basis) * t["qty"]
            realized += g
            prof_mes[t["fecha"].strftime("%Y-%m")] += g
            prof_div[t["divisa"]] += g
            prof_resp[t["resp"]] += g
            prof_dia[t["fecha"].date()] += g
            p["qty"] = max(0.0, p["qty"] - t["qty"])
            if g < 0:
                neg.append(dict(fecha=t["fecha"].date(), divisa=t["divisa"],
                                qty=t["qty"], rate=t["rate"], costo=basis, perdida=g))

    n_sell = sum(t["tipo"] == "SELL" for t in rows)
    return dict(
        n_tx=len(rows),
        n_buy=sum(t["tipo"] == "BUY" for t in rows), n_sell=n_sell,
        fecha_min=rows[0]["fecha"].date(), fecha_max=rows[-1]["fecha"].date(),
        realizado=realized, vol_buy=vol_buy, vol_sell=vol_sell,
        dias=len(prof_dia), media_dia=realized / max(len(prof_dia), 1),
        margen_pct=realized / vol_sell * 100 if vol_sell else 0,
        por_mes=dict(sorted(prof_mes.items())),
        por_divisa=dict(sorted(prof_div.items(), key=lambda x: -x[1])),
        por_responsable=dict(sorted(prof_resp.items(), key=lambda x: -x[1])),
        vol_por_divisa=dict(sorted(vol_div.items(), key=lambda x: -x[1])),
        medio_pago=dict(medio_ct),
        prof_dia=dict(prof_dia),
        neg=sorted(neg, key=lambda x: x["perdida"]),
        neg_total=sum(x["perdida"] for x in neg),
    )


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    d = compute()
    print(f"GANANCIA REALIZADA: Bs {d['realizado']:,.0f}  "
          f"({d['fecha_min']} -> {d['fecha_max']}, {d['dias']} dias)")
    print(f"Margen sobre ventas: {d['margen_pct']:.2f}%  | media/dia Bs {d['media_dia']:,.0f}")
    print("Por mes:", {k: round(v) for k, v in d["por_mes"].items()})
    print("Por divisa:", {k: round(v) for k, v in d["por_divisa"].items()})
    print("Por responsable:", {k: round(v) for k, v in d["por_responsable"].items()})
    print(f"Ventas con perdida: {len(d['neg'])}/{d['n_sell']}  total Bs {d['neg_total']:,.0f}")


if __name__ == "__main__":
    main()
