"""
DolarApi Bolivia fetchers — cotizaciones USD/BOB.

Endpoints:
  oficial  → GET https://bo.dolarapi.com/v1/dolares/oficial
             {"compra": 6.96, "venta": 6.97, "fechaActualizacion": "..."}
  lista    → GET https://bo.dolarapi.com/v1/dolares
             [{"nombre": "oficial", "compra": ..., "venta": ...}, ...]

Estos son tipos de cambio oficiales/no-paralelos del BCB.
Se registran con market_type='official' para comparación referencial.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django.utils import timezone

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT, apply_min_spread

log = logging.getLogger('kapitalya.rates.fetcher.dolarapi_bolivia')

_Q4     = Decimal('0.0001')
_BOB_LO = Decimal('5.0')   # official rate range (lower bound for BCB)
_BOB_HI = Decimal('16.0')


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(_Q4, rounding=ROUND_HALF_UP)


def _to_dec(val, lo: Decimal = _BOB_LO, hi: Decimal = _BOB_HI) -> Decimal | None:
    try:
        d = Decimal(str(val))
        if lo <= d <= hi:
            return d
    except (InvalidOperation, TypeError):
        pass
    return None


class DolarApiBoliviaOficialFetcher(BaseFetcher):
    """
    GET https://bo.dolarapi.com/v1/dolares/oficial
    Cotización oficial USD/BOB del BCB.
    """
    source_name = 'DOLARAPI_OFICIAL'
    market_type = 'official'
    _URL = 'https://bo.dolarapi.com/v1/dolares/oficial'

    def _fetch(self) -> list[FetchResult]:
        session    = self._get_session()
        fetched_at = timezone.now()

        resp = session.get(self._URL, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        buy  = _to_dec(data.get('compra') or data.get('buy')  or data.get('purchase'))
        sell = _to_dec(data.get('venta')  or data.get('sell') or data.get('sale'))

        if buy and sell and buy < sell:
            pass
        elif buy and sell and buy >= sell:
            buy, sell = min(buy, sell), max(buy, sell)
        elif buy:
            buy, sell = apply_min_spread(buy)
        elif sell:
            buy, sell = apply_min_spread(sell)
        else:
            log.debug('DOLARAPI_OFICIAL no valid prices in response')
            return []

        buy  = _q(buy)
        sell = _q(sell)

        r = FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = _q((buy + sell) / Decimal('2')),
            buy_rate      = buy,
            sell_rate     = sell,
            scale_factor  = 1,
            confidence    = 0.95,
            source_method = 'API',
            source_url    = self._URL,
            fetched_at    = fetched_at,
            raw_data      = {'raw': data},
        )
        return [r] if r.is_valid() else []


class DolarApiBoliviaListFetcher(BaseFetcher):
    """
    GET https://bo.dolarapi.com/v1/dolares
    Lista de tipos de cambio USD/BOB (oficial, tarjeta, etc.).
    Devuelve un FetchResult por cada tipo encontrado.
    """
    source_name = 'DOLARAPI_LISTA'
    market_type = 'official'
    _URL = 'https://bo.dolarapi.com/v1/dolares'

    # Mapeo nombre → source_name + market_type
    _TYPE_MAP: dict[str, tuple[str, str]] = {
        'oficial':  ('DOLARAPI_OFICIAL',  'official'),
        'tarjeta':  ('DOLARAPI_TARJETA',  'official'),
        'blue':     ('DOLARAPI_BLUE',     'paralelo_digital'),
        'paralelo': ('DOLARAPI_PARALELO', 'paralelo_digital'),
        'informal': ('DOLARAPI_INFORMAL', 'paralelo_digital'),
    }

    def _fetch(self) -> list[FetchResult]:
        session    = self._get_session()
        fetched_at = timezone.now()

        resp = session.get(self._URL, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        items = resp.json()

        if not isinstance(items, list):
            # Some endpoints return a single object
            items = [items]

        results: list[FetchResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            nombre = str(item.get('nombre', item.get('name', item.get('tipo', '')))).lower()
            src_name, mtype = self._TYPE_MAP.get(nombre, (f'DOLARAPI_{nombre.upper()}', 'official'))

            buy  = _to_dec(item.get('compra') or item.get('buy'))
            sell = _to_dec(item.get('venta')  or item.get('sell'))

            if buy and sell and buy < sell:
                pass
            elif buy and sell and buy >= sell:
                buy, sell = min(buy, sell), max(buy, sell)
            elif buy:
                buy, sell = apply_min_spread(buy)
            elif sell:
                buy, sell = apply_min_spread(sell)
            else:
                continue

            buy  = _q(buy)
            sell = _q(sell)

            r = FetchResult(
                currency_code = 'USD',
                market_type   = mtype,
                source_name   = src_name,
                official_rate = _q((buy + sell) / Decimal('2')),
                buy_rate      = buy,
                sell_rate     = sell,
                scale_factor  = 1,
                confidence    = 0.95 if mtype == 'official' else 0.80,
                source_method = 'API',
                source_url    = self._URL,
                fetched_at    = fetched_at,
                raw_data      = {'nombre': nombre},
            )
            if r.is_valid():
                results.append(r)

        return results
