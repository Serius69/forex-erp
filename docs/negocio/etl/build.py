"""
BUILD maestro — Kapitalya FX
=============================
Un solo comando refresca TODO: ingiere documentos nuevos, corre los extractores,
recalcula los datos, actualiza las variables, regenera figuras y renderiza los
reportes. Al subir documentos nuevos a docs/negocio/, se incorporan solos.

  0. INGESTA   : documentos (PDF/Office/img) -> Markdown (markitdown)
  1. DOCS-DATA : facturas + extractos bancarios + RTE ASFI -> data/*.csv
  2. EXTRACT   : Google Sheets -> data/canonico.csv (+ raw snapshots)
  3. COMPUTE   : ganancia, capital, gastos, recargas, activos
  4. VARIABLES : ../_variables.yml (numeros vivos para los .qmd)
  5. FIGURAS   : PNG 200dpi
  6. RENDER    : quarto -> HTML + PDF de los informes
  7. ARCHIVO   : PDF versionados por fecha en reportes/

    python build.py                 # todo
    python build.py --no-render      # solo refresca datos/figuras
    python build.py --no-docs        # omite ingesta de documentos
    python build.py --quick          # render solo HTML (rapido)
"""
import os, sys, subprocess, argparse, shutil, csv, datetime
sys.path.insert(0, os.path.dirname(__file__))
import extract, diagnostico, capital, gastos, recargas  # noqa: E402
import facturas, bancos, ingesta_docs, asfi_rte  # noqa: E402

HERE = os.path.dirname(__file__)
NEGOCIO = os.path.normpath(os.path.join(HERE, ".."))
DOCS_QUARTO = ["resumen-ejecutivo.qmd", "diagnostico-rentabilidad.qmd",
               "informe-optimizacion.qmd", "cumplimiento-asfi.qmd",
               "plantillas-operativas.qmd"]

MESES_ES = {"01": "ene", "02": "feb", "03": "mar", "04": "abr", "05": "may",
            "06": "jun", "07": "jul", "08": "ago", "09": "sep", "10": "oct",
            "11": "nov", "12": "dic"}
MESES_NOM = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo",
             6: "junio", 7: "julio", 8: "agosto", 9: "septiembre",
             10: "octubre", 11: "noviembre", 12: "diciembre"}


def bs(x):
    return f"{round(x):,}".replace(",", ".")


def mes_es(ym):
    y, m = ym.split("-")
    return f"{MESES_ES[m]}-{y[2:]}"


def yaml_escape(s):
    return '"' + str(s).replace('"', '\\"') + '"'


def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    data_dir = os.path.join(NEGOCIO, "data")

    # 0) Ingesta de documentos nuevos -> Markdown
    if not args.no_docs:
        try:
            r = ingesta_docs.ingesta(source=NEGOCIO)
            print(f"[0] Ingesta docs: {r['convertidos']} nuevos, "
                  f"{r['saltados']} sin cambios, {r['errores']} errores")
        except Exception as exc:  # noqa: BLE001
            print(f"[0] Ingesta docs OMITIDA ({type(exc).__name__}: {exc})")

    # 1) Extractores de documentos (facturas + bancos + RTE)
    FAC = facturas.extraer_facturas()
    BAN = bancos.extraer_bancos()
    print(f"[1] Facturas: {FAC['n']} (Bs {FAC['total_bs']:,.0f}) | "
          f"Bancos: {BAN['n']} meses (débitos Bs {BAN['tot_debitos']:,.0f})")

    # 2-3) extract + compute
    print("[2] Extract sheets..."); rows, anom = extract.extract()
    extract.write_csv(rows, os.path.join(data_dir, "canonico.csv"))
    raw_manifest = extract.write_raw_sources(os.path.join(data_dir, "raw"))
    print("[3] Compute..."); D = diagnostico.compute()
    serie_capital, CAP = capital.serie_completa()
    BG = capital.balance_general()
    ACT = capital.composicion_activos()
    capital.write_csvs(data_dir, serie=serie_capital, bg=BG)
    gastos_path, gastos_n = gastos.write_csv(os.path.join(data_dir, "gastos_clasificados.csv"))

    # RTE ASFI del último mes disponible
    ra, rm = asfi_rte.ultimo_mes_disponible()
    RTE = asfi_rte.generar_rte(ra, rm)
    print(f"[1] RTE ASFI {ra}-{rm:02d}: {RTE['n_operaciones']} ops efectivo "
          f"({RTE['n_alto_valor']} alto valor)")

    meses_margen = sorted(D["por_mes"].keys())
    P = gastos.panorama(D["realizado"], meses_margen[0], meses_margen[-1])
    RG = recargas.margen_recargas()
    print(f"      Raw snapshots: {len(raw_manifest)} pestanas")
    print(f"      Gastos clasificados: {gastos_n} -> {gastos_path}")

    overlap = [m for m in D["por_mes"] if m in CAP["por_mes"] and m <= "2025-12"]
    margen_overlap = sum(D["por_mes"][m] for m in overlap)
    capital_overlap = sum(CAP["por_mes"][m] for m in overlap)
    brecha = margen_overlap - capital_overlap

    mejor = max(D["por_mes"].items(), key=lambda x: x[1])
    peor = min(D["por_mes"].items(), key=lambda x: x[1])
    usd = D["por_divisa"].get("USD", 0)
    usd_pct = usd / D["realizado"] * 100 if D["realizado"] else 0
    resp = list(D["por_responsable"].items())
    top_neg = D["neg"][0] if D["neg"] else None

    V = {
        "periodo":       f"{D['fecha_min']} a {D['fecha_max']}",
        "n_tx":          bs(D["n_tx"]),
        "n_buy":         bs(D["n_buy"]),
        "n_sell":        bs(D["n_sell"]),
        "dias":          str(D["dias"]),
        "realizado":     bs(D["realizado"]),
        "media_dia":     bs(D["media_dia"]),
        "margen_pct":    f"{D['margen_pct']:.2f}",
        "vol_buy":       bs(D["vol_buy"]),
        "vol_sell":      bs(D["vol_sell"]),
        "mejor_mes":     mes_es(mejor[0]), "mejor_mes_bs": bs(mejor[1]),
        "peor_mes":      mes_es(peor[0]),  "peor_mes_bs":  bs(peor[1]),
        "usd_bs":        bs(usd), "usd_pct": f"{usd_pct:.0f}",
        "resp1":         resp[0][0], "resp1_bs": bs(resp[0][1]),
        "resp1_pct":     f"{resp[0][1]/D['realizado']*100:.0f}",
        "resp2":         resp[1][0] if len(resp) > 1 else "-",
        "resp2_bs":      bs(resp[1][1]) if len(resp) > 1 else "0",
        "resp2_pct":     f"{resp[1][1]/D['realizado']*100:.0f}" if len(resp) > 1 else "0",
        "n_neg":         str(len(D["neg"])),
        "neg_total":     bs(abs(D["neg_total"])),
        "neg_pct":       f"{len(D['neg'])/D['n_sell']*100:.1f}",
        "top_neg_fecha": str(top_neg["fecha"]) if top_neg else "-",
        "top_neg_qty":   bs(top_neg["qty"]) if top_neg else "0",
        "top_neg_rate":  f"{top_neg['rate']:.2f}" if top_neg else "0",
        "top_neg_bs":    bs(abs(top_neg["perdida"])) if top_neg else "0",
        "anomalias":     str(sum(anom.values())),
        "fecha_max":     str(D["fecha_max"]),
        "cap_inicio":      bs(CAP["balance_inicio"]),
        "cap_fin":         bs(CAP["balance_fin"]),
        "cap_crecimiento": bs(CAP["crecimiento"]),
        "cap_desde":       str(CAP["fecha_inicio"]),
        "cap_hasta":       str(CAP["fecha_fin"]),
        "cap_mejor_mes":   mes_es(CAP["mejor_mes"]),
        "cap_mejor_mes_bs": bs(CAP["mejor_mes_bs"]),
        "bg_propio":     bs(BG["capital_propio"]) if BG["capital_propio"] is not None else "0",
        "bg_acreedores": bs(BG["acreedores"]) if BG["acreedores"] is not None else "0",
        "bg_total":      bs(BG["total_general"]) if BG["total_general"] is not None else "0",
        "bg_propio_pct": f"{BG['propio_pct']:.0f}" if BG.get("propio_pct") else "0",
        "bg_acreed_pct": f"{(BG['acreedores']/BG['total_general']*100):.0f}" if BG.get("total_general") else "0",
        "rec_margen":   bs(margen_overlap),
        "rec_capital":  bs(capital_overlap),
        "rec_brecha":   bs(brecha),
        "pn_margen":       bs(P["margen"]),
        "pn_gasto_op":     bs(P["gasto_op"]),
        "pn_resultado_op": bs(P["resultado_op"]),
        "pn_retiros":      bs(P["retiro_neto"]),
        "pn_var_capital":  bs(P["var_capital"]),
        "pn_top_gasto":    P["top"][0][0] if P["top"] else "-",
        "pn_top_gasto_bs": bs(P["top"][0][1]) if P["top"] else "0",
        "pn_veh_manual":   bs(P["veh_manual"]),
        "est_roe":        f"{(P['resultado_op']/BG['capital_propio']*100):.0f}" if BG.get("capital_propio") else "0",
        "est_roe_total":  f"{(P['resultado_op']/BG['total_general']*100):.0f}" if BG.get("total_general") else "0",
        "est_gasto_ratio": f"{(P['gasto_op']/P['margen']*100):.0f}" if P.get("margen") else "0",
        "rg_margen":   bs(RG["margen_total"]),
        "rg_venta":    bs(RG["venta_facial"]),
        "rg_pct":      f"{RG['margen_pct']:.1f}",
        "rg_unidades": bs(RG["unidades"]),
        "rg_inventario": bs(RG["inventario"]),
        "rg_top_op":   list(RG["por_operador"].keys())[0] if RG["por_operador"] else "-",
        "rg_top_op_bs": bs(list(RG["por_operador"].values())[0]) if RG["por_operador"] else "0",
        "act_divisas":    bs(ACT.get("divisas", 0)),
        "act_bancos":     bs(ACT.get("bancos", 0)),
        "act_inventario": bs(ACT.get("inventario", 0)),
        "act_usdc":       bs(ACT.get("usdc", 0)),
        "act_total":      bs(ACT.get("total", 0)),
        "act_divisas_pct": f"{(ACT.get('divisas',0)/ACT.get('total',1)*100):.0f}" if ACT.get("total") else "0",
        "act_bancos_pct":  f"{(ACT.get('bancos',0)/ACT.get('total',1)*100):.0f}" if ACT.get("total") else "0",
        "fac_n":       str(FAC["n"]),
        "fac_total":   bs(FAC["total_bs"]),
        "ban_meses":    str(BAN["n"]),
        "ban_debitos":  bs(BAN["tot_debitos"]),
        "ban_creditos": bs(BAN["tot_creditos"]),
        "ban_desde":    BAN["filas"][0]["periodo"] if BAN["filas"] else "-",
        "ban_hasta":    BAN["filas"][-1]["periodo"] if BAN["filas"] else "-",
        "docs_total":  str(_contar_docs()),
        "asfi_rte_mes":   f"{MESES_NOM[RTE['mes']]} {RTE['anio']}",
        "asfi_rte_ops":   bs(RTE["n_operaciones"]),
        "asfi_rte_alto":  str(RTE["n_alto_valor"]),
        "asfi_rte_gap":   bs(RTE["n_sin_cliente"]),
        "asfi_umbral":    bs(RTE["umbral_usd"]),
        "asfi_entidad":   asfi_rte.NOMBRE_ENTIDAD,
        "asfi_nit":       asfi_rte.NIT_ENTIDAD,
    }
    path = os.path.join(NEGOCIO, "_variables.yml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Generado por etl/build.py — NO editar a mano.\n")
        fh.write("fx:\n")
        for k, v in V.items():
            fh.write(f"  {k}: {yaml_escape(v)}\n")
    print(f"[4] Variables -> {os.path.basename(path)}")

    print("[5] Figuras...")
    subprocess.run([sys.executable, os.path.join(NEGOCIO, "figuras", "gen_figuras.py")],
                   check=True)

    if not args.no_render:
        _render(quick=args.quick)
        if not args.no_archive and not args.quick:
            n = _archivar()
            print(f"[7] Archivados {n} PDF versionados en reportes/")
    else:
        print("[6] Render OMITIDO (--no-render)")

    print("\n✅ Listo. Reportes actualizados en docs/negocio/")


def _render(quick: bool = False):
    quarto = shutil.which("quarto")
    if not quarto:
        print("[6] Render OMITIDO — 'quarto' no está en el PATH")
        return
    formatos = ["html"] if quick else ["html", "pdf"]
    for fmt in formatos:
        print(f"[6] Render {fmt.upper()}...")
        for doc in DOCS_QUARTO:
            res = subprocess.run([quarto, "render", doc, "--to", fmt],
                                 cwd=NEGOCIO, capture_output=True, text=True)
            estado = "OK" if res.returncode == 0 else "ERROR"
            if res.returncode != 0:
                print(f"    !! {doc} [{fmt}] {estado}: {res.stderr.strip()[-200:]}")
            else:
                print(f"    OK {doc} [{fmt}]")


def _archivar() -> int:
    """Guarda copia versionada por fecha de cada PDF: reportes/<informe>/<informe>_<fecha>.pdf."""
    hoy = datetime.date.today().isoformat()
    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    rep = os.path.join(NEGOCIO, "reportes")
    hist = os.path.join(rep, "_historial.csv")
    filas = []
    for qmd in DOCS_QUARTO:
        base = qmd[:-4]
        pdf = os.path.join(NEGOCIO, base + ".pdf")
        if not os.path.exists(pdf):
            continue
        dest_dir = os.path.join(rep, base)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"{base}_{hoy}.pdf")
        shutil.copy2(pdf, dest)
        filas.append([ahora, base, os.path.relpath(dest, NEGOCIO),
                      round(os.path.getsize(pdf) / 1024, 1)])
    if filas:
        nuevo = not os.path.exists(hist)
        os.makedirs(rep, exist_ok=True)
        with open(hist, "a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            if nuevo:
                w.writerow(["fecha_hora", "informe", "archivo", "tamano_kb"])
            w.writerows(filas)
    return len(filas)


def _contar_docs() -> int:
    man = os.path.join(NEGOCIO, "documentos", "markdown", "_manifest.csv")
    if not os.path.exists(man):
        return 0
    with open(man, encoding="utf-8") as fh:
        return max(sum(1 for _ in fh) - 1, 0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build maestro Kapitalya FX")
    ap.add_argument("--no-docs", action="store_true", help="omitir ingesta de documentos")
    ap.add_argument("--no-render", action="store_true", help="no renderizar los informes")
    ap.add_argument("--quick", action="store_true", help="render solo HTML (rápido)")
    ap.add_argument("--no-archive", action="store_true", help="no guardar PDF versionados")
    main(ap.parse_args())
