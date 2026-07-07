"""
Vigilante de documentos — Kapitalya FX
========================================
Observa docs/negocio/ y, cuando detecta documentos nuevos o modificados (tras
un momento de calma), corre el build maestro para incorporarlos a los reportes.

    python watch.py            # vigila y refresca (render completo HTML+PDF)
    python watch.py --quick    # refresca solo HTML
    python watch.py --once      # un escaneo y sale (para probar)

Sin dependencias externas (polling de mtimes). Cerrar con Ctrl+C.
"""
from __future__ import annotations
import os, sys, time, subprocess, argparse

HERE = os.path.dirname(__file__)
NEGOCIO = os.path.normpath(os.path.join(HERE, ".."))
BUILD = os.path.join(HERE, "build.py")

IGNORAR = {".git", ".quarto", "__pycache__", "node_modules",
           "etl", "figuras", "data"}
DOC_EXT = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".csv",
           ".png", ".jpg", ".jpeg", ".html", ".txt", ".msg", ".rtf", ".epub"}
INTERVALO = 5
CALMA = 8


def firma() -> dict:
    out = {}
    for root, dirs, files in os.walk(NEGOCIO):
        dirs[:] = [d for d in dirs if d not in IGNORAR and not d.endswith("_files")
                   and d != "markdown"]
        for f in files:
            if os.path.splitext(f)[1].lower() in DOC_EXT:
                p = os.path.join(root, f)
                try:
                    out[p] = os.path.getmtime(p)
                except OSError:
                    pass
    return out


def correr_build(quick: bool):
    cmd = [sys.executable, BUILD]
    if quick:
        cmd.append("--quick")
    print(f"\n🔄 Cambios detectados — refrescando reportes...\n", flush=True)
    subprocess.run(cmd, cwd=HERE)
    print("\n👀 Vigilando docs/negocio/ … (Ctrl+C para salir)", flush=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Vigilante de documentos")
    ap.add_argument("--quick", action="store_true", help="render solo HTML en cada cambio")
    ap.add_argument("--once", action="store_true", help="un escaneo y salir (prueba)")
    args = ap.parse_args()

    actual = firma()
    print(f"👀 Vigilando docs/negocio/ — {len(actual)} documentos rastreados.")
    if args.once:
        print("Modo --once: sin cambios pendientes, saliendo.")
        return

    print("   (Al subir/modificar documentos, se refrescan los reportes solos.)")
    print("   Ctrl+C para salir.\n")
    ultimo_cambio = None
    while True:
        time.sleep(INTERVALO)
        nueva = firma()
        if nueva != actual:
            nuevos = set(nueva) - set(actual)
            modif = {p for p in nueva if p in actual and nueva[p] != actual[p]}
            for p in list(nuevos)[:8]:
                print(f"  + nuevo: {os.path.relpath(p, NEGOCIO)}")
            for p in list(modif)[:8]:
                print(f"  ~ modif: {os.path.relpath(p, NEGOCIO)}")
            actual = nueva
            ultimo_cambio = time.time()
        elif ultimo_cambio and (time.time() - ultimo_cambio) >= CALMA:
            ultimo_cambio = None
            correr_build(args.quick)
            actual = firma()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Vigilante detenido.")
