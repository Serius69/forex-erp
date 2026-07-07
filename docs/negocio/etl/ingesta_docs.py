"""
Ingesta de documentación — Kapitalya FX
=========================================
Convierte documentos (PDF, Word, Excel, PPT, HTML, imágenes…) a Markdown con
**markitdown** (Microsoft), para extraer su información y alimentar el análisis.

    documentos/inbox/*  (o docs/negocio con --source)  →  documentos/markdown/*.md

    python ingesta_docs.py                 # escanea documentos/inbox
    python ingesta_docs.py --source negocio  # escanea docs/negocio/ (excluye pipeline)
    python ingesta_docs.py --force

Requiere:  pip install "markitdown[pdf,docx,xlsx,pptx]"
"""
from __future__ import annotations
import os, sys, csv, argparse, datetime, hashlib

HERE = os.path.dirname(__file__)
NEGOCIO = os.path.normpath(os.path.join(HERE, ".."))
DOCS = os.path.join(NEGOCIO, "documentos")
INBOX = os.path.join(DOCS, "inbox")
OUT = os.path.join(DOCS, "markdown")
MANIFEST = os.path.join(OUT, "_manifest.csv")

SOPORTADAS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".csv",
    ".html", ".htm", ".xml", ".json", ".txt", ".rtf", ".epub", ".msg",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
}

EXCLUDE_DIRS = {
    ".git", ".quarto", "__pycache__", "node_modules",
    "etl", "figuras", "data", "documentos",
    "reportes", "documentos-asfi",   # generados por el pipeline — no re-ingerir
}
EXCLUDE_FILES = {
    "README.md", "_variables.yml", "_quarto.yml",
    "diagnostico-rentabilidad.pdf", "diagnostico-rentabilidad.html",
    "informe-optimizacion.pdf", "informe-optimizacion.html",
    "plantillas-operativas.pdf", "plantillas-operativas.html",
}


def _slug(rel: str) -> str:
    base = rel.replace("\\", "/").rsplit(".", 1)[0]
    base = base.replace("/", "__").replace(" ", "_")
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in base)


def _sha8(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def _contar_chars(md_path: str) -> int:
    try:
        with open(md_path, encoding="utf-8") as fh:
            return len(fh.read())
    except OSError:
        return 0


def ingesta(force: bool = False, source: str = INBOX):
    from markitdown import MarkItDown
    os.makedirs(OUT, exist_ok=True)
    md = MarkItDown()

    fuentes = []
    for root, dirs, files in os.walk(source):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.endswith("_files")]
        for f in files:
            if f in EXCLUDE_FILES:
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext in SOPORTADAS:
                fuentes.append(os.path.join(root, f))
    fuentes.sort()

    manifest = []
    convertidos = saltados = errores = 0
    for src in fuentes:
        rel = os.path.relpath(src, source)
        out_md = os.path.join(OUT, _slug(rel) + ".md")
        src_mtime = os.path.getmtime(src)

        if (not force and os.path.exists(out_md)
                and os.path.getmtime(out_md) >= src_mtime):
            saltados += 1
            estado, chars = "sin cambios", _contar_chars(out_md)
        else:
            try:
                res = md.convert(src)
                texto = res.text_content or ""
                titulo = (getattr(res, "title", None) or os.path.basename(rel))
                with open(out_md, "w", encoding="utf-8") as fh:
                    fh.write(f"---\nfuente: {rel}\n")
                    fh.write(f"titulo: {titulo}\n")
                    fh.write(f"convertido: {datetime.datetime.now().isoformat(timespec='seconds')}\n")
                    fh.write(f"sha8_fuente: {_sha8(src)}\n---\n\n")
                    fh.write(texto)
                convertidos += 1
                estado, chars = "convertido", len(texto)
            except Exception as exc:  # noqa: BLE001
                errores += 1
                estado, chars = f"ERROR: {type(exc).__name__}: {str(exc)[:80]}", 0

        manifest.append(dict(
            fuente=rel,
            tipo=os.path.splitext(src)[1].lower().lstrip("."),
            tamano_kb=round(os.path.getsize(src) / 1024, 1),
            chars_extraidos=chars,
            markdown=os.path.relpath(out_md, DOCS) if not estado.startswith("ERROR") else "",
            estado=estado,
        ))

    with open(MANIFEST, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "fuente", "tipo", "tamano_kb", "chars_extraidos", "markdown", "estado"])
        w.writeheader()
        w.writerows(manifest)

    return dict(total=len(fuentes), convertidos=convertidos,
                saltados=saltados, errores=errores, manifest=manifest)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Ingesta de documentos → Markdown")
    ap.add_argument("--force", action="store_true", help="reconvertir todo")
    ap.add_argument("--source", default=None,
                    help="carpeta a escanear (default: inbox; usar 'negocio' para docs/negocio/)")
    args = ap.parse_args()

    source = INBOX
    if args.source in ("negocio", ".."):
        source = NEGOCIO
    elif args.source:
        source = os.path.abspath(args.source)

    os.makedirs(source, exist_ok=True)
    r = ingesta(force=args.force, source=source)
    print(f"Fuente: {source}")
    print(f"Documentos: {r['total']}  |  convertidos: {r['convertidos']}  "
          f"saltados: {r['saltados']}  errores: {r['errores']}")
    if r["total"] == 0:
        print(f"\nColoca documentos en:\n  {INBOX}\n(pdf, docx, xlsx, pptx, imágenes, etc.) y vuelve a correr.")
    for m in r["manifest"]:
        marca = "OK " if m["estado"] in ("convertido", "sin cambios") else "!! "
        print(f"  {marca}{m['fuente']}  ({m['chars_extraidos']} chars)  {m['estado']}")


if __name__ == "__main__":
    main()
