"""
BCP Bolivia (Banco de Crédito de Bolivia) — exchange rate scraper.
URL: https://www.bcp.com.bo/librerias/indicadores/tipo_cambio.php

BCP publishes buy/sell rates for the major currencies traded in Bolivia.
This is a commercial bank rate — closer to the street/parallel rate than BCB official.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal

from bs4 import BeautifulSoup

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.bcp')

_SCALE = {'USD': 1, 'EUR': 1, 'BRL': 1, 'PEN': 1, 'ARS': 1000, 'CLP': 1000}

_CURRENCY_PATTERNS = {
    r'dólar|dollar|usd':        'USD',
    r'euro|eur':                 'EUR',
    r'real|brl':                 'BRL',
    r'peso\s+arg|ars':           'ARS',
    r'peso\s+chil|clp':         'CLP',
    r'sol\s+per|pen':            'PEN',
}


class BCPBoliviaFetcher(BaseFetcher):
    """
    BCP Bolivia — commercial bank rates (buy/sell).
    Falls back to a secondary URL if the primary fails.
    """
    source_name = 'BCP_BOLIVIA'
    market_type = 'bcb'

    _URLS = [
        'https://www.bcp.com.bo/librerias/indicadores/tipo_cambio.php',
        'https://www.bcp.com.bo/tipo-de-cambio',
        'https://www.bcp.com.bo/',
    ]

    def _fetch(self) -> list[FetchResult]:
        session = self._get_session()

        for url in self._URLS:
            try:
                resp = session.get(url, timeout=DEFAULT_TIMEOUT)
                resp.raise_for_status()
                results = self._parse(resp.content, url)
                if results:
                    log.info('BCP_BOLIVIA success url=%s rates=%d', url, len(results))
                    return results
            except Exception as exc:
                log.debug('BCP_BOLIVIA url=%s failed: %s', url, exc)

        log.warning('BCP_BOLIVIA all URLs failed')
        return []

    def _parse(self, content: bytes, source_url: str) -> list[FetchResult]:
        from django.utils import timezone

        soup    = BeautifulSoup(content, 'html.parser')
        results = []

        # Strategy 1: structured table with class containing "cambio" or "divisa"
        tables = (
            soup.find_all('table', {'class': re.compile(r'cambio|divisa|cotiz', re.I)}) or
            soup.find_all('table')
        )

        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 3:
                    continue

                text_cells = [c.get_text(strip=True) for c in cells]
                currency_cell = text_cells[0].lower()

                code = self._match_currency(currency_cell)
                if not code:
                    continue

                try:
                    buy_raw  = self._clean_number(text_cells[1])
                    sell_raw = self._clean_number(text_cells[2]) if len(text_cells) > 2 else buy_raw
                    buy  = Decimal(buy_raw)
                    sell = Decimal(sell_raw)

                    if buy <= 0 or sell <= 0 or buy > sell:
                        continue

                    scale   = _SCALE.get(code, 1)
                    mid     = (buy + sell) / Decimal('2')
                    official = mid / Decimal(str(scale))

                    results.append(FetchResult(
                        currency_code  = code,
                        market_type    = self.market_type,
                        source_name    = self.source_name,
                        official_rate  = official.quantize(Decimal('0.0001')),
                        buy_rate       = buy.quantize(Decimal('0.0001')),
                        sell_rate      = sell.quantize(Decimal('0.0001')),
                        scale_factor   = scale,
                        confidence     = 0.82,
                        source_method  = 'SCRAP',
                        source_url     = source_url,
                        fetched_at     = timezone.now(),
                    ))
                except Exception as exc:
                    log.debug('BCP_BOLIVIA row parse error: cells=%s err=%s', text_cells, exc)

            if results:
                return results

        # Strategy 2: look for any pattern like "USD ... 6.96 ... 6.96"
        text = soup.get_text(separator='\n')
        results = self._parse_text_fallback(text, source_url)
        return results

    def _match_currency(self, text: str) -> str | None:
        for pattern, code in _CURRENCY_PATTERNS.items():
            if re.search(pattern, text, re.I):
                return code
        return None

    @staticmethod
    def _clean_number(text: str) -> str:
        return re.sub(r'[^\d.,]', '', text).replace(',', '.')

    def _parse_text_fallback(self, text: str, source_url: str) -> list[FetchResult]:
        from django.utils import timezone

        results = []
        lines   = text.split('\n')
        for i, line in enumerate(lines):
            code = self._match_currency(line.lower())
            if not code:
                continue
            # Look for numbers in the same line or next 2 lines
            search_text = ' '.join(lines[i:i + 3])
            numbers = re.findall(r'\b(\d{1,3}(?:[.,]\d{1,4})?)\b', search_text)
            decimals = []
            for n in numbers:
                try:
                    val = Decimal(n.replace(',', '.'))
                    if Decimal('1') <= val <= Decimal('100'):
                        decimals.append(val)
                except Exception:
                    pass

            if len(decimals) >= 2:
                buy, sell = decimals[0], decimals[1]
                if buy > sell:
                    buy, sell = sell, buy
                scale   = _SCALE.get(code, 1)
                mid     = (buy + sell) / Decimal('2')
                official = mid / Decimal(str(scale))
                results.append(FetchResult(
                    currency_code  = code,
                    market_type    = self.market_type,
                    source_name    = self.source_name,
                    official_rate  = official.quantize(Decimal('0.0001')),
                    buy_rate       = buy.quantize(Decimal('0.0001')),
                    sell_rate      = sell.quantize(Decimal('0.0001')),
                    scale_factor   = scale,
                    confidence     = 0.72,
                    source_method  = 'SCRAP',
                    source_url     = source_url,
                    fetched_at     = timezone.now(),
                ))

        return results


class BCPJsonAPIFetcher(BaseFetcher):
    """
    BCP Bolivia JSON indicator endpoint (if available).
    """
    source_name = 'BCP_JSON'
    market_type = 'bcb'

    _URL = 'https://www.bcp.com.bo/librerias/indicadores/tipo_cambio.json'

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone

        session = self._get_session()
        try:
            resp = session.get(self._URL, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.debug('BCP_JSON failed: %s', exc)
            return []

        entries = data if isinstance(data, list) else data.get('data', data.get('tasas', []))
        results = []

        for entry in (entries or []):
            if not isinstance(entry, dict):
                continue
            code = BCPBoliviaFetcher()._match_currency(
                str(entry.get('moneda', entry.get('currency', ''))).lower()
            )
            if not code:
                continue
            try:
                buy  = Decimal(str(entry.get('compra', entry.get('buy', 0))))
                sell = Decimal(str(entry.get('venta', entry.get('sell', 0))))
                if buy <= 0 or sell <= 0:
                    continue
                scale   = _SCALE.get(code, 1)
                mid     = (buy + sell) / Decimal('2')
                official = mid / Decimal(str(scale))
                results.append(FetchResult(
                    currency_code  = code,
                    market_type    = self.market_type,
                    source_name    = self.source_name,
                    official_rate  = official.quantize(Decimal('0.0001')),
                    buy_rate       = buy.quantize(Decimal('0.0001')),
                    sell_rate      = sell.quantize(Decimal('0.0001')),
                    scale_factor   = scale,
                    confidence     = 0.87,
                    source_method  = 'API',
                    source_url     = self._URL,
                    fetched_at     = timezone.now(),
                ))
            except Exception as exc:
                log.debug('BCP_JSON entry parse error: %s', exc)

        return results
