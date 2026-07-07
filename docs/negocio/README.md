# Kapitalya FX — Documentos de negocio

Análisis de rentabilidad, optimización y cumplimiento de la casa de cambio, en
Quarto, alimentado por un ETL automatizado que lee los registros operativos
directamente desde Google Sheets y los documentos ingeridos con markitdown.

## Estructura

```
negocio/
  etl/
    extract.py       # Google Sheets -> data/canonico.csv (+ raw snapshots)
    diagnostico.py   # ganancia real por costo promedio móvil
    capital.py       # serie de capital + balance (propio/acreedores) + activos
    gastos.py        # gastos clasificados + panorama financiero neto
    recargas.py      # margen de recargas/tarjetas (modelo comisión)
    facturas.py      # facturas de comisión (ENTEL) -> data/facturas.csv
    bancos.py        # extractos bancarios (resumen mensual) -> data/bancos.csv
    asfi_rte.py      # RTE ASFI (Reg. Transacciones Efectivo) -> reportes/asfi/RTE_*.csv
    ingesta_docs.py  # documentación (PDF/Office/img) -> Markdown vía markitdown
    build.py         # ORQUESTADOR: ingesta+extractores+datos+figuras+render+archivado
    watch.py         # vigilante: refresca solo al subir/modificar documentos
    programar_tarea.ps1  # registra la generación periódica como tarea de Windows
  documentos/
    inbox/           # dejar aquí docs (pdf, docx, xlsx, img…)
    markdown/        # salida convertida + _manifest.csv
  documentos-asfi/   # paquete de inscripción ASFI (.qmd -> PDF)
  data/              # canonico.csv, gastos_clasificados.csv, capital_serie.csv, etc.
  reportes/          # PDFs versionados por fecha + _historial.csv + asfi/RTE_*.csv
  figuras/           # PNG 200dpi (matplotlib)
  _variables.yml     # números vivos para los .qmd (generado)
  _quarto.yml
  resumen-ejecutivo.qmd          # informe: una página
  diagnostico-rentabilidad.qmd   # informe: rentabilidad y panorama financiero
  informe-optimizacion.qmd       # informe: optimización estratégica
  cumplimiento-asfi.qmd          # informe: requisitos ASFI, RTE, gaps
  plantillas-operativas.qmd      # formatos: caja, gastos, control, checklists
```

## Cómo refrescar TODO (un solo comando)

```bash
"E:/data/production/venv/Scripts/python.exe" etl/build.py
```

Opciones: `--no-render` (solo datos), `--quick` (solo HTML), `--no-docs` (omitir
ingesta), `--no-archive` (no versionar PDFs).

**Automático al subir documentos:**

```bash
"E:/data/production/venv/Scripts/python.exe" etl/watch.py          # HTML+PDF
```

## Versionado e histórico

Cada corrida guarda `reportes/<informe>/<informe>_<fecha>.pdf` (histórico). Los
`.qmd`/HTML se actualizan en sitio (versión canónica). Log en
`reportes/_historial.csv`.

## Generación periódica (tarea de Windows)

```powershell
powershell -ExecutionPolicy Bypass -File etl/programar_tarea.ps1 -Frecuencia Semanal -Hora 20:00
```

## Método

Ganancia por venta = (tasa de venta − **costo promedio móvil** del inventario)
× cantidad. Es la misma contabilidad que lleva la casa, pero reproducible.

## Nota importante

Todo esto vive en `docs/negocio/`, **sin commitear a git** por ahora. Cuidado con
`git clean`/"Discard all changes": borra lo no commiteado.
