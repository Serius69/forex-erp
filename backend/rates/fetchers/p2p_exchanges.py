"""
P2P exchange fetchers — Bitget P2P and Bybit P2P.

Both return USDT/BOB prices (USDT ≈ USD).
All prices are in BOB per 1 USDT.

Bitget P2P: GET https://api.bitget.com/api/v2/p2p/merchant-ad-list?fiat=BOB&side=BUY
Bybit P2P:  GET https://api.bybit.com/v5/p2p/item/online?fiatCurrency=BOB&direction=BUY
"""
from __future__ import annotations
import logging
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from typing import Optional

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.p2p_exchanges')

_Q4 = Decimal('0.0001')
_Q2 = Decimal('0.01')

BITGET_BASE_URL = 'https://api.bitget.com'
BYBIT_BASE_URL  = 'https://api.bybit.com'


TOP_N = 10  # use top N ads per side


def _q(val, places=_Q4) -> Decimal:
    return Decimal(str(val)).quantize(places, rounding=ROUND_HALF_UP)


class BitgetP2PFetcher(BaseFetcher):
    """
    Bitget P2P USDT/BOB.
    GET /api/v2/p2p/merchant-ad-list?fiat=BOB&side=BUY&currency=USDT
    side=BUY  → ads where merchant buys USDT from user → buyer price (lower)
    side=SELL → ads where merchant sells USDT to user → seller price (higher)
    """
    source_name = 'BITGET_P2P'
    market_type = 'paralelo_digital'

    def _fetch(self) -> list[FetchResult]:
        import requests
        from django.utils import timezone

        session = self._get_session()
        fetched_at = timezone.now()

        buy_prices  = self._fetch_side(session, 'BUY')
        sell_prices = self._fetch_side(session, 'SELL')

        if not buy_prices and not sell_prices:
            log.debug('BITGET_P2P_NO_PRICES — all endpoints failed or unsupported')
            return []

        buy_prices  = sorted(buy_prices)[:TOP_N]
        sell_prices = sorted(sell_prices, reverse=True)[:TOP_N]

        buy_price  = _q(median(buy_prices))  if buy_prices  else None
        sell_price = _q(median(sell_prices)) if sell_prices else None

        if not buy_price and not sell_price:
            return []

        # If one side is missing, mirror the other with a minimal spread
        if not buy_price:
            buy_price = _q(sell_price * Decimal('0.995'))
        if not sell_price:
            sell_price = _q(buy_price * Decimal('1.005'))

        if buy_price > sell_price:
            sell_price = _q(buy_price * Decimal('1.005'))

        result = FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = (buy_price + sell_price) / Decimal('2'),
            buy_rate      = buy_price,
            sell_rate     = sell_price,
            scale_factor  = 1,
            confidence    = 0.88,
            source_method = 'API',
            source_url    = f'{BITGET_BASE_URL}/api/v2/p2p/merchant-ad-list',
            fetched_at    = fetched_at,
        )
        return [result] if result.is_valid() else []

    def _fetch_side(self, session, side: str) -> list[float]:
        """Returns list of float prices for the given side (BUY/SELL)."""
        # Bitget P2P endpoint variants — try each until one returns prices
        candidates = [
            ('GET',  f'{BITGET_BASE_URL}/api/v2/p2p/advList', {
                'fiatCurrency': 'BOB', 'coinCode': 'USDT',
                'tradeType': side, 'pageNo': '1', 'pageSize': str(TOP_N),
            }),
            ('POST', f'{BITGET_BASE_URL}/api/v2/p2p/adv/list', {
                'fiatCurrency': 'BOB', 'coinCode': 'USDT',
                'tradeType': side, 'pageNo': 1, 'pageSize': TOP_N,
            }),
            ('GET',  f'{BITGET_BASE_URL}/api/v2/p2p/merchant-ad-list', {
                'fiat': 'BOB', 'side': side, 'currency': 'USDT',
                'page': '1', 'pageSize': str(TOP_N),
            }),
        ]
        for method, url, params_or_body in candidates:
            try:
                if method == 'POST':
                    resp = session.post(url, json=params_or_body, timeout=DEFAULT_TIMEOUT)
                else:
                    resp = session.get(url, params=params_or_body, timeout=DEFAULT_TIMEOUT)

                if resp.status_code in (404, 403, 400):
                    continue

                data = resp.json()
                ads = (
                    data.get('data', {}).get('adList', [])
                    or data.get('data', {}).get('list', [])
                    or data.get('data', [])
                    or data.get('items', [])
                )
                prices = []
                for ad in ads:
                    try:
                        price = float(
                            ad.get('price') or ad.get('adPrice') or
                            ad.get('unitPrice') or 0
                        )
                        if price > 0:
                            prices.append(price)
                    except (TypeError, ValueError):
                        continue
                if prices:
                    return prices
            except Exception as exc:
                log.debug('BITGET_P2P_SIDE_ERROR side=%s url=%s error=%s', side, url, exc)
        return []


class BybitP2PFetcher(BaseFetcher):
    """
    Bybit P2P USDT/BOB.
    GET /v5/p2p/item/online?fiatCurrency=BOB&direction=BUY&tokenId=USDT
    direction=BUY  → user wants to buy USDT → seller ads → sell price
    direction=SELL → user wants to sell USDT → buyer ads → buy price
    """
    source_name = 'BYBIT_P2P'
    market_type = 'paralelo_digital'

    def _fetch(self) -> list[FetchResult]:
        import requests
        from django.utils import timezone

        session = self._get_session()
        fetched_at = timezone.now()

        # BUY direction = merchant selling USDT = what user pays = sell_price
        sell_prices = self._fetch_side(session, 'BUY')
        # SELL direction = merchant buying USDT = what user gets = buy_price
        buy_prices  = self._fetch_side(session, 'SELL')

        if not buy_prices and not sell_prices:
            log.debug('BYBIT_P2P_NO_PRICES — all endpoints failed or unsupported')
            return []

        buy_prices  = sorted(buy_prices)[:TOP_N]
        sell_prices = sorted(sell_prices, reverse=True)[:TOP_N]

        buy_price  = _q(median(buy_prices))  if buy_prices  else None
        sell_price = _q(median(sell_prices)) if sell_prices else None

        if not buy_price:
            buy_price = _q(sell_price * Decimal('0.995')) if sell_price else None
        if not sell_price:
            sell_price = _q(buy_price * Decimal('1.005')) if buy_price else None

        if not buy_price or not sell_price:
            return []

        if buy_price > sell_price:
            sell_price = _q(buy_price * Decimal('1.005'))

        result = FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = (buy_price + sell_price) / Decimal('2'),
            buy_rate      = buy_price,
            sell_rate     = sell_price,
            scale_factor  = 1,
            confidence    = 0.88,
            source_method = 'API',
            source_url    = f'{BYBIT_BASE_URL}/v5/p2p/item/online',
            fetched_at    = fetched_at,
        )
        return [result] if result.is_valid() else []

    def _fetch_side(self, session, direction: str) -> list[float]:
        """
        direction='BUY'  → user buys USDT (merchant sells) → sell prices
        direction='SELL' → user sells USDT (merchant buys) → buy prices
        """
        # Bybit P2P moved from GET /v5/ to POST api2.bybit.com
        # side: '1'=BUY(user buys USDT), '0'=SELL(user sells USDT)
        bybit_side = '1' if direction == 'BUY' else '0'
        candidates = [
            ('POST', 'https://api2.bybit.com/fiat/otc/item/online', {
                'tokenId': 'USDT', 'currencyId': 'BOB',
                'payment': '0', 'side': bybit_side,
                'size': str(TOP_N), 'page': '1', 'amount': '',
            }),
            ('GET', f'{BYBIT_BASE_URL}/v5/p2p/item/online', {
                'fiatCurrency': 'BOB', 'tokenId': 'USDT',
                'side': bybit_side, 'page': '1', 'size': str(TOP_N),
            }),
        ]
        for method, url, params_or_body in candidates:
            try:
                if method == 'POST':
                    resp = session.post(url, json=params_or_body, timeout=DEFAULT_TIMEOUT)
                else:
                    resp = session.get(url, params=params_or_body, timeout=DEFAULT_TIMEOUT)

                if resp.status_code in (404, 403, 400):
                    continue

                data = resp.json()
                items = (
                    data.get('result', {}).get('items', [])
                    or data.get('data', {}).get('list', [])
                    or data.get('data', [])
                    or data.get('items', [])
                )
                prices = []
                for item in items:
                    try:
                        price = float(
                            item.get('price') or item.get('unitPrice') or
                            item.get('priceFloat') or 0
                        )
                        if price > 0:
                            prices.append(price)
                    except (TypeError, ValueError):
                        continue
                if prices:
                    return prices
            except Exception as exc:
                log.debug('BYBIT_P2P_SIDE_ERROR direction=%s url=%s error=%s', direction, url, exc)
        return []


class BinanceP2PFetcher(BaseFetcher):
    """
    Binance P2P USDT/BOB — BaseFetcher wrapper around the existing function.
    Provides consistent interface with the rest of the parallel fetchers.
    """
    source_name = 'BINANCE_P2P'
    market_type = 'paralelo_digital'
    URL = 'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'

    def _fetch(self) -> list[FetchResult]:
        import requests
        from statistics import median as _median
        from django.utils import timezone

        session = self._get_session()
        session.headers.update({'Content-Type': 'application/json'})
        fetched_at = timezone.now()

        sell_prices = self._fetch_side(session, 'SELL')
        buy_prices  = self._fetch_side(session, 'BUY')

        if not buy_prices and not sell_prices:
            return []

        buy_prices  = sorted(buy_prices)[:TOP_N]
        sell_prices = sorted(sell_prices, reverse=True)[:TOP_N]

        buy_price  = _q(_median(buy_prices))  if buy_prices  else None
        sell_price = _q(_median(sell_prices)) if sell_prices else None

        if not buy_price:
            buy_price = _q(sell_price * Decimal('0.995'))
        if not sell_price:
            sell_price = _q(buy_price * Decimal('1.005'))

        if buy_price > sell_price:
            sell_price = _q(buy_price * Decimal('1.005'))

        result = FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = (buy_price + sell_price) / Decimal('2'),
            buy_rate      = buy_price,
            sell_rate     = sell_price,
            scale_factor  = 1,
            confidence    = 0.95,
            source_method = 'API',
            source_url    = self.URL,
            fetched_at    = fetched_at,
        )
        return [result] if result.is_valid() else []

    def _fetch_side(self, session, trade_type: str) -> list[float]:
        try:
            payload = {
                'asset':         'USDT',
                'fiat':          'BOB',
                'merchantCheck': False,
                'page':          1,
                'payTypes':      [],
                'publisherType': None,
                'rows':          TOP_N,
                'tradeType':     trade_type,
            }
            resp = session.post(self.URL, json=payload, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            ads = resp.json().get('data', [])
            prices = []
            for ad in ads:
                try:
                    price = float(ad['adv']['price'])
                    if price > 0:
                        prices.append(price)
                except (KeyError, TypeError, ValueError):
                    continue
            return prices
        except Exception as exc:
            log.debug('BINANCE_P2P_SIDE_ERROR side=%s error=%s', trade_type, exc)
            return []
