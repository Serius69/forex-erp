"""
Eldorado.io — wrapper para la capa integrations/.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as tz

from rates.integrations.base import AbstractRateFetcher
from rates.schemas import NormalizedRate

log = logging.getLogger('kapitalya.integrations.eldorado')


class EldoradoIntFetcher(AbstractRateFetcher):
    id_fuente       = 'eldorado'
    tipo_fuente     = 'EXCHANGE'
    pares_soportados = [
        ('USD', 'BOB'), ('EUR', 'BOB'), ('BRL', 'BOB'),
        ('PEN', 'BOB'), ('ARS', 'BOB'), ('CLP', 'BOB'),
    ]

    def fetch(self) -> list[NormalizedRate]:
        from rates.fetchers.eldorado_fetcher import EldoradoFetcher
        legacy = EldoradoFetcher()
        results = legacy.fetch()
        now = datetime.now(tz.utc)
        out: list[NormalizedRate] = []
        for r in results:
            out.append(NormalizedRate(
                moneda_base      = r.currency_code,
                moneda_cotizada  = 'BOB',
                precio           = r.buy_rate,
                precio_compra    = r.buy_rate,
                precio_venta     = r.sell_rate,
                spread_pct       = None,
                fuente           = self.id_fuente,
                tipo_fuente      = self.tipo_fuente,
                timestamp        = getattr(r, 'fetched_at', None) or now,
                payload_raw      = r.raw_data,
                confianza        = int(r.confidence * 100),
                es_valido        = r.is_valid(),
            ))
        return out
