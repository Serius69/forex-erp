"""
Genera las figuras PNG (200dpi) del diagnostico. Patron Kapitalya: matplotlib
pre-renderizado (no mermaid) para que impriman bien en PDF via Quarto.
    python gen_figuras.py
"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))
import diagnostico  # noqa: E402
import capital as capital_mod  # noqa: E402
import gastos as gastos_mod  # noqa: E402

HERE = os.path.dirname(__file__)
D = diagnostico.compute()

AZUL, VERDE, AMBAR, ROJO, GRIS = "#1e3a5f", "#16a34a", "#d97706", "#dc2626", "#64748b"
plt.rcParams.update({"font.size": 11, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 200})


def _bs(x, _=None):
    return f"{x:,.0f}".replace(",", ".")


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, name), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ", name)


def fig_mensual():
    meses = list(D["por_mes"].keys())
    vals = list(D["por_mes"].values())
    fig, ax = plt.subplots(figsize=(8, 3.6))
    bars = ax.bar(meses, vals, color=[VERDE if v >= 0 else ROJO for v in vals])
    ax.axhline(0, color=GRIS, lw=0.8)
    ax.yaxis.set_major_formatter(FuncFormatter(_bs))
    ax.set_ylabel("Ganancia (Bs)")
    ax.set_title("Ganancia realizada por mes", fontweight="bold", color=AZUL)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    mx = max(vals)
    for b, v in zip(bars, vals):
        if v == mx:
            ax.text(b.get_x() + b.get_width()/2, v, f" {_bs(v)}", ha="center",
                    va="bottom", fontsize=8, fontweight="bold", color=AZUL)
    save(fig, "ganancia_mensual.png")


def fig_acumulada():
    dias = sorted(D["prof_dia"].keys())
    acc, s = [], 0.0
    for d in dias:
        s += D["prof_dia"][d]; acc.append(s)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.plot(dias, acc, color=AZUL, lw=1.8)
    ax.fill_between(dias, acc, color=AZUL, alpha=0.08)
    ax.yaxis.set_major_formatter(FuncFormatter(_bs))
    ax.set_ylabel("Ganancia acumulada (Bs)")
    ax.set_title("Curva de ganancia acumulada", fontweight="bold", color=AZUL)
    ax.annotate(f"Bs {_bs(acc[-1])}", xy=(dias[-1], acc[-1]),
                xytext=(-8, 4), textcoords="offset points", ha="right",
                fontweight="bold", color=VERDE)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    save(fig, "ganancia_acumulada.png")


def fig_divisa():
    items = list(D["por_divisa"].items())
    labels = [k for k, _ in items][::-1]
    vals = [v for _, v in items][::-1]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.barh(labels, vals, color=AZUL)
    ax.xaxis.set_major_formatter(FuncFormatter(_bs))
    tot = sum(vals)
    for i, v in enumerate(vals):
        ax.text(v, i, f" {_bs(v)} ({v/tot*100:.0f}%)", va="center", fontsize=8.5)
    ax.set_title("Ganancia por divisa", fontweight="bold", color=AZUL)
    ax.margins(x=0.18)
    save(fig, "por_divisa.png")


def fig_responsable():
    items = list(D["por_responsable"].items())
    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(5, 3))
    bars = ax.bar(labels, vals, color=[AZUL, AMBAR])
    ax.yaxis.set_major_formatter(FuncFormatter(_bs))
    tot = sum(vals)
    for b, v in zip(bars, vals):
        ax.text(b.get_x()+b.get_width()/2, v, f"{_bs(v)}\n{v/tot*100:.0f}%",
                ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_title("Ganancia por responsable", fontweight="bold", color=AZUL)
    ax.margins(y=0.2)
    save(fig, "por_responsable.png")


def fig_capital():
    serie, res = capital_mod.serie_completa()
    fechas = [d for d, _, _ in serie]
    bals = [b for _, b, _ in serie]
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.plot(fechas, bals, color=AZUL, lw=1.8, marker="o", ms=2.5)
    ax.fill_between(fechas, bals, color=AZUL, alpha=0.07)
    ax.yaxis.set_major_formatter(FuncFormatter(_bs))
    ax.set_ylabel("Capital propio (Bs)")
    ax.set_title("Evolución del capital propio — feb 2025 a hoy",
                 fontweight="bold", color=AZUL)
    import datetime as _dt
    corte = _dt.datetime(2025, 6, 1)
    ax.axvline(corte, color=AMBAR, ls="--", lw=1.2)
    ax.text(corte, max(bals), " inicio registro\n transaccional", color=AMBAR,
            fontsize=7.5, va="top")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    save(fig, "evolucion_capital.png")


def fig_cascada():
    meses = sorted(D["por_mes"].keys())
    P = gastos_mod.panorama(D["realizado"], meses[0], meses[-1])
    pasos = [
        ("Margen\ntrading", P["margen"], VERDE, False),
        ("Gastos\noperativos", -P["gasto_op"], ROJO, False),
        ("Resultado\noperativo", P["resultado_op"], AZUL, True),
        ("Retiros\nnetos", -P["retiro_neto"], AMBAR, False),
        ("Variación\nde capital", P["var_capital"], AZUL, True),
    ]
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    run = 0.0
    for i, (label, val, color, total) in enumerate(pasos):
        if total:
            ax.bar(i, val, color=color, alpha=0.95, edgecolor="black", lw=0.5)
            top = val
        else:
            ax.bar(i, val, bottom=run, color=color, alpha=0.9)
            top = run + val
            run = top
        ax.text(i, max(top, run) + max(P["margen"], 1) * 0.02, _bs(abs(val)),
                ha="center", va="bottom", fontsize=8, fontweight="bold")
    ax.axhline(0, color=GRIS, lw=0.8)
    ax.set_xticks(range(len(pasos)))
    ax.set_xticklabels([p[0] for p in pasos], fontsize=9)
    ax.yaxis.set_major_formatter(FuncFormatter(_bs))
    ax.set_title("Del margen de trading a la variación de capital",
                 fontweight="bold", color=AZUL)
    ax.margins(y=0.18)
    save(fig, "cascada_neto.png")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Generando figuras...")
    fig_mensual(); fig_acumulada(); fig_divisa(); fig_responsable()
    fig_capital(); fig_cascada()
    print("Listo.")
