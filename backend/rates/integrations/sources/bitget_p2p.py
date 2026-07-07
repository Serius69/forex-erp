"""
Bitget P2P — wrapper para la capa integrations/.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as tz

from rates.integrations.base import AbstractRateFetcher
from rates.schemas import NormalizedRate

log = logging.getLogger('kapitalya.integrations.bitget_p2p')


class BitgetP2PIntFetcher(AbstractRateFetcher):
    id_fuente       = 'bitget_p2p'
    tipo_fuente     = 'P2P'
    pares_soportados = [('USD', 'BOB')]

    def fetch(self) -> list[NormalizedRate]:
        from rates.fetchers.p2p_exchanges import BitgetP2PFetcher
        legacy = BitgetP2PFetcher()
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
