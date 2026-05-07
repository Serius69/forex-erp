"""
DolarBlueBolivia.click — adapta el scraper existente a AbstractRateFetcher.

El scraper original está en rates/scrapers/dolar_blue_bolivia.py.
Este módulo es solo un adapter — no reescribe lógica.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as tz
from decimal import Decimal

from rates.integrations.base import AbstractRateFetcher
from rates.schemas import NormalizedRate

log = logging.getLogger('kapitalya.integrations.dolarbluebolivia')


class DolarBlueBoliviaIntFetcher(AbstractRateFetcher):
    id_fuente       = 'dolarbluebolivia_click'
    tipo_fuente     = 'AGREGADOR'
    pares_soportados = [('USD', 'BOB')]

    def fetch(self) -> list[NormalizedRate]:
        from rates.scrapers.dolar_blue_bolivia import scrape_parallel_rate
        now = datetime.now(tz.utc)

        data = scrape_parallel_rate()

        mid  = data.get('mid')
        buy  = data.get('buy')
        sell = data.get('sell')

        if not mid and not buy:
            return []

        precio_compra = buy  or mid
        precio_venta  = sell or mid

        if precio_compra and precio_venta and precio_compra > precio_venta:
            precio_compra = precio_venta = (precio_compra + precio_venta) / Decimal('2')

        return [NormalizedRate(
            moneda_base      = 'USD',
            moneda_cotizada  = 'BOB',
            precio           = precio_compra or mid,
            precio_compra    = precio_compra,
            precio_venta     = precio_venta,
            spread_pct       = None,
            fuente           = self.id_fuente,
            tipo_fuente      = self.tipo_fuente,
            timestamp        = now,
            payload_raw      = {k: str(v) for k, v in data.items() if v is not None},
            confianza        = 82,
            es_valido        = bool(mid or buy),
        )]
