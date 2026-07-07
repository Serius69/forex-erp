"""
Wallbit exchange rate fetcher.

GET https://api.wallbit.io/v1/rates?currencies=USD,EUR,BRL,PEN,ARS,CLP
Headers: X-API-Key: <WALLBIT_API_KEY>

Returns rates for multiple currencies vs BOB (or vs USD which we cross-rate).
"""
from __future__ import annotations
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.wallbit')

WALLBIT_BASE_URL = 'https://api.wallbit.io/v1/rates'
CURRENCIES_PARAM = 'USD,EUR,BRL,PEN,ARS,CLP'

SCALE_FACTORS = {'ARS': 1000, 'CLP': 1000}

_KNOWN_CURRENCIES = frozenset({'USD', 'EUR', 'BRL', 'PEN', 'ARS', 'CLP'})

_Q4 = Decimal('0.0001')


def _q(val) -> Decimal:
    return Decimal(str(val)).quantize(_Q4, rounding=ROUND_HALF_UP)


class WallbitFetcher(BaseFetcher):
    """
    Fetches multi-currency rates from Wallbit via authenticated API.
    API key is read from settings.WALLBIT_API_KEY or env var.
    """
    source_name = 'WALLBIT'
    market_type = 'paralelo_digital'

    def _get_api_key(self) -> str | None:
        return getattr(settings, 'WALLBIT_API_KEY', None)

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone

        api_key = self._get_api_key()
        if not api_key:
            log.debug('WALLBIT_NO_API_KEY — skipping fetcher (configure WALLBIT_API_KEY)')
            return []

        session = self._get_session()
        session.headers.update({
            'X-API-Key': api_key,
            'Accept':    'application/json',
        })

        fetched_at = timezone.now()

        try:
            resp = session.get(
                WALLBIT_BASE_URL,
                params={'currencies': CURRENCIES_PARAM},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error('WALLBIT_FETCH_ERROR %s', exc)
            return []

        return self._parse(data, fetched_at)

    def _parse(self, data: dict | list, fetched_at) -> list[FetchResult]:
        results = []

        # Wallbit may return {USD: {...}, EUR: {...}} or [{currency, buy, sell}...]
        if isinstance(data, dict):
            # Try direct currency-keyed dict
            items = []
            for code, val in data.items():
                if code.upper() in _KNOWN_CURRENCIES:
                    if isinstance(val, dict):
                        val['currency'] = code.upper()
                        items.append(val)
                    elif isinstance(val, (int, float)):
                        # Single rate value — treat as mid-rate
                        items.append({'currency': code.upper(), 'mid': val})

            # Or nested under 'data' / 'rates'
            if not items:
                items = data.get('rates', data.get('data', []))
        else:
            items = data

        for item in items:
            if not isinstance(item, dict):
                continue

            code = str(
                item.get('currency') or item.get('code') or item.get('asset') or ''
            ).upper()

            if code not in _KNOWN_CURRENCIES:
                continue

            try:
                buy  = _q(item.get('buy')  or item.get('compra') or item.get('bid') or
                          item.get('mid')  or 0)
                sell = _q(item.get('sell') or item.get('venta')  or item.get('ask') or
                          item.get('mid')  or 0)

                if buy <= 0 and sell <= 0:
                    continue
                if buy <= 0:
                    buy = _q(sell * Decimal('0.995'))
                if sell <= 0:
                    sell = _q(buy * Decimal('1.005'))

                scale = SCALE_FACTORS.get(code, 1)

                buy_scaled  = buy  * Decimal(str(scale)) if scale > 1 else buy
                sell_scaled = sell * Decimal(str(scale)) if scale > 1 else sell

                result = FetchResult(
                    currency_code = code,
                    market_type   = self.market_type,
                    source_name   = self.source_name,
                    official_rate = (buy_scaled + sell_scaled) / Decimal('2'),
                    buy_rate      = buy_scaled,
                    sell_rate     = sell_scaled,
                    scale_factor  = scale,
                    confidence    = 0.88,
                    source_method = 'API',
                    source_url    = WALLBIT_BASE_URL,
                    fetched_at    = fetched_at,
                )
                if result.is_valid():
                    results.append(result)

            except Exception as exc:
                log.debug('WALLBIT_ITEM_ERROR code=%s error=%s', code, exc)

        log.info('WALLBIT_PARSED results=%d', len(results))
        return results
