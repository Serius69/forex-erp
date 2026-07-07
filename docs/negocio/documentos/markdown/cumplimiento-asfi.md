---
fuente: cumplimiento-asfi.html
titulo: Cumplimiento ASFI — Kapitalya FX
convertido: 2026-07-01T22:39:20
sha8_fuente: 96032c10
---

## Contenido

* [1 Marco normativo](#marco-normativo)
* [2 Requisitos de inscripción (una sola vez)](#requisitos-de-inscripción-una-sola-vez)
* [3 Obligaciones de reporte periódico](#obligaciones-de-reporte-periódico)
  + [3.1 RTE — Registro de Transacciones en Efectivo](#rte-registro-de-transacciones-en-efectivo)
  + [3.2 ROS — Reporte de Operaciones Sospechosas](#ros-reporte-de-operaciones-sospechosas)
  + [3.3 KYC — Conozca a su Cliente](#kyc-conozca-a-su-cliente)
* [4 Gap crítico — identificación de cliente](#gap-crítico-identificación-de-cliente)
* [5 Cómo se genera (en código)](#cómo-se-genera-en-código)
* [6 Checklist de próximos pasos](#checklist-de-próximos-pasos)

## Otros formatos

* [PDF](cumplimiento-asfi.pdf)

# Cumplimiento ASFI — Kapitalya FX

Qué exige ASFI a una casa de cambio, qué se genera en código y qué falta

Autor/a

Kapitalya FX

Fecha de publicación

1 de julio de 2026

Resumen

Guía de cumplimiento ante la Autoridad de Supervisión del Sistema Financiero (ASFI) para operar como casa de cambio en Bolivia: requisitos de inscripción, obligaciones de reporte periódico (RTE, ROS, KYC/LD-FT), estado actual y el código que ya genera los reportes exigidos. Referencias: D.S. 29681, Ley 393 de Servicios Financieros, Resolución ASFI/Nº 773/2021, normativa UIF.

Importante

Este documento es una **guía operativa de preparación**, no asesoría legal. Los estados marcados “por confirmar” deben validarse con el asesor legal y el Oficial de Cumplimiento. La normativa ASFI/UIF se actualiza; verificar la versión vigente.

# 1 Marco normativo

* **Ley N° 393 de Servicios Financieros** — marco general y supervisión ASFI.
* **D.S. 29681** — requisitos para entidades de cambio.
* **Resolución ASFI/Nº 773/2021** — operaciones de cambio y el **RTE**.
* **Normativa UIF** — prevención de LGI/FT: KYC, ROS, Oficial de Cumplimiento.

**Entidad:** KAPITALYA SERVICIOS INTEGRALES · **NIT:** 670400030.

# 2 Requisitos de inscripción (una sola vez)

| # | Requisito | Estado |
| --- | --- | --- |
| 1 | Constitución legal (SEPREC/FUNDEMPRESA, escritura pública) | ☑ se tiene |
| 2 | NIT y certificado de cumplimiento tributario (SIN) | ☑ se tiene |
| 3 | Declaración de capital social y procedencia | ☑ generada |
| 4 | Infraestructura y sistemas de información | ☑ sistema operativo (forex-erp) |
| 5 | **Manual de políticas LGI/FT** | ☑ borrador generado |
| 6 | **Designación de Oficial de Cumplimiento** | ☑ borrador generado |
| 7 | Registro ante la UIF | ☐ por confirmar |
| 8 | Estados financieros (respaldo de solvencia) | ☑ generables (ver informes) |
| 9 | Declaración jurada de cumplimiento normativo | ☑ generada |

*(Paquete completo en `documentos-asfi/`.)*

# 3 Obligaciones de reporte periódico

## 3.1 RTE — Registro de Transacciones en Efectivo

El reporte central. **Ya está automatizado en código** — se genera el archivo en el formato ASFI (CSV delimitado por `|`, UTF-8 con BOM).

Del último mes disponible (**julio 2026**):

| Métrica | Valor |
| --- | --- |
| Operaciones en efectivo | 4 |
| Operaciones de alto valor (≥ USD 10.000) | 0 |

El archivo queda en `reportes/asfi/RTE_<año>_<mes>.csv`. Se regenera con cada `build.py`, o con `python etl/asfi_rte.py 2026 6`.

## 3.2 ROS — Reporte de Operaciones Sospechosas

Ante señales de alerta, el Oficial de Cumplimiento reporta a la UIF. Requiere el registro de cliente por operación (ver gap abajo).

## 3.3 KYC — Conozca a su Cliente

Identificación del cliente en operaciones reportables (CI/NIT, nombres, nacionalidad, PEP).

# 4 Gap crítico — identificación de cliente

AdvertenciaEl registro actual no captura al cliente

El RTE de julio 2026 salió con **4 operaciones sin identificación de cliente**, porque el registro operativo actual (planilla) no captura CI, nombres, nacionalidad ni PEP. **Sin esos datos el RTE está incompleto para ASFI** y no se pueden generar ROS.

**La buena noticia:** el sistema **forex-erp ya tiene los campos** (`carnet_identidad`, `customer`, categoría REPORTABLE). El cierre del gap es **operativo**, no de desarrollo:

1. Capturar CI + nombre del cliente en toda operación reportable.
2. Migrar el registro de la planilla a forex-erp.
3. Marcar operaciones ≥ USD 10.000 para revisión reforzada.

# 5 Cómo se genera (en código)

| Componente | Dónde | Qué hace |
| --- | --- | --- |
| RTE standalone | `etl/asfi_rte.py` | CSV ASFI desde el dataset canónico |
| RTE en producción | `forex-erp/backend/reports/asfi_*.py` | RTE desde la BD, con cliente |
| Estados financieros | informes de rentabilidad y optimización | respaldo de solvencia |

# 6 Checklist de próximos pasos

1. [ ] Confirmar/actualizar el **registro ante la UIF**.
2. [ ] Cerrar el **gap KYC**: capturar cliente por operación (forex-erp).
3. [ ] Definir el **umbral de operación reportable** vigente con el asesor.
4. [ ] Establecer el **calendario de entrega del RTE** (mensual) a ASFI.
5. [ ] Validar todo el paquete de inscripción con el asesor legal.

---

*Kapitalya FX · Guía de cumplimiento ASFI · La Paz, Bolivia · 2026-07-01*