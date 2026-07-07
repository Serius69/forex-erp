"""
External API Rate Fetchers — DolarApi, OpenExchangeRates, ExchangeRate-API.

Sources (in priority order):
  1. Open Exchange Rates (free, no key, BOB base)  → official/reference rates
  2. ExchangeRate-API open tier  → mid-market reference
  3. Fixer.io (requires FIXER_API_KEY env var)      → institutional mid-market
  4. BCB JSON internal API                           → official Bolivia rates

All fetchers produce source_method='API' with confidence ≥ 0.85.
These rates are mid-market — they represent official/reference values.
For parallel/P2P market use Binance P2P + parallel_scraper.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT, apply_min_spread

log = logging.getLogger('kapitalya.rates.fetcher.external_api')

# Scale factors synced with Currency.scale_factor
_SCALE = {'USD': 1, 'EUR': 1, 'BRL': 1, 'PEN': 1, 'ARS': 1000, 'CLP': 1000}
_TARGET_CURRENCIES = {'USD', 'EUR', 'BRL', 'ARS', 'CLP', 'PEN'}


def _make_fetch_result(
    code: str,
    mid_rate_per_unit: Decimal,
    source_name: str,
    source_url: str,
    market_type: str = 'paralelo_digital',
    confidence: float = 0.88,
) -> FetchResult:
    """
    Builds a FetchResult from a mid-market per-unit rate.
    Applies a 0.20% spread (±0.10%) since the API only provides mid-market.
    buy_rate/sell_rate are per scale_factor units.
    """
    from django.utils import timezone

    scale  = _SCALE.get(code, 1)
    mid    = (mid_rate_per_unit * Decimal(str(scale))).quantize(Decimal('0.0001'))
    buy, sell = apply_min_spread(mid)

    return FetchResult(
        currency_code  = code,
        market_type    = market_type,
        source_name    = source_name,
        official_rate  = mid,
        buy_rate       = buy,
        sell_rate      = sell,
        scale_factor   = scale,
        confidence     = confidence,
        source_method  = 'API',
        source_url     = source_url,
        fetched_at     = timezone.now(),
        raw_data       = {'mid_per_unit': str(mid_rate_per_unit), 'scale': scale},
    )


class OpenExchangeRatesFetcher(BaseFetcher):
    """
    Open Exchange Rates — free tier, no API key required.
    Endpoint: https://open.er-api.com/v6/latest/BOB
    Returns rates relative to BOB (inverted to get X/BOB).
    """
    source_name = 'OPEN_ER_API'
    market_type = 'paralelo_digital'

    _URL = 'https://open.er-api.com/v6/latest/BOB'

    def _fetch(self) -> list[FetchResult]:
        from django.core.cache import cache
        cached = cache.get('open_er_api_results')
        if cached is not None:
            log.debug('OPEN_ER_API cache hit — %d results', len(cached))
            return cached

        session = self._get_session()
        resp    = session.get(self._URL, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data    = resp.json()

        if data.get('result') != 'success':
            log.warning('OPEN_ER_API non-success result: %s', data.get('result'))
            return []

        rates = data.get('rates', {})
        results: list[FetchResult] = []

        for code in _TARGET_CURRENCIES:
            raw = rates.get(code)
            if not raw:
                continue
            try:
                # rates[code] = BOB per 1 unit of code ... wait, base=BOB so:
                # rates[USD] = how many USD per 1 BOB → invert to get BOB per USD
                bob_per_unit = Decimal('1') / Decimal(str(raw))
                results.append(
                    _make_fetch_result(
                        code, bob_per_unit, self.source_name, self._URL,
                        confidence=0.88,
                    )
                )
            except Exception as exc:
                log.debug('OPEN_ER_API parse error %s: %s', code, exc)

        cache.set('open_er_api_results', results, 300)
        return results


class ExchangeRateAPIFetcher(BaseFetcher):
    """
    ExchangeRate-API open data endpoint — no key required.
    Endpoint: https://api.exchangerate-api.com/v4/latest/USD
    """
    source_name = 'EXCHANGERATE_API'
    market_type = 'paralelo_digital'

    _URL = 'https://api.exchangerate-api.com/v4/latest/USD'

    def _fetch(self) -> list[FetchResult]:
        session = self._get_session()
        resp    = session.get(self._URL, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data    = resp.json()

        rates = data.get('rates', {})
        bob_per_usd = Decimal(str(rates.get('BOB', 0)))
        if bob_per_usd <= 0:
            log.warning('EXCHANGERATE_API no BOB rate found')
            return []

        results: list[FetchResult] = []
        for code in _TARGET_CURRENCIES:
            raw = rates.get(code)
            if not raw or float(raw) == 0:
                continue
            try:
                # rates are relative to USD → convert to BOB:
                # rate_code = bob_per_usd / usd_per_code  (rates[code] = USD per 1 code? No...)
                # Actually: rates[X] = how many X per 1 USD
                # So: BOB per 1 X = (rates[BOB] / rates[X]) = bob_per_usd / rates[code]
                usd_per_code = Decimal(str(raw))
                if code == 'USD':
                    bob_per_unit = bob_per_usd
                else:
                    # rates[code] = units of code per 1 USD
                    # → 1 code = (1/rates[code]) USD = (bob_per_usd / rates[code]) BOB
                    bob_per_unit = bob_per_usd / usd_per_code

                results.append(
                    _make_fetch_result(
                        code, bob_per_unit, self.source_name, self._URL,
                        confidence=0.85,
                    )
                )
            except Exception as exc:
                log.debug('EXCHANGERATE_API parse error %s: %s', code, exc)

        return results


class FixerIOFetcher(BaseFetcher):
    """
    Fixer.io — requires FIXER_API_KEY in settings.
    Disabled automatically if no key is configured.
    """
    source_name = 'FIXER_IO'
    market_type = 'paralelo_digital'

    def _fetch(self) -> list[FetchResult]:
        api_key = getattr(settings, 'FIXER_API_KEY', '') or ''
        if not api_key:
            log.debug('FIXER_IO skipped — FIXER_API_KEY not configured')
            return []

        url = f'https://data.fixer.io/api/latest?access_key={api_key}&base=EUR&symbols=BOB,USD,BRL,ARS,CLP,PEN'
        session = self._get_session()
        resp    = session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data    = resp.json()

        if not data.get('success'):
            log.warning('FIXER_IO error: %s', data.get('error'))
            return []

        rates   = data.get('rates', {})
        bob_per_eur = Decimal(str(rates.get('BOB', 0)))
        if bob_per_eur <= 0:
            return []

        results: list[FetchResult] = []
        for code in _TARGET_CURRENCIES:
            raw = rates.get(code)
            if not raw or float(raw) == 0:
                continue
            try:
                eur_units = Decimal(str(raw))
                if code == 'EUR':
                    bob_per_unit = bob_per_eur
                else:
                    bob_per_unit = bob_per_eur / eur_units

                from django.utils import timezone
                scale = _SCALE.get(code, 1)
                scaled = bob_per_unit * Decimal(str(scale))
                spread = scaled * Decimal('0.001')
                buy_f  = (scaled - spread).quantize(Decimal('0.0001'))
                sell_f = (scaled + spread).quantize(Decimal('0.0001'))
                results.append(FetchResult(
                    currency_code  = code,
                    market_type    = self.market_type,
                    source_name    = self.source_name,
                    official_rate  = (buy_f + sell_f) / Decimal('2'),
                    buy_rate       = buy_f,
                    sell_rate      = sell_f,
                    scale_factor   = scale,
                    confidence     = 0.90,
                    source_method  = 'API',
                    source_url     = 'https://data.fixer.io/api/latest',
                    fetched_at     = timezone.now(),
                ))
            except Exception as exc:
                log.debug('FIXER_IO parse error %s: %s', code, exc)

        return results


class BCBJsonAPIFetcher(BaseFetcher):
    """
    BCB internal JSON API — dormant, kept for reference only. Not invoked by aggregator.
    """
    source_name = 'BCB_JSON_API'
    market_type = 'paralelo_digital'

    _CANDIDATES = [
        'https://www.bcb.gob.bo/librerias/indicadores/tipoCambio.json',
        'https://www.bcb.gob.bo/tipo-de-cambio',
    ]

    _CURRENCY_MAP = {
        'USD': 'USD', 'DÓLAR': 'USD', 'DOLAR': 'USD',
        'EUR': 'EUR', 'EURO': 'EUR',
        'BRL': 'BRL', 'REAL': 'BRL',
        'ARS': 'ARS', 'PESO ARGENTINO': 'ARS',
        'CLP': 'CLP', 'PESO CHILENO': 'CLP',
        'PEN': 'PEN', 'SOL': 'PEN',
    }

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone

        session = self._get_session()
        for url in self._CANDIDATES:
            try:
                resp = session.get(url, timeout=DEFAULT_TIMEOUT)
                resp.raise_for_status()

                try:
                    data = resp.json()
                except Exception:
                    continue

                results = self._parse_json(data, url)
                if results:
                    return results
            except Exception as exc:
                log.debug('BCB_JSON_API candidate %s failed: %s', url, exc)

        return []

    def _parse_json(self, data, source_url: str) -> list[FetchResult]:
        from django.utils import timezone
        results: list[FetchResult] = []

        entries = data if isinstance(data, list) else data.get('tasas', data.get('data', []))
        if not isinstance(entries, list):
            return []

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get('moneda', entry.get('name', entry.get('currency', '')))).upper()
            code = self._CURRENCY_MAP.get(name)
            if not code:
                continue

            try:
                raw_rate = entry.get('venta', entry.get('sell', entry.get('rate', entry.get('tc', 0))))
                rate = Decimal(str(raw_rate))
                if rate <= 0:
                    continue

                scale = _SCALE.get(code, 1)
                scaled = rate * Decimal(str(scale))
                spread = scaled * Decimal('0.001')
                buy_s  = (scaled - spread).quantize(Decimal('0.0001'))
                sell_s = (scaled + spread).quantize(Decimal('0.0001'))
                results.append(FetchResult(
                    currency_code  = code,
                    market_type    = self.market_type,
                    source_name    = self.source_name,
                    official_rate  = (buy_s + sell_s) / Decimal('2'),
                    buy_rate       = buy_s,
                    sell_rate      = sell_s,
                    scale_factor   = scale,
                    confidence     = 0.92,
                    source_method  = 'API',
                    source_url     = source_url,
                    fetched_at     = timezone.now(),
                ))
            except Exception as exc:
                log.debug('BCB_JSON_API entry parse error %s: %s', name, exc)

        return results
