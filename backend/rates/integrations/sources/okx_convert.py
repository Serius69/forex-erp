"""
OKX Convert — tasas de conversión para USDT→fiat.

API pública: GET https://www.okx.com/api/v5/market/ticker?instId=USDT-BOB
(OKX no tiene BOB directamente — usamos USDT/USD y cruzamos con BOB)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as tz
from decimal import Decimal

from rates.integrations.base import AbstractRateFetcher
from rates.schemas import NormalizedRate

log = logging.getLogger('kapitalya.integrations.okx_convert')

OKX_CONVERT_URL = 'https://www.okx.com/api/v5/asset/convert/currencies'
OKX_PRICE_URL   = 'https://www.okx.com/api/v5/market/ticker'

FIATS = ['BOB']   # OKX soporta muy pocos fiat LatAm — mantenemos como fallback


class OKXConvertFetcher(AbstractRateFetcher):
    id_fuente       = 'okx_convert'
    tipo_fuente     = 'EXCHANGE'
    pares_soportados = [('USD', 'BOB')]

    def fetch(self) -> list[NormalizedRate]:
        """
        OKX no tiene USDT/BOB directo. Intentamos el endpoint de convert
        y si falla retornamos lista vacía sin marcar revisión.
        """
        session = self._get_session()
        now     = datetime.now(tz.utc)
        results: list[NormalizedRate] = []

        for fiat in FIATS:
            try:
                # Intentar GET convert-estimate para USDT → fiat
                resp = session.get(
                    'https://www.okx.com/api/v5/asset/convert/estimate-quote',
                    params={
                        'baseCcy':  'USDT',
                        'quoteCcy': fiat,
                        'side':     'sell',
                        'rfqSz':    '100',
                        'rfqSzCcy': 'USDT',
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                quote = data.get('data', [{}])[0]
                price_str = quote.get('quotePrice') or quote.get('estFillPx')
                if not price_str:
                    continue

                price = self._to_decimal(price_str)
                if price <= 0:
                    continue

                results.append(NormalizedRate(
                    moneda_base      = 'USD',
                    moneda_cotizada  = 'BOB',
                    precio           = price,
                    precio_compra    = price * Decimal('0.998'),
                    precio_venta     = price * Decimal('1.002'),
                    spread_pct       = None,
                    fuente           = self.id_fuente,
                    tipo_fuente      = self.tipo_fuente,
                    timestamp        = now,
                    payload_raw      = quote,
                    confianza        = 78,
                    es_valido        = True,
                ))

            except Exception as exc:
                log.debug('OKX_CONVERT fiat=%s error=%s', fiat, exc)

        return results
