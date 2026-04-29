"""
Eldorado.io exchange rate fetcher.

GET https://api.eldorado.io/api/v1/rates
Headers: Authorization: Bearer <ELDORADO_TOKEN>

Returns rates for multiple currencies vs BOB.
"""
from __future__ import annotations
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.eldorado')

ELDORADO_URL = 'https://api.eldorado.io/api/v1/rates'

# BCB reference per currency (used as official_rate field only)
BCB_REF = {
    'USD': Decimal('6.96'),  'EUR': Decimal('7.52'),
    'BRL': Decimal('1.22'),  'PEN': Decimal('1.85'),
    'CLP': Decimal('0.0076'),'ARS': Decimal('0.007'),
}
SCALE_FACTORS = {'ARS': 1000, 'CLP': 1000}

_Q4 = Decimal('0.0001')


def _q(val) -> Decimal:
    return Decimal(str(val)).quantize(_Q4, rounding=ROUND_HALF_UP)


class EldoradoFetcher(BaseFetcher):
    """
    Fetches multi-currency rates from Eldorado.io via authenticated API.
    Token is read from settings.ELDORADO_API_TOKEN or env var.
    """
    source_name = 'ELDORADO'
    market_type = 'paralelo_digital'

    def _get_token(self) -> str | None:
        return getattr(settings, 'ELDORADO_API_TOKEN', None)

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone

        token = self._get_token()
        if not token:
            log.warning('ELDORADO_NO_TOKEN — skipping fetcher')
            return []

        session = self._get_session()
        session.headers.update({
            'Authorization': f'Bearer {token}',
            'Accept':        'application/json',
        })

        fetched_at = timezone.now()

        try:
            resp = session.get(ELDORADO_URL, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error('ELDORADO_FETCH_ERROR %s', exc)
            return []

        return self._parse(data, fetched_at)

    def _parse(self, data: dict | list, fetched_at) -> list[FetchResult]:
        results = []

        # Normalize to a list of rate items
        items = (
            data.get('rates', data.get('data', data))
            if isinstance(data, dict) else data
        )
        if not isinstance(items, list):
            items = [items]

        for item in items:
            if not isinstance(item, dict):
                continue

            # Field name variants from Eldorado
            code = str(
                item.get('currency') or item.get('code') or item.get('asset') or ''
            ).upper()

            if code not in BCB_REF:
                continue

            try:
                buy  = _q(item.get('buy')    or item.get('compra') or item.get('bid') or 0)
                sell = _q(item.get('sell')   or item.get('venta')  or item.get('ask') or 0)
                ref  = BCB_REF[code]
                scale = SCALE_FACTORS.get(code, 1)

                # Eldorado may return per-unit rates — scale if needed
                buy_scaled  = buy  * Decimal(str(scale)) if scale > 1 else buy
                sell_scaled = sell * Decimal(str(scale)) if scale > 1 else sell

                result = FetchResult(
                    currency_code = code,
                    market_type   = self.market_type,
                    source_name   = self.source_name,
                    official_rate = ref,
                    buy_rate      = buy_scaled,
                    sell_rate     = sell_scaled,
                    scale_factor  = scale,
                    confidence    = 0.90,
                    source_method = 'API',
                    source_url    = ELDORADO_URL,
                    fetched_at    = fetched_at,
                )
                if result.is_valid():
                    results.append(result)

            except Exception as exc:
                log.debug('ELDORADO_ITEM_ERROR code=%s error=%s', code, exc)

        log.info('ELDORADO_PARSED results=%d', len(results))
        return results
