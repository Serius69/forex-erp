"""
Reference rate fetchers — BCB cucu.bo API and BCP Bolivia.

These rates are for DISPLAY AND ANALYTICS ONLY.
NEVER use these for trading operations.

BCB API: GET https://bcb.cucu.bo/api/v1/tc/usd
Response: {"compra": 6.90, "venta": 6.96}

BCP API: POST https://www.bcp.com.bo/api/Bcp/ExchangeRate
Body: {"country": "USA"}
"""
from __future__ import annotations
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

log = logging.getLogger('kapitalya.rates.fetcher.reference')

_Q2 = Decimal('0.01')


def _q2(val) -> Decimal:
    return Decimal(str(val)).quantize(_Q2, rounding=ROUND_HALF_UP)


class BCBCucuFetcher:
    """
    Fetches USD/BOB reference from the BCB cucu.bo JSON API.
    Returns (buy, sell) in BOB, rounded to 2 decimals.
    """
    URL = 'https://bcb.cucu.bo/api/v1/tc/usd'
    TIMEOUT = 10

    def fetch(self) -> Optional[dict]:
        """
        Returns:
            {'currency': 'USD', 'reference_buy': Decimal, 'reference_sell': Decimal,
             'source': 'BCB', 'raw': dict}
        or None on failure.
        """
        import requests
        try:
            resp = requests.get(self.URL, timeout=self.TIMEOUT, headers={
                'Accept': 'application/json',
                'User-Agent': 'KapitalyaERP/1.0',
            })
            resp.raise_for_status()
            data = resp.json()

            buy  = _q2(data.get('compra') or data.get('buy')  or data.get('compra_bs'))
            sell = _q2(data.get('venta')  or data.get('sell') or data.get('venta_bs'))

            if buy <= 0 or sell <= 0:
                log.warning('BCB_CUCU_INVALID buy=%s sell=%s', buy, sell)
                return None

            log.info('BCB_CUCU_FETCHED buy=%s sell=%s', buy, sell)
            return {
                'currency':      'USD',
                'reference_buy':  buy,
                'reference_sell': sell,
                'source':         'BCB',
                'raw':            data,
            }

        except Exception as exc:
            log.error('BCB_CUCU_ERROR %s', exc)
            return None


class BCPBoliviaReferenceFetcher:
    """
    Fetches USD/BOB reference from BCP Bolivia.
    POST https://www.bcp.com.bo/api/Bcp/ExchangeRate
    Body: {"country": "USA"}
    """
    URL = 'https://www.bcp.com.bo/api/Bcp/ExchangeRate'
    TIMEOUT = 12

    def fetch(self) -> Optional[dict]:
        import requests
        try:
            resp = requests.post(
                self.URL,
                json={'country': 'USA'},
                timeout=self.TIMEOUT,
                headers={
                    'Content-Type': 'application/json',
                    'Accept':       'application/json',
                    'User-Agent':   'KapitalyaERP/1.0',
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # BCP response structure varies — try known field names
            buy  = None
            sell = None
            if isinstance(data, dict):
                buy  = (data.get('compra')  or data.get('buyRate')  or
                        data.get('buy')     or data.get('tipoCambioCompra'))
                sell = (data.get('venta')   or data.get('sellRate') or
                        data.get('sell')    or data.get('tipoCambioVenta'))
            elif isinstance(data, list) and data:
                item = data[0]
                buy  = item.get('compra') or item.get('buyRate')
                sell = item.get('venta')  or item.get('sellRate')

            if not buy or not sell:
                log.warning('BCP_REF_NO_RATE data=%s', data)
                return None

            buy  = _q2(buy)
            sell = _q2(sell)

            if buy <= 0 or sell <= 0:
                return None

            log.info('BCP_REF_FETCHED buy=%s sell=%s', buy, sell)
            return {
                'currency':      'USD',
                'reference_buy':  buy,
                'reference_sell': sell,
                'source':         'BCP',
                'raw':            data if isinstance(data, dict) else {'list': data},
            }

        except Exception as exc:
            log.error('BCP_REF_ERROR %s', exc)
            return None


def fetch_and_save_reference_rates() -> list[dict]:
    """
    Fetches BCB + BCP reference rates and persists them to ReferenceRate model.
    Returns list of saved records (as dicts).

    ⚠️  DISPLAY ONLY — not for trading.
    """
    from django.utils import timezone
    from rates.models import ReferenceRate

    fetchers = [BCBCucuFetcher(), BCPBoliviaReferenceFetcher()]
    saved: list[dict] = []

    for fetcher in fetchers:
        result = fetcher.fetch()
        if not result:
            continue
        try:
            obj = ReferenceRate.objects.create(
                currency        = result['currency'],
                reference_buy   = result['reference_buy'],
                reference_sell  = result['reference_sell'],
                source          = result['source'],
                raw_response    = result.get('raw', {}),
            )
            saved.append({
                'id':            obj.pk,
                'currency':      obj.currency,
                'reference_buy': float(obj.reference_buy),
                'reference_sell':float(obj.reference_sell),
                'source':        obj.source,
                'timestamp':     obj.timestamp.isoformat(),
            })
            log.info(
                'REFERENCE_SAVED source=%s currency=%s buy=%s sell=%s',
                obj.source, obj.currency, obj.reference_buy, obj.reference_sell,
            )
        except Exception as exc:
            log.error('REFERENCE_SAVE_ERROR source=%s error=%s', result.get('source'), exc)

    return saved


def get_latest_reference(currency: str = 'USD') -> dict | None:
    """
    Returns the latest reference rate dict from any source.
    Prefers BCB over BCP.
    """
    from rates.models import ReferenceRate
    try:
        for source in ('BCB', 'BCP'):
            obj = ReferenceRate.objects.filter(
                currency=currency.upper(), source=source
            ).first()
            if obj:
                return {
                    'currency':      obj.currency,
                    'reference_buy': float(obj.reference_buy),
                    'reference_sell':float(obj.reference_sell),
                    'source':        obj.source,
                    'timestamp':     obj.timestamp.isoformat(),
                    'label':         'Solo referencia - no usado para operaciones',
                }
    except Exception as exc:
        log.error('GET_LATEST_REFERENCE_ERROR %s', exc)
    return None
