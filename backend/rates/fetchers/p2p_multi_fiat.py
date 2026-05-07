"""
Multi-fiat P2P cross-rate fetchers via Binance P2P USDT intermediary.

Formula (casa de cambio perspective — FIAT/BOB expressed as BOB per scale_factor FIAT):
  buy_rate  = (buy_bob_per_usdt  / sell_fiat_per_usdt) * scale_factor
  sell_rate = (sell_bob_per_usdt / buy_fiat_per_usdt)  * scale_factor

  buy_bob  : BUY  tradeType USDT/BOB → house receives BOB, delivers USDT
  sell_bob : SELL tradeType USDT/BOB → user delivers BOB, receives USDT
  buy_fiat : BUY  tradeType USDT/FIAT → house receives FIAT, delivers USDT
  sell_fiat: SELL tradeType USDT/FIAT → user delivers FIAT, receives USDT
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from django.core.cache import cache

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.p2p_multi_fiat')

_URL = 'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'
_Q4  = Decimal('0.0001')
TOP_N = 10

BOB_LO = Decimal('7.0')
BOB_HI = Decimal('16.0')

# fiat → (scale_factor, lo_fiat_per_usdt, hi_fiat_per_usdt, confidence)
_FIAT_CFG: dict[str, tuple[int, Decimal, Decimal, float]] = {
    'ARS': (1000, Decimal('700'),  Decimal('2500'), 0.82),
    'CLP': (1000, Decimal('700'),  Decimal('1400'), 0.80),
    'PEN': (1,    Decimal('3.4'),  Decimal('4.5'),  0.82),
    'BRL': (1,    Decimal('4.5'),  Decimal('7.0'),  0.82),
    'EUR': (1,    Decimal('0.85'), Decimal('1.10'), 0.84),
}


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(_Q4, rounding=ROUND_HALF_UP)


class BinanceCrossRateFetcher(BaseFetcher):
    """
    Binance P2P cross rate: FIAT/BOB via USDT intermediary.
    One instance per fiat currency.
    """
    market_type = 'paralelo_digital'

    def __init__(self, fiat: str) -> None:
        self._fiat = fiat.upper()
        if self._fiat not in _FIAT_CFG:
            raise ValueError(f'BinanceCrossRateFetcher: unsupported fiat={fiat}')
        self.source_name = f'BINANCE_{self._fiat}'

    # ──────────────────────────────────────────────────────────────────────────

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone

        cache_key = f'binance_cross_{self._fiat}'
        if cached := cache.get(cache_key):
            return cached

        session = self._get_session()
        session.headers.update({'Content-Type': 'application/json'})
        fetched_at = timezone.now()

        # BOB reference
        buy_bob_list  = self._p2p_side(session, 'BUY',  'BOB')
        sell_bob_list = self._p2p_side(session, 'SELL', 'BOB')
        if not buy_bob_list or not sell_bob_list:
            log.debug('BINANCE_CROSS_%s no BOB data', self._fiat)
            return []

        buy_bob  = _q(median(buy_bob_list[:TOP_N]))
        sell_bob = _q(median(sell_bob_list[:TOP_N]))
        if not (BOB_LO <= buy_bob <= BOB_HI and BOB_LO <= sell_bob <= BOB_HI):
            log.debug('BINANCE_CROSS_%s BOB out of range buy=%s sell=%s', self._fiat, buy_bob, sell_bob)
            return []

        # Fiat reference
        scale, lo, hi, conf = _FIAT_CFG[self._fiat]
        buy_fiat_list  = self._p2p_side(session, 'BUY',  self._fiat)
        sell_fiat_list = self._p2p_side(session, 'SELL', self._fiat)
        if not buy_fiat_list or not sell_fiat_list:
            log.debug('BINANCE_CROSS_%s no fiat data', self._fiat)
            return []

        buy_fiat  = _q(median(buy_fiat_list[:TOP_N]))
        sell_fiat = _q(median(sell_fiat_list[:TOP_N]))
        if not (lo <= buy_fiat <= hi and lo <= sell_fiat <= hi):
            log.debug('BINANCE_CROSS_%s fiat out of range buy=%s sell=%s lo=%s hi=%s',
                      self._fiat, buy_fiat, sell_fiat, lo, hi)
            return []

        buy_rate  = _q((buy_bob  / sell_fiat) * scale)
        sell_rate = _q((sell_bob / buy_fiat)  * scale)

        if buy_rate <= 0 or sell_rate <= 0:
            return []
        if buy_rate > sell_rate:
            sell_rate = _q(buy_rate * Decimal('1.005'))

        result = FetchResult(
            currency_code = self._fiat,
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = (buy_rate + sell_rate) / Decimal('2'),
            buy_rate      = buy_rate,
            sell_rate     = sell_rate,
            scale_factor  = scale,
            confidence    = conf,
            source_method = 'API',
            source_url    = _URL,
            fetched_at    = fetched_at,
        )
        results = [result] if result.is_valid() else []
        if results:
            cache.set(cache_key, results, 300)
        return results

    def _p2p_side(self, session, trade_type: str, fiat: str) -> list[float]:
        try:
            payload = {
                'asset':         'USDT',
                'fiat':          fiat,
                'merchantCheck': False,
                'page':          1,
                'payTypes':      [],
                'publisherType': None,
                'rows':          TOP_N,
                'tradeType':     trade_type,
            }
            resp = session.post(_URL, json=payload, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            prices = []
            for ad in resp.json().get('data', []):
                try:
                    p = float(ad['adv']['price'])
                    if p > 0:
                        prices.append(p)
                except (KeyError, TypeError, ValueError):
                    pass
            return prices
        except Exception as exc:
            log.debug('BINANCE_CROSS_%s side=%s fiat=%s error=%s', self._fiat, trade_type, fiat, exc)
            return []


def all_binance_cross_fetchers() -> list[BinanceCrossRateFetcher]:
    """Returns one fetcher per supported fiat currency."""
    return [BinanceCrossRateFetcher(fiat) for fiat in _FIAT_CFG]
