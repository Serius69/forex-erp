# Paquete de inscripción ASFI — Casa de Cambio Unipersonal

**KAPITALYA SERVICIOS INTEGRALES** · Empresa Unipersonal
Propietario: **Sergio Denis Troche Mayta** · C.I. 6754281 LP
NIT / Matrícula de Comercio: **670400030**
Domicilio: Zona Villa Fátima, Av. Las Delicias N.º 207-C, La Paz
Base normativa: **Recopilación de Normas ASFI — Libro 1°, Título II, Capítulo V**
(Reglamento para Casas de Cambio) · Ley 393 de Servicios Financieros · normativa UIF.

> ⚠️ Estos son **borradores de trabajo** pre-llenados con los datos reales de la
> empresa. Antes de presentarlos a ASFI deben ser **revisados por un asesor legal**.

## Estado de requisitos

| # | Requisito | Estado | Documento |
|:-:|:--|:--|:--|
| 1 | Matrícula de Comercio (SEPREC) | ✅ Se tiene | — |
| 2 | NIT (SIN) | ✅ Se tiene | — |
| 3 | C.I. del propietario | ✅ Se tiene (6754281) | — |
| 4 | Contrato de arrendamiento del local | ✅ Se tiene | `CONTRATO DE ARRENDAMIENTO` |
| 5 | Carta de solicitud a ASFI | 🟡 **En Quarto** | `carta-solicitud-asfi.qmd` |
| 6 | Programa General de Funcionamiento | 🟡 **En Quarto** | `programa-general-funcionamiento.qmd` |
| 7 | **Manual PLD/FT** | 🟡 **Generado aquí** | `manual-pld-ft.qmd` |
| 8 | **Designación de Oficial de Cumplimiento** (Sergio) | 🟡 **Generado aquí** | `designacion-oficial-cumplimiento.qmd` |
| 9 | **Declaración jurada de origen del capital** | 🟡 **Generado aquí** | `declaracion-jurada-capital.qmd` |
| 10 | **Declaración jurada de cumplimiento / no impedimentos** | 🟡 **Generado aquí** | `declaracion-jurada-cumplimiento.qmd` |
| 11 | Balance de apertura / estados financieros | 🟢 Generables | ver informes de rentabilidad |
| 12 | Croquis de ubicación + fotografías del local | 🔴 Pendiente | (levantar) |
| 13 | Certificado REJAP / antecedentes penales del propietario | 🔴 Pendiente | (trámite personal) |
| 14 | Boleta de garantía (si aplica) | 🔴 Por confirmar | (con asesor) |

Leyenda: ✅ listo · 🟡 borrador en Quarto (revisar/firmar) · 🟢 generable del sistema ·
🔴 pendiente de gestión.

## Cómo generar los PDF para presentar

La fuente editable es el `.qmd` (Markdown/LaTeX) — se edita ahí y se renderiza a PDF.

```bash
cd documentos-asfi
quarto render carta-solicitud-asfi.qmd            # -> PDF
quarto render programa-general-funcionamiento.qmd
quarto render manual-pld-ft.qmd
quarto render designacion-oficial-cumplimiento.qmd
quarto render declaracion-jurada-capital.qmd
quarto render declaracion-jurada-cumplimiento.qmd
```

## Datos ya completados

- Fecha de presentación: **1 de julio de 2026** (ajustar a la fecha real de entrega).
- Origen del capital: **Bs 200.000 ahorros propios + Bs 50.000 actividad comercial previa = Bs 250.000**.
- Oficial de Cumplimiento: el propietario **Sergio Denis Troche Mayta**.

## Pendiente de gestión externa

- Número de resolución/registro **UIF** (cuando se obtenga).
- **Croquis + fotografías** del local.
- Certificado **REJAP / antecedentes** del propietario.
- **Revisión legal** del paquete.
