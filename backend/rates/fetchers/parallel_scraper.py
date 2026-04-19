"""
Fetcher para tasas del mercado paralelo boliviano.

Fuentes objetivo:
  - DolarBoliviano.com  — referencia histórica del dólar paralelo en Bolivia
  - Cotizaciones de cambistas en redes sociales (no automatizable)
  - Foros de tipo de cambio boliviano
  - Estimación basada en spread histórico del mercado paralelo (~30-40% sobre BCB)

Nota: El mercado paralelo boliviano no tiene una fuente oficial centralizada.
Las casas de cambio no publican sus tasas online. Se usan sitios de referencia
comunitarios como proxy del precio real de mercado.
"""
from __future__ import annotations
import logging
import re
from decimal import Decimal

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.parallel')

# Spread estimado del mercado paralelo boliviano
# Basado en observación histórica 2023-2025
# USD: ~30-38% sobre BCB (6.96 → ~9.10-9.60)
# EUR: spread similar al USD en términos relativos
PARALLEL_SPREAD_ESTIMATE = {
    'USD': {'buy_premium': Decimal('0.32'), 'sell_premium': Decimal('0.38')},
    'EUR': {'buy_premium': Decimal('0.28'), 'sell_premium': Decimal('0.34')},
    'BRL': {'buy_premium': Decimal('0.18'), 'sell_premium': Decimal('0.24')},
    'ARS': {'buy_premium': Decimal('0.12'), 'sell_premium': Decimal('0.18')},
    'CLP': {'buy_premium': Decimal('0.22'), 'sell_premium': Decimal('0.28')},
    'PEN': {'buy_premium': Decimal('0.18'), 'sell_premium': Decimal('0.24')},
}

BCB_REFERENCE = {
    'USD': Decimal('6.96'),
    'EUR': Decimal('7.52'),
    'BRL': Decimal('1.22'),
    'ARS': Decimal('0.007'),
    'CLP': Decimal('0.0076'),
    'PEN': Decimal('1.85'),
}

SCALE_FACTORS = {'USD': 1, 'EUR': 1, 'BRL': 1, 'PEN': 1, 'ARS': 1000, 'CLP': 1000}

# Patrones regex para extraer tasas de páginas HTML
_RATE_PATTERNS = [
    # "Compra: 9.30" o "Compra 9.30 BOB"
    r'(?:compra|buy)[:\s]+(\d+[\.,]\d{1,4})',
    # "Venta: 9.60" o "Venta 9.60 BOB"
    r'(?:venta|sell)[:\s]+(\d+[\.,]\d{1,4})',
    # "USD 9.30 / 9.60"
    r'USD[:\s]+(\d+[\.,]\d{1,4})\s*/\s*(\d+[\.,]\d{1,4})',
    # Tabla con dos valores consecutivos tipo 9.30 9.60
    r'(\d+[\.,]\d{2,4})\s+(\d+[\.,]\d{2,4})',
]


def _clean_decimal(text: str) -> Decimal | None:
    """Intenta convertir texto en Decimal, tolerando comas y espacios."""
    try:
        cleaned = re.sub(r'[^\d.,]', '', text).replace(',', '.')
        if cleaned:
            return Decimal(cleaned)
    except Exception:
        pass
    return None


class ParallelMarketFetcher(BaseFetcher):
    """
    Fetcher principal del mercado paralelo boliviano.

    Estrategia en cascada:
      1. Scraping de sitios de referencia del mercado paralelo boliviano
      2. Extracción de datos estructurados (JSON-LD / meta tags)
      3. Estimación con spread histórico (confidence=0.60)
    """
    source_name = 'PARALELO'
    market_type = 'parallel'

    def _fetch(self) -> list[FetchResult]:
        results = self._scrape_reference_sites()
        if results:
            return results
        log.info("PARALLEL_SCRAPE_FAILED — usando estimación histórica")
        return self._estimate_parallel_rates()

    def _scrape_reference_sites(self) -> list[FetchResult]:
        """Intenta múltiples sitios de referencia del dólar paralelo boliviano."""
        results = self._scrape_dolar_boliviano()
        if results:
            return results

        results = self._scrape_cambio_bolivia()
        if results:
            return results

        return []

    # ------------------------------------------------------------------ #
    #  Fuente 1: DolarBoliviano / sitios de referencia similares          #
    # ------------------------------------------------------------------ #

    def _scrape_dolar_boliviano(self) -> list[FetchResult]:
        """
        Intenta extraer la cotización del dólar paralelo de sitios de referencia.
        Estos sitios publican cotizaciones del mercado informal boliviano.
        """
        from bs4 import BeautifulSoup

        candidate_urls = [
            'https://www.bcb.gob.bo/mercadocambiario/',  # BCB también publica tabla de autorizado
        ]
        session = self._get_session()

        for url in candidate_urls:
            try:
                resp = session.get(url, timeout=DEFAULT_TIMEOUT)
                if resp.status_code != 200:
                    continue

                ctype = resp.headers.get('content-type', '')
                if 'json' in ctype:
                    parsed = self._parse_json_rates(resp.json(), 'PARALELO')
                    if parsed:
                        return parsed

                soup = BeautifulSoup(resp.text, 'html.parser')
                parsed = self._parse_generic_rate_table(soup, url)
                if parsed:
                    return parsed

            except Exception as exc:
                log.debug("PARALLEL_URL_FAILED url=%s error=%s", url, exc)
                continue

        return []

    def _scrape_cambio_bolivia(self) -> list[FetchResult]:
        """
        Segunda fuente: páginas con tablas de casas de cambio autorizadas ASFI.
        ASFI publica tasas autorizadas; el paralelo está ~30% encima.
        """
        from bs4 import BeautifulSoup

        urls = [
            'https://www.asfi.gob.bo/index.php/tipo-de-cambio.html',
        ]
        session = self._get_session()

        for url in urls:
            try:
                resp = session.get(url, timeout=DEFAULT_TIMEOUT)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, 'html.parser')
                parsed = self._parse_generic_rate_table(soup, url)
                if parsed:
                    # ASFI rates are "authorized" not parallel — lower confidence
                    for r in parsed:
                        r.confidence = min(r.confidence, 0.65)
                        r.source_name = 'ASFI_AUTORIZADO'
                    return parsed
            except Exception as exc:
                log.debug("ASFI_URL_FAILED url=%s error=%s", url, exc)

        return []

    # ------------------------------------------------------------------ #
    #  Parsers genéricos                                                   #
    # ------------------------------------------------------------------ #

    def _parse_generic_rate_table(self, soup, source_url: str) -> list[FetchResult]:
        """
        Busca tablas HTML con pares divisa/tasa usando heurísticas robustas.
        Soporta tablas con columnas Compra/Venta o un solo valor de referencia.
        """
        results    = []
        found_data = {}  # code → {buy, sell}

        # Buscar en todas las tablas
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cols = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
                if len(cols) < 2:
                    continue

                # Detectar si la primera columna contiene un código de divisa conocido
                first = cols[0].upper().strip()
                code  = self._detect_currency_code(first)
                if not code:
                    continue

                # Intentar extraer valores numéricos de las siguientes columnas
                decimals = []
                for col in cols[1:]:
                    d = _clean_decimal(col)
                    if d is not None and d > Decimal('0.001'):
                        decimals.append(d)

                if not decimals:
                    continue

                buy  = decimals[0]
                sell = decimals[1] if len(decimals) >= 2 else decimals[0] * Decimal('1.02')

                # Sanity check: valores razonables para BOB
                ref = BCB_REFERENCE.get(code, Decimal('1'))
                scale = SCALE_FACTORS.get(code, 1)
                # buy/sell deben estar en el rango [0.5*ref, 5*ref] (por unidad)
                buy_per_unit  = buy  / Decimal(str(scale))
                sell_per_unit = sell / Decimal(str(scale))
                if not (ref * Decimal('0.5') <= buy_per_unit <= ref * Decimal('5')):
                    log.debug(
                        "PARALLEL_SANITY_FAIL code=%s buy_per_unit=%s ref=%s",
                        code, buy_per_unit, ref,
                    )
                    continue

                found_data[code] = {'buy': buy, 'sell': sell}

        # Construir FetchResults
        for code, vals in found_data.items():
            ref   = BCB_REFERENCE.get(code, Decimal('1'))
            scale = SCALE_FACTORS.get(code, 1)

            result = FetchResult(
                currency_code = code,
                market_type   = self.market_type,
                source_name   = self.source_name,
                official_rate = ref,
                buy_rate      = vals['buy'],
                sell_rate     = vals['sell'],
                scale_factor  = scale,
                confidence    = 0.72,
                raw_data      = {'source_url': source_url},
            )
            if result.is_valid():
                results.append(result)

        log.debug(
            "PARALLEL_TABLE_PARSE url=%s found=%d", source_url, len(results)
        )
        return results

    def _parse_json_rates(self, data: dict | list, source_suffix: str) -> list[FetchResult]:
        """Parsea JSON con tasas de cambio en formato genérico."""
        results = []
        items   = data if isinstance(data, list) else (
            data.get('rates', data.get('data', [data]))
        )
        if not isinstance(items, list):
            items = [items]

        for item in items:
            if not isinstance(item, dict):
                continue
            code_raw = str(item.get('currency', item.get('moneda', item.get('code', '')))).upper()
            code     = self._detect_currency_code(code_raw)
            if not code:
                continue

            try:
                buy  = self._to_decimal(item.get('buy',  item.get('compra')))
                sell = self._to_decimal(item.get('sell', item.get('venta')))
                ref  = BCB_REFERENCE.get(code, Decimal('1'))
                scale = SCALE_FACTORS.get(code, 1)

                result = FetchResult(
                    currency_code = code,
                    market_type   = self.market_type,
                    source_name   = source_suffix,
                    official_rate = ref,
                    buy_rate      = buy  * Decimal(str(scale)) if scale > 1 and buy < ref * 10 else buy,
                    sell_rate     = sell * Decimal(str(scale)) if scale > 1 and sell < ref * 10 else sell,
                    scale_factor  = scale,
                    confidence    = 0.75,
                    raw_data      = item,
                )
                if result.is_valid():
                    results.append(result)
            except Exception as exc:
                log.debug("PARALLEL_JSON_ITEM_ERROR item=%s error=%s", item, exc)

        return results

    @staticmethod
    def _detect_currency_code(text: str) -> str | None:
        """Detecta código ISO de divisa en texto (incluyendo nombres en español)."""
        text = text.upper().strip()

        exact = {
            'USD', 'EUR', 'BRL', 'ARS', 'CLP', 'PEN',
            'BOB', 'GBP', 'JPY', 'CHF',
        }
        if text in exact:
            return text if text in BCB_REFERENCE else None

        # Nombres en español
        spanish_map = {
            'DÓLAR': 'USD', 'DOLAR': 'USD', 'DOLLAR': 'USD',
            'DÓLAR AMERICANO': 'USD', 'DOLAR AMERICANO': 'USD',
            'DÓLAR ESTADOUNIDENSE': 'USD', 'DOLAR ESTADOUNIDENSE': 'USD',
            'EURO': 'EUR', 'EUROS': 'EUR',
            'REAL': 'BRL', 'REAL BRASILEÑO': 'BRL', 'REAL BRASILENO': 'BRL',
            'PESO ARGENTINO': 'ARS',
            'PESO CHILENO': 'CLP',
            'SOL PERUANO': 'PEN', 'SOL': 'PEN',
        }
        for pattern, code in spanish_map.items():
            if pattern in text:
                return code

        return None

    # ------------------------------------------------------------------ #
    #  Estimación de último recurso                                        #
    # ------------------------------------------------------------------ #

    def _estimate_parallel_rates(self) -> list[FetchResult]:
        """
        Estimación basada en spread histórico del mercado paralelo boliviano.

        COMPLIANCE: source_method='INFERENCE', confidence=0.60.
        Estas tasas NO provienen de scraping en tiempo real.
        Se marcan para que el frontend muestre advertencia y requiera confirmación.
        """
        from django.utils import timezone as tz
        results    = []
        fetched_at = tz.now()

        for code, ref in BCB_REFERENCE.items():
            spread = PARALLEL_SPREAD_ESTIMATE.get(code, {
                'buy_premium':  Decimal('0.25'),
                'sell_premium': Decimal('0.32'),
            })
            scale     = SCALE_FACTORS.get(code, 1)
            buy_unit  = ref * (1 + spread['buy_premium'])
            sell_unit = ref * (1 + spread['sell_premium'])

            result = FetchResult(
                currency_code = code,
                market_type   = self.market_type,
                source_name   = 'PARALELO_EST',
                official_rate = ref,
                buy_rate      = buy_unit  * Decimal(str(scale)),
                sell_rate     = sell_unit * Decimal(str(scale)),
                scale_factor  = scale,
                confidence    = 0.60,
                raw_data      = {
                    'method':       'estimated',
                    'buy_premium':  float(spread['buy_premium']),
                    'sell_premium': float(spread['sell_premium']),
                    'warning':      'NOT_REAL_TIME',
                },
                source_method = 'INFERENCE',
                source_url    = None,
                fetched_at    = fetched_at,
            )
            if result.is_valid():
                results.append(result)

        log.warning(
            "PARALLEL_RATES_ESTIMATED — all scraping failed, "
            "using INFERENCE fallback with hardcoded spreads"
        )
        return results


class CasaDeCambioFetcher(BaseFetcher):
    """
    Fetcher para casas de cambio bolivianas autorizadas por ASFI.
    Las casas de cambio publican tasas que reflejan el mercado real,
    aunque son ligeramente inferiores al mercado paralelo informal.
    """
    source_name = 'CASA_CAMBIO'
    market_type = 'parallel'

    def _fetch(self) -> list[FetchResult]:
        """Usa ParallelMarketFetcher como base y ajusta source_name."""
        base    = ParallelMarketFetcher()
        results = base._scrape_reference_sites()

        if not results:
            return []

        for r in results:
            r.source_name = self.source_name
            r.confidence  = min(r.confidence, 0.70)

        return results
