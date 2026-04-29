"""
SaldoAR fetcher — ARS/BOB reference rate.

GET https://api.saldo.com.ar/json/rates/banco/banco_ar_usd

Returns ARS/USD rates which we cross-rate to ARS/BOB using USD/BOB parallel price.
"""
from __future__ import annotations
import logging
from decimal import Decimal, ROUND_HALF_UP

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.saldoar')

SALDOAR_URL  = 'https://api.saldo.com.ar/json/rates/banco/banco_ar_usd'
ARS_SCALE    = 1000       # ARS is quoted per 1000 units
BCB_USD_REF  = Decimal('6.96')
BCB_ARS_REF  = Decimal('0.007')   # per 1 ARS ≈ 0.007 BOB

_Q4 = Decimal('0.0001')


def _q(val) -> Decimal:
    return Decimal(str(val)).quantize(_Q4, rounding=ROUND_HALF_UP)


def _get_usd_bob_parallel() -> Decimal:
    """Get current USD/BOB parallel rate from DB."""
    try:
        from rates.models import Currency, ExchangeRate
        usd = Currency.objects.get(code='USD')
        bob = Currency.objects.get(code='BOB')
        rate = (
            ExchangeRate.objects
            .filter(
                currency_from=usd,
                currency_to=bob,
                valid_until__isnull=True,
                market_type__in=('paralelo_digital', 'parallel'),
            )
            .order_by('-confidence', '-valid_from')
            .first()
        )
        if rate and rate.buy_rate > 0:
            return _q((rate.buy_rate + rate.sell_rate) / 2)
    except Exception as exc:
        log.debug('SALDOAR_USD_BOB_FAIL %s', exc)
    return BCB_USD_REF


class SaldoARFetcher(BaseFetcher):
    """
    Fetches ARS/USD rate from SaldoAR and converts to ARS/BOB.

    Formula:
        ARS/BOB = ARS/USD * USD/BOB_parallel
        Per 1000 ARS: (1000 / ARS_per_USD) * USD_BOB_rate
    """
    source_name = 'SALDOAR'
    market_type = 'paralelo_digital'

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone

        session    = self._get_session()
        fetched_at = timezone.now()

        try:
            resp = session.get(SALDOAR_URL, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error('SALDOAR_FETCH_ERROR %s', exc)
            return []

        return self._parse(data, fetched_at)

    def _parse(self, data: dict | list, fetched_at) -> list[FetchResult]:
        """
        SaldoAR returns ARS per USD (how many ARS buy 1 USD).
        We need ARS/BOB (how many BOB for 1000 ARS).
        """
        # Try to extract buy/sell ARS per USD
        if isinstance(data, list) and data:
            item = data[0]
        elif isinstance(data, dict):
            item = data
        else:
            log.warning('SALDOAR_UNEXPECTED_FORMAT data=%s', type(data))
            return []

        try:
            # Fields: compra/venta = ARS per USD (how many ARS for 1 USD)
            ars_per_usd_buy  = _q(
                item.get('compra') or item.get('buy') or item.get('bid') or 0
            )
            ars_per_usd_sell = _q(
                item.get('venta') or item.get('sell') or item.get('ask') or 0
            )

            if ars_per_usd_buy <= 0 and ars_per_usd_sell <= 0:
                log.warning('SALDOAR_ZERO_RATE item=%s', item)
                return []

            if ars_per_usd_buy <= 0:
                ars_per_usd_buy = _q(ars_per_usd_sell * Decimal('0.99'))
            if ars_per_usd_sell <= 0:
                ars_per_usd_sell = _q(ars_per_usd_buy * Decimal('1.01'))

        except Exception as exc:
            log.error('SALDOAR_PARSE_ERROR %s', exc)
            return []

        # Cross-rate: ARS/BOB = (1 / ARS_per_USD) * USD_BOB
        usd_bob = _get_usd_bob_parallel()

        # Per 1 ARS:
        #   bob_per_ars_buy  = (1 / ars_per_usd_sell) * usd_bob  ← we buy ARS (pay BOB)
        #   bob_per_ars_sell = (1 / ars_per_usd_buy)  * usd_bob  ← we sell ARS (receive BOB)
        # Note: inverted buy/sell from ARS perspective
        try:
            bob_per_ars_buy  = usd_bob / ars_per_usd_sell  # cheaper to buy ARS
            bob_per_ars_sell = usd_bob / ars_per_usd_buy   # pricier to sell ARS

            # Scale to 1000 ARS
            buy_scaled  = _q(bob_per_ars_buy  * ARS_SCALE)
            sell_scaled = _q(bob_per_ars_sell * ARS_SCALE)

            if buy_scaled > sell_scaled:
                sell_scaled = _q(buy_scaled * Decimal('1.005'))

        except (ZeroDivisionError, Exception) as exc:
            log.error('SALDOAR_CROSSRATE_ERROR %s', exc)
            return []

        result = FetchResult(
            currency_code = 'ARS',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = BCB_ARS_REF,
            buy_rate      = buy_scaled,
            sell_rate     = sell_scaled,
            scale_factor  = ARS_SCALE,
            confidence    = 0.82,
            source_method = 'API',
            source_url    = SALDOAR_URL,
            fetched_at    = fetched_at,
            raw_data      = {
                'ars_per_usd_buy':  float(ars_per_usd_buy),
                'ars_per_usd_sell': float(ars_per_usd_sell),
                'usd_bob_used':     float(usd_bob),
            },
        )

        if not result.is_valid():
            log.warning('SALDOAR_INVALID_RESULT buy=%s sell=%s', buy_scaled, sell_scaled)
            return []

        log.info('SALDOAR_PARSED ars/bob_per_1000 buy=%s sell=%s', buy_scaled, sell_scaled)
        return [result]
