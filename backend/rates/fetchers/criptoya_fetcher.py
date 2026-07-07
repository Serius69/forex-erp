"""
CriptoYa fetchers — agregador Latam de precios USDT.

Endpoint patrón: https://criptoya.com/api/usdt/{fiat}/1
Respuesta:
  {
    "exchange_slug": {"totalBid": <float>, "totalAsk": <float>, "time": <unix_ts>},
    ...
  }

  totalBid = precio más alto que alguien paga por USDT (bid de mercado)
  totalAsk = precio más bajo al que alguien vende USDT (ask de mercado)

  Para Kapitalya (casa de cambio, perspectiva FIAT/BOB):
    buy_rate  = totalBid  (compramos USD/USDT al precio que el mercado paga = bid)
    sell_rate = totalAsk  (vendemos USD/USDT al precio que el mercado pide = ask)

Cross-rate formula (FIAT/BOB via USDT):
  buy_FIAT_BOB  = (buy_BOB / sell_FIAT) * scale
  sell_FIAT_BOB = (sell_BOB / buy_FIAT) * scale
"""
from __future__ import annotations

import logging
import time as _time
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from statistics import median

from django.core.cache import cache
from django.utils import timezone

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT, apply_min_spread

log = logging.getLogger('kapitalya.rates.fetcher.criptoya')

_Q4     = Decimal('0.0001')
_BOB_LO = Decimal('7.0')
_BOB_HI = Decimal('16.0')
_STALE  = 300  # ignore quotes older than 5 min (unix seconds)

# fiat → (scale_factor, lo_fiat_per_usdt, hi_fiat_per_usdt, confidence)
_FIAT_CFG: dict[str, tuple[int, Decimal, Decimal, float]] = {
    'ARS': (1000, Decimal('700'),  Decimal('3000'), 0.82),
    'CLP': (1000, Decimal('700'),  Decimal('1400'), 0.80),
    'PEN': (1,    Decimal('3.0'),  Decimal('5.0'),  0.82),
    'BRL': (1,    Decimal('4.0'),  Decimal('8.0'),  0.82),
}


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(_Q4, rounding=ROUND_HALF_UP)


def _to_dec(val, lo: Decimal, hi: Decimal) -> Decimal | None:
    try:
        d = Decimal(str(val))
        if lo <= d <= hi:
            return d
    except (InvalidOperation, TypeError):
        pass
    return None


def _best_bid_ask(
    data: dict,
    lo: Decimal,
    hi: Decimal,
    now_ts: float,
) -> tuple[Decimal | None, Decimal | None]:
    """
    Returns (best_bid, best_ask) across all exchanges in the CriptoYa response.
    Filters out stale quotes (> _STALE seconds old).
    best_bid = highest bid (what the market pays to buy USDT)
    best_ask = lowest ask (what the market asks to sell USDT)
    """
    bids: list[float] = []
    asks: list[float] = []

    for slug, entry in data.items():
        if not isinstance(entry, dict):
            continue
        ts = entry.get('time', now_ts)
        if (now_ts - ts) > _STALE:
            continue
        bid = entry.get('totalBid') or entry.get('bid') or entry.get('compra')
        ask = entry.get('totalAsk') or entry.get('ask') or entry.get('venta')
        if bid and _to_dec(bid, lo, hi):
            bids.append(float(bid))
        if ask and _to_dec(ask, lo, hi):
            asks.append(float(ask))

    best_bid = _to_dec(max(bids), lo, hi) if bids else None
    best_ask = _to_dec(min(asks), lo, hi) if asks else None
    return best_bid, best_ask


class CriptoYaBOBFetcher(BaseFetcher):
    """
    CriptoYa USDT/BOB → USD/BOB (mercado paralelo boliviano).
    GET https://criptoya.com/api/usdt/bob/1
    """
    source_name = 'CRIPTOYA_BOB'
    market_type = 'paralelo_digital'
    _URL = 'https://criptoya.com/api/usdt/bob/1'

    def _fetch(self) -> list[FetchResult]:
        session    = self._get_session()
        fetched_at = timezone.now()
        now_ts     = _time.time()

        resp = session.get(self._URL, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        bid, ask = _best_bid_ask(data, _BOB_LO, _BOB_HI, now_ts)

        if bid and ask and bid < ask:
            buy, sell = _q(bid), _q(ask)
        elif bid and ask:
            buy, sell = min(_q(bid), _q(ask)), max(_q(bid), _q(ask))
        elif bid:
            buy, sell = apply_min_spread(_q(bid))
        elif ask:
            buy, sell = apply_min_spread(_q(ask))
        else:
            log.debug('CRIPTOYA_BOB no valid prices')
            return []

        mid = _q((buy + sell) / Decimal('2'))
        # Cache for cross-rate fetchers (5 min)
        cache.set('criptoya_bob_rates', {'buy': buy, 'sell': sell, 'mid': mid}, 300)

        r = FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = mid,
            buy_rate      = buy,
            sell_rate     = sell,
            scale_factor  = 1,
            confidence    = 0.88,
            source_method = 'API',
            source_url    = self._URL,
            fetched_at    = fetched_at,
            raw_data      = {'exchanges_count': len(data)},
        )
        return [r] if r.is_valid() else []


class CriptoYaCrossRateFetcher(BaseFetcher):
    """
    CriptoYa cross-rate: FIAT/BOB via USDT intermediary.
    GET https://criptoya.com/api/usdt/{fiat}/1

    Fórmula (misma que p2p_multi_fiat.py):
      buy_FIAT_BOB  = (buy_BOB  / sell_FIAT) * scale
      sell_FIAT_BOB = (sell_BOB / buy_FIAT)  * scale
    """
    market_type = 'paralelo_digital'

    def __init__(self, fiat: str) -> None:
        self._fiat = fiat.upper()
        if self._fiat not in _FIAT_CFG:
            raise ValueError(f'CriptoYaCrossRateFetcher: unsupported fiat={fiat}')
        self.source_name = f'CRIPTOYA_{self._fiat}'

    def _fetch(self) -> list[FetchResult]:
        session    = self._get_session()
        fetched_at = timezone.now()
        now_ts     = _time.time()

        scale, lo_fiat, hi_fiat, conf = _FIAT_CFG[self._fiat]

        # 1. Get USDT/BOB reference
        bob_cached = cache.get('criptoya_bob_rates')
        if bob_cached:
            buy_bob  = bob_cached['buy']
            sell_bob = bob_cached['sell']
        else:
            # Fetch BOB inline
            try:
                r = session.get('https://criptoya.com/api/usdt/bob/1', timeout=DEFAULT_TIMEOUT)
                r.raise_for_status()
                bid_bob, ask_bob = _best_bid_ask(r.json(), _BOB_LO, _BOB_HI, now_ts)
                if not bid_bob or not ask_bob:
                    log.debug('CRIPTOYA_%s no BOB reference', self._fiat)
                    return []
                buy_bob  = _q(bid_bob)
                sell_bob = _q(ask_bob)
                if buy_bob >= sell_bob:
                    buy_bob, sell_bob = min(buy_bob, sell_bob), max(buy_bob, sell_bob)
            except Exception as exc:
                log.debug('CRIPTOYA_%s BOB fetch error: %s', self._fiat, exc)
                return []

        # 2. Get USDT/FIAT rates
        url = f'https://criptoya.com/api/usdt/{self._fiat.lower()}/1'
        resp = session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        bid_fiat, ask_fiat = _best_bid_ask(data, lo_fiat, hi_fiat, now_ts)
        if not bid_fiat or not ask_fiat:
            log.debug('CRIPTOYA_%s no fiat prices', self._fiat)
            return []

        buy_fiat  = _q(bid_fiat)
        sell_fiat = _q(ask_fiat)
        if buy_fiat <= 0 or sell_fiat <= 0:
            return []

        # 3. Cross-rate computation
        buy_rate  = _q((buy_bob  / sell_fiat) * scale)
        sell_rate = _q((sell_bob / buy_fiat)  * scale)

        if buy_rate <= 0 or sell_rate <= 0:
            return []
        if buy_rate >= sell_rate:
            buy_rate, sell_rate = min(buy_rate, sell_rate), max(buy_rate, sell_rate)
            if buy_rate == sell_rate:
                buy_rate, sell_rate = apply_min_spread(buy_rate)

        mid = _q((buy_rate + sell_rate) / Decimal('2'))

        r = FetchResult(
            currency_code = self._fiat,
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = mid,
            buy_rate      = buy_rate,
            sell_rate     = sell_rate,
            scale_factor  = scale,
            confidence    = conf,
            source_method = 'API',
            source_url    = url,
            fetched_at    = fetched_at,
            raw_data      = {
                'buy_bob': str(buy_bob), 'sell_bob': str(sell_bob),
                'buy_fiat': str(buy_fiat), 'sell_fiat': str(sell_fiat),
            },
        )
        return [r] if r.is_valid() else []


def all_criptoya_cross_fetchers() -> list[CriptoYaCrossRateFetcher]:
    return [CriptoYaCrossRateFetcher(fiat) for fiat in _FIAT_CFG]
