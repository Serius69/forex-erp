"""
DólaresABolivianos fetchers — agregador USDT/BOB boliviano.

Dos endpoints:
  1. LLM summary  → https://www.dolaresabolivianos.com/api/llm.json
     JSON con mejor_compra/mejor_venta/promedio, actualizado cada ~30 s.
  2. Last record  → https://api.dolaresabolivianos.com/api/v1/data/last
     Último registro puntual con precio + fuente + timestamp.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django.utils import timezone

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT, apply_min_spread

log = logging.getLogger('kapitalya.rates.fetcher.dolaresabolivianos')

_Q4 = Decimal('0.0001')
_BOB_LO = Decimal('7.0')
_BOB_HI = Decimal('16.0')


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(_Q4, rounding=ROUND_HALF_UP)


def _to_dec(val) -> Decimal | None:
    try:
        d = Decimal(str(val))
        if _BOB_LO <= d <= _BOB_HI:
            return d
    except (InvalidOperation, TypeError):
        pass
    return None


class DolaresABolivianosLLMFetcher(BaseFetcher):
    """
    https://www.dolaresabolivianos.com/api/llm.json
    Devuelve el resumen de mercado USDT/BOB con mejor compra y venta.
    """
    source_name = 'DOLARESABOLIVIANOS_LLM'
    market_type = 'paralelo_digital'
    _URL = 'https://www.dolaresabolivianos.com/api/llm.json'

    def _fetch(self) -> list[FetchResult]:
        session    = self._get_session()
        fetched_at = timezone.now()

        resp = session.get(self._URL, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        # Try multiple field name conventions
        buy = (
            _to_dec(data.get('mejor_precio_compra'))
            or _to_dec(data.get('mejor_compra'))
            or _to_dec(data.get('compra'))
            or _to_dec(data.get('bid'))
        )
        sell = (
            _to_dec(data.get('mejor_precio_venta'))
            or _to_dec(data.get('mejor_venta'))
            or _to_dec(data.get('venta'))
            or _to_dec(data.get('ask'))
        )
        mid = (
            _to_dec(data.get('promedio'))
            or _to_dec(data.get('precio_promedio'))
            or _to_dec(data.get('mediana'))
            or _to_dec(data.get('precio'))
        )

        if buy and sell and buy < sell:
            pass  # real spread available
        elif buy and sell and buy >= sell:
            buy, sell = min(buy, sell), max(buy, sell)
        elif mid:
            buy, sell = apply_min_spread(mid)
        elif buy:
            _, sell = apply_min_spread(buy)
        elif sell:
            buy, _ = apply_min_spread(sell)
        else:
            log.debug('DOLARESABOLIVIANOS_LLM no valid price in response')
            return []

        buy  = _q(buy)
        sell = _q(sell)
        mid_val = _q((buy + sell) / Decimal('2'))

        r = FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = mid_val,
            buy_rate      = buy,
            sell_rate     = sell,
            scale_factor  = 1,
            confidence    = 0.90,
            source_method = 'API',
            source_url    = self._URL,
            fetched_at    = fetched_at,
            raw_data      = {'raw': data},
        )
        return [r] if r.is_valid() else []


class DolaresABolivianosLastFetcher(BaseFetcher):
    """
    https://api.dolaresabolivianos.com/api/v1/data/last
    Último registro puntual USDT/BOB.
    """
    source_name = 'DOLARESABOLIVIANOS_LAST'
    market_type = 'paralelo_digital'
    _URL = 'https://api.dolaresabolivianos.com/api/v1/data/last'

    def _fetch(self) -> list[FetchResult]:
        session    = self._get_session()
        fetched_at = timezone.now()

        resp = session.get(self._URL, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        # Single-price endpoint — try multiple field names
        price = (
            _to_dec(data.get('precio'))
            or _to_dec(data.get('price'))
            or _to_dec(data.get('rate'))
            or _to_dec(data.get('valor'))
        )
        if not price:
            log.debug('DOLARESABOLIVIANOS_LAST no valid price in response')
            return []

        buy, sell = apply_min_spread(price)
        buy  = _q(buy)
        sell = _q(sell)

        r = FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = _q(price),
            buy_rate      = buy,
            sell_rate     = sell,
            scale_factor  = 1,
            confidence    = 0.88,
            source_method = 'API',
            source_url    = self._URL,
            fetched_at    = fetched_at,
            raw_data      = {'raw': data},
        )
        return [r] if r.is_valid() else []
