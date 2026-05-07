"""
OKX C2P fetcher — USDT/BOB via OKX P2P API.

Endpoints tried in order (most reliable first):
  1. POST https://www.okx.com/v3/c2c/tradingOrders/books (legacy C2C)
  2. GET  https://www.okx.com/api/v5/fiat/exchange-rate?baseCcy=USDT&quoteCcy=BOB
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from django.core.cache import cache

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.okx')

_Q4    = Decimal('0.0001')
_BOB_LO = Decimal('7.0')
_BOB_HI = Decimal('16.0')
TOP_N  = 10

_C2C_URL  = 'https://www.okx.com/v3/c2c/tradingOrders/books'
_RATE_URL = 'https://www.okx.com/api/v5/fiat/exchange-rate'

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
    'Accept':     'application/json',
    'Referer':    'https://www.okx.com/',
}


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(_Q4, rounding=ROUND_HALF_UP)


class OKXFetcher(BaseFetcher):
    """
    OKX P2P / Convert — USDT/BOB parallel market rate.
    Falls back gracefully through multiple OKX endpoints.
    """
    source_name = 'OKX_P2P'
    market_type = 'paralelo_digital'

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone

        cached = cache.get('okx_usdt_bob')
        if cached:
            return cached

        session = self._get_session()
        session.headers.update(_HEADERS)
        fetched_at = timezone.now()

        # Try C2C P2P endpoint first
        result = self._try_c2c(session, fetched_at)

        # Fallback: fiat exchange-rate endpoint
        if not result:
            result = self._try_fiat_rate(session, fetched_at)

        if result:
            cache.set('okx_usdt_bob', [result], 300)
            return [result]
        return []

    # ── C2C books ─────────────────────────────────────────────────────────────

    def _try_c2c(self, session, fetched_at) -> FetchResult | None:
        buy_prices  = self._c2c_side(session, side='buy')
        sell_prices = self._c2c_side(session, side='sell')

        if not buy_prices and not sell_prices:
            return None

        buy_price  = _q(median(sorted(buy_prices)[:TOP_N]))  if buy_prices  else None
        sell_price = _q(median(sorted(sell_prices, reverse=True)[:TOP_N])) if sell_prices else None

        if not buy_price:
            buy_price = _q(sell_price * Decimal('0.995'))
        if not sell_price:
            sell_price = _q(buy_price * Decimal('1.005'))

        if not (_BOB_LO <= buy_price <= _BOB_HI):
            log.debug('OKX_C2C buy out of range (BOB not supported?): %s', buy_price)
            return None

        if buy_price > sell_price:
            sell_price = _q(buy_price * Decimal('1.005'))

        return FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = (buy_price + sell_price) / Decimal('2'),
            buy_rate      = buy_price,
            sell_rate     = sell_price,
            scale_factor  = 1,
            confidence    = 0.86,
            source_method = 'API',
            source_url    = _C2C_URL,
            fetched_at    = fetched_at,
        )

    def _c2c_side(self, session, side: str) -> list[float]:
        """
        side='sell' → merchant sells USDT → user buys USDT (sell price, higher)
        side='buy'  → merchant buys USDT  → user sells USDT (buy price, lower)
        """
        try:
            params = {
                'side':              'sell' if side == 'sell' else 'buy',
                'cryptoCurrency':    'USDT',
                'fiatCurrency':      'BOB',
                'paymentMethod':     'ALL',
                'userType':          'all',
                'showTrade':         'false',
                'showFollow':        'false',
                'showAlreadyTraded': 'false',
                'isAbleFilter':      'false',
            }
            resp = session.get(_C2C_URL, params=params, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            # Response shape: {"data": {"sell": [...], "buy": [...]}}
            # or {"data": [{"price": "9.30", ...}]}
            items = (
                data.get('data', {}).get(side, [])
                or data.get('data', [])
                or []
            )
            prices = []
            for item in items:
                try:
                    p = float(item.get('price') or item.get('quotePrice') or 0)
                    if _BOB_LO <= Decimal(str(p)) <= _BOB_HI:
                        prices.append(p)
                except (TypeError, ValueError):
                    pass
            return prices
        except Exception as exc:
            log.debug('OKX_C2C_SIDE side=%s error=%s', side, exc)
            return []

    # ── Fiat exchange-rate endpoint ────────────────────────────────────────────

    def _try_fiat_rate(self, session, fetched_at) -> FetchResult | None:
        try:
            resp = session.get(
                _RATE_URL,
                params={'baseCcy': 'USDT', 'quoteCcy': 'BOB'},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            # {"code":"0","data":[{"bestBuy":"9.35","bestSell":"9.60",...}]}
            items = data.get('data', [])
            if not items:
                return None

            row = items[0]
            buy  = _q(row.get('bestBuy')  or row.get('buyPrice')  or 0)
            sell = _q(row.get('bestSell') or row.get('sellPrice') or 0)

            if not (_BOB_LO <= buy <= _BOB_HI):
                return None
            if buy > sell or sell <= 0:
                sell = _q(buy * Decimal('1.010'))

            return FetchResult(
                currency_code = 'USD',
                market_type   = self.market_type,
                source_name   = self.source_name,
                official_rate = (buy + sell) / Decimal('2'),
                buy_rate      = buy,
                sell_rate     = sell,
                scale_factor  = 1,
                confidence    = 0.82,
                source_method = 'API',
                source_url    = _RATE_URL,
                fetched_at    = fetched_at,
            )
        except Exception as exc:
            log.debug('OKX_FIAT_RATE error=%s', exc)
            return None
