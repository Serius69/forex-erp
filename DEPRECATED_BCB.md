# Auditoría de eliminación: fuentes BCB

**Fecha:** 2026-05-01  
**Motivo:** El negocio opera únicamente con tasa paralela boliviana. BCB dejó de ser fuente relevante.  
**Nueva fuente única:** `https://dolarbluebolivia.click/`

---

## Qué se eliminó / desactivó

### Backend — Fetchers

| Archivo | Estado | Acción |
|---|---|---|
| `backend/rates/fetchers/bcb_fetcher.py` | Conservado (datos históricos en DB) | Ya no se importa ni ejecuta |
| `backend/rates/fetchers/reference_fetcher.py` | Conservado (datos históricos en DB) | Ya no se importa ni ejecuta |
| `BCBOfficialFetcher` | Desactivado | Removido de `aggregator.collect_all()` |
| `BCBReferenceFetcher` | Desactivado | Removido de `aggregator.collect_all()` |
| `BCBJsonAPIFetcher` | Desactivado | Removido de `aggregator.collect_all()` y `collect_by_market()` |
| `BCPBoliviaFetcher` | Desactivado | Removido de `aggregator.collect_all()` y `collect_by_market()` |
| `BCPJsonAPIFetcher` | Desactivado | Removido de `aggregator.collect_all()` y `collect_by_market()` |

### Backend — Tareas Celery

| Tarea | Estado | Acción |
|---|---|---|
| `rates.update_bcb_rates` | Desactivada | Convertida a stub que retorna `deprecated_bcb_removed` |
| `rates.fetch_reference_rates` | Desactivada | Convertida a stub que retorna `deprecated_bcb_removed` |
| `update-bcb-rates` (Beat schedule) | Eliminada | Reemplazada por `fetch-parallel-rate` cada 15 min |

### Backend — Aggregator

| Cambio | Detalle |
|---|---|
| `MARKET_PRIORITY['official']` | Bajado a `0` (solo datos históricos) |
| `MARKET_PRIORITY['bcb']` | Bajado a `1` (solo datos históricos) |
| `MARKET_PRIORITY['paralelo_digital']` | Subido a `5` (fuente principal) |
| `collect_all()` | BCB y BCP fetchers eliminados |
| `collect_by_market('official')` | Redirigido a OpenExchangeRates/ExchangeRateAPI |
| `collect_by_market('bcb')` | Redirigido a OpenExchangeRates/ExchangeRateAPI |

### Backend — Predictions

| Archivo | Cambio |
|---|---|
| `predictions/tasks.py:evaluate_predictions` | `actual.official_rate` → `(actual.buy_rate + actual.sell_rate) / 2` |
| `predictions/tasks.py:update_training_data` | Filtrado a `market_type IN (paralelo_digital, paralelo_fisico_empresa, parallel, digital)` |
| `predictions/tasks.py:update_training_data` | `rate.official_rate` → `(rate.buy_rate + rate.sell_rate) / 2` |

### Frontend

| Archivo | Cambio |
|---|---|
| `Rates.tsx` | `handleUpdateFromBCB` → `handleUpdateParallelRate` con source `dolarbluebolivia_click` |
| `Rates.tsx` | Botón "Actualizar BCB" → "Actualizar mercado paralelo" |
| `Rates.tsx` | Header tabla "Oficial BCB" → "Tasa mercado" |
| `Rates.tsx` | Tooltip "Tasa BCB por unidad individual" → "Tasa de mercado por unidad" |
| `Rates.tsx` | TextField label "Tasa Oficial BCB" → "Tasa de mercado" |
| `Rates.tsx` | Chips `official`/`bcb` → label "Paralelo" |
| `Rates.tsx` | `bcb_ref` live source config: label "REFERENCIAL" → "PARALELO" |
| `Rates.tsx` | Agregado helper `isStale()` + badge "⚠ Precio desactualizado" si > 30 min |
| `RateHistoryChart.tsx` | Eliminadas opciones "BCB Referencial" y "Oficial" del filtro de mercado |
| `ArbitrageAlerts.tsx` | `bcb_premium.label` "Prima BCB" → "Prima mercado" |
| `ArbitrageAlerts.tsx` | `MARKET_LABEL['official']` "BCB Oficial" → "Mercado paralelo" |
| `ArbitrageAlerts.tsx` | `MARKET_LABEL['bcb']` "BCB Ref." → "Mercado paralelo" |

---

## Qué se creó

| Archivo | Descripción |
|---|---|
| `backend/rates/scrapers/__init__.py` | Nuevo paquete scrapers standalone |
| `backend/rates/scrapers/dolar_blue_bolivia.py` | Scraper httpx+BeautifulSoup con CSS → regex fallback |
| `backend/rates/tests/__init__.py` | Paquete de tests para rates |
| `backend/rates/tests/test_scraper.py` | 14 tests: CSS selectors, regex fallback, error handling, rango |

---

## Qué NO se tocó (intencional)

| Componente | Razón |
|---|---|
| `ExchangeRate.MARKET_TYPE_CHOICES` (opciones `official`, `bcb`) | Preservadas para no romper datos históricos en DB |
| `ExchangeRateSource.SOURCE_TYPES` (`bcb_official`, `bcb_reference`) | Preservadas para no romper registros existentes |
| `ExchangeRate.official_rate` (campo DB) | Preservado; ahora almacena mid de mercado paralelo |
| `ExchangeRate.source` default `'BCB'` | Mantenido; los nuevos registros usan `source='dolarbluebolivia_click'` |
| `backend/rates/fetchers/bcb_fetcher.py` | Archivo preservado (no borrado); datos históricos lo referencian |
| `backend/rates/fetchers/reference_fetcher.py` | Archivo preservado (no borrado) |
| `capital/tasks.py` `unrealized_pnl_official` | Preservado; los valores son históricos, el campo se deprecará gradualmente |

---

## Nuevo schedule Celery Beat

```
fetch-parallel-rate   → rates.fetch_parallel_rate   → cada 15 min  (era: update-bcb-rates cada 30 min)
update-digital-rates  → rates.update_digital_rates  → cada 60 min  (sin cambios)
update-parallel-rates → rates.update_parallel_rates → cada 20 min  (sin cambios)
```
