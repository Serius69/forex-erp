"""
Airtm real-time quote fetcher.

POST https://app.airtm.com/v2/payments (or rate quote endpoint)
Body: {"amount": 10, "from": "BOB", "to": "USD"}

Extracts implied USD/BOB rate from the quote response.
"""
from __future__ import annotations
import logging
from decimal import Decimal, ROUND_HALF_UP

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.airtm_v2')

# Airtm endpoint candidates — tried in order
_AIRTM_ENDPOINTS = [
    # Public GET endpoints
    ('GET',  'https://airtm.com/api/v1/exchange-rates'),
    ('GET',  'https://app.airtm.com/api/v1/rates'),
    ('GET',  'https://app.airtm.com/api/rates'),
    ('GET',  'https://airtm.com/api/exchange-rates'),
    # Quote POST endpoint
    ('POST', 'https://app.airtm.com/v2/payments'),
]

AIRTM_QUOTE_URL  = 'https://app.airtm.com/v2/payments'
AIRTM_RATE_URL   = 'https://app.airtm.com/api/rates'

_Q4 = Decimal('0.0001')


def _q(val) -> Decimal:
    return Decimal(str(val)).quantize(_Q4, rounding=ROUND_HALF_UP)


class AirtmQuoteFetcher(BaseFetcher):
    """
    Obtains USD/BOB rate from Airtm by requesting a payment quote.
    The quote response contains the implied exchange rate.

    source_method = 'API'
    confidence    = 0.85
    """
    source_name = 'AIRTM'
    market_type = 'paralelo_digital'

    # Amount to quote (BOB → USD direction to get BOB/USD rate)
    QUOTE_AMOUNT_BOB = 100

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone

        fetched_at = timezone.now()
        session = self._get_session()
        session.headers.update({
            'Accept':     'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
        })

        for method, url in _AIRTM_ENDPOINTS:
            try:
                if method == 'POST':
                    resp = session.post(
                        url,
                        json={'amount': self.QUOTE_AMOUNT_BOB, 'from': 'BOB', 'to': 'USD'},
                        timeout=DEFAULT_TIMEOUT,
                    )
                else:
                    resp = session.get(url, timeout=DEFAULT_TIMEOUT)

                if resp.status_code in (403, 404, 401):
                    log.debug('AIRTM_SKIP status=%s url=%s', resp.status_code, url)
                    continue

                raw = resp.text.strip()
                if not raw or raw in ('{}', '[]', 'null'):
                    log.debug('AIRTM_EMPTY_BODY url=%s', url)
                    continue

                data = resp.json()
                if method == 'POST':
                    result = self._extract_from_quote(data, fetched_at, url)
                else:
                    result = self._extract_from_rates(data, fetched_at, url)

                if result:
                    log.info('AIRTM_OK url=%s results=%d', url, len(result))
                    return result

            except Exception as exc:
                log.debug('AIRTM_ENDPOINT_ERROR method=%s url=%s error=%s', method, url, exc)

        log.debug('AIRTM_ALL_ENDPOINTS_FAILED — no live data available')
        return []

    def _fetch_quote(self, fetched_at) -> list[FetchResult]:
        """POST /v2/payments with BOB→USD quote."""
        session = self._get_session()
        session.headers.update({'Content-Type': 'application/json'})

        try:
            resp = session.post(
                AIRTM_QUOTE_URL,
                json={
                    'amount': self.QUOTE_AMOUNT_BOB,
                    'from':   'BOB',
                    'to':     'USD',
                },
                timeout=DEFAULT_TIMEOUT,
            )
            if resp.status_code not in (200, 201):
                log.debug('AIRTM_QUOTE_STATUS %s', resp.status_code)
                return []

            data = resp.json()
            return self._extract_from_quote(data, fetched_at, AIRTM_QUOTE_URL)

        except Exception as exc:
            log.debug('AIRTM_QUOTE_ERROR %s', exc)
            return []

    def _fetch_rates_get(self, fetched_at) -> list[FetchResult]:
        """GET /api/rates as fallback."""
        session = self._get_session()
        try:
            resp = session.get(AIRTM_RATE_URL, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return self._extract_from_rates(data, fetched_at, AIRTM_RATE_URL)
        except Exception as exc:
            log.debug('AIRTM_RATES_GET_ERROR %s', exc)
            return []

    def _extract_from_quote(self, data: dict, fetched_at, url: str) -> list[FetchResult]:
        """
        Extract USD/BOB from a quote response.
        If we sent 100 BOB → X USD, then USD/BOB = 100 / X.
        """
        try:
            usd_received = _q(
                data.get('amount') or data.get('toAmount') or
                data.get('receivedAmount') or data.get('converted') or 0
            )
            if usd_received <= 0:
                # Try rate field directly
                rate = _q(data.get('rate') or data.get('exchangeRate') or 0)
                if rate <= 0:
                    return []
                bob_per_usd = rate
            else:
                bob_per_usd = _q(Decimal(str(self.QUOTE_AMOUNT_BOB)) / usd_received)

            if bob_per_usd <= 0:
                return []

            # Quote gives us the BUY price from customer perspective (BOB→USD)
            # Airtm typically has a ~2% fee embedded, spread is implicit
            buy_rate  = _q(bob_per_usd * Decimal('0.990'))  # we pay slightly less
            sell_rate = _q(bob_per_usd * Decimal('1.010'))  # we charge slightly more

            result = FetchResult(
                currency_code = 'USD',
                market_type   = self.market_type,
                source_name   = self.source_name,
                official_rate = (buy_rate + sell_rate) / Decimal('2'),
                buy_rate      = buy_rate,
                sell_rate     = sell_rate,
                scale_factor  = 1,
                confidence    = 0.85,
                source_method = 'API',
                source_url    = url,
                fetched_at    = fetched_at,
                raw_data      = {'implied_rate': float(bob_per_usd)},
            )
            return [result] if result.is_valid() else []

        except Exception as exc:
            log.debug('AIRTM_QUOTE_EXTRACT_ERROR %s', exc)
            return []

    def _extract_from_rates(self, data: dict | list, fetched_at, url: str) -> list[FetchResult]:
        """Extract from a GET /rates style response."""
        items = (data.get('rates', data.get('data', data))
                 if isinstance(data, dict) else data)

        if not isinstance(items, list):
            # Maybe it's {USD: {...}, ...}
            if isinstance(data, dict):
                items = [{'currency': k, **v}
                         for k, v in data.items()
                         if isinstance(v, dict)]
            else:
                items = []

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get('currency') or item.get('code') or '').upper()
            if code not in ('USD',):
                continue
            try:
                buy  = _q(item.get('buy') or item.get('compra') or item.get('bid') or 0)
                sell = _q(item.get('sell') or item.get('venta') or item.get('ask') or 0)
                if buy <= 0 or sell <= 0:
                    continue
                result = FetchResult(
                    currency_code = code,
                    market_type   = self.market_type,
                    source_name   = self.source_name,
                    official_rate = (buy + sell) / Decimal('2'),
                    buy_rate      = buy,
                    sell_rate     = sell,
                    scale_factor  = 1,
                    confidence    = 0.80,
                    source_method = 'API',
                    source_url    = url,
                    fetched_at    = fetched_at,
                )
                if result.is_valid():
                    results.append(result)
            except Exception as exc:
                log.debug('AIRTM_RATES_ITEM_ERROR %s', exc)

        return results
