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

SALDOAR_URL       = 'https://api.saldo.com.ar/json/rates/banco/banco_ar_usd'
_SALDOAR_FALLBACK_URLS = [
    'https://api.saldo.com.ar/json/rates',
    'https://api.saldo.com.ar/json/rates/banco/usd',
    'https://saldo.com.ar/api/rates',
]
ARS_SCALE    = 1000       # ARS is quoted per 1000 units
_PARALLEL_USD_FALLBACK = Decimal('9.80')  # fallback conservador si DB está vacío
_ARS_PARALLEL_REF = Decimal('8.00')  # per 1000 ARS, mercado paralelo boliviano

_Q4 = Decimal('0.0001')


def _q(val) -> Decimal:
    return Decimal(str(val)).quantize(_Q4, rounding=ROUND_HALF_UP)


def _get_usd_bob_parallel() -> tuple[Decimal, bool]:
    """
    USD/BOB paralelo desde BD para el cross-rate ARS/BOB.

    Devuelve (valor, is_real). is_real=False cuando se cayó al constante
    _PARALLEL_USD_FALLBACK (BD sin ninguna referencia), para que el llamador
    DEGRADE la tasa ARS derivada en vez de emitir un hardcode como dato real.
    Antes de rendirse intenta la última USD/BOB paralela conocida aunque ya
    esté expirada (dentro de 7 días).
    """
    try:
        from datetime import timedelta
        from django.utils import timezone
        from rates.models import Currency, ExchangeRate
        usd = Currency.objects.get(code='USD')
        bob = Currency.objects.get(code='BOB')
        base_q = ExchangeRate.objects.filter(
            currency_from=usd, currency_to=bob,
            market_type__in=('paralelo_digital', 'parallel'),
        )
        # 1) tasa activa vigente
        rate = base_q.filter(valid_until__isnull=True).order_by(
            '-confidence', '-valid_from').first()
        # 2) última conocida (aunque expirada) dentro de 7 días
        if not (rate and rate.buy_rate > 0):
            since = timezone.now() - timedelta(days=7)
            rate = base_q.filter(valid_from__gte=since).order_by(
                '-valid_from').first()
        if rate and rate.buy_rate > 0:
            return _q((rate.buy_rate + rate.sell_rate) / 2), True
    except Exception as exc:
        log.debug('SALDOAR_USD_BOB_FAIL %s', exc)
    return _PARALLEL_USD_FALLBACK, False


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

        # Try primary URL then fallbacks
        all_urls = [SALDOAR_URL] + _SALDOAR_FALLBACK_URLS
        for url in all_urls:
            try:
                resp = session.get(url, timeout=DEFAULT_TIMEOUT)
                if resp.status_code in (404, 403):
                    continue
                resp.raise_for_status()
                raw = resp.text.strip()
                if not raw:
                    log.debug('SALDOAR_EMPTY_BODY url=%s', url)
                    continue
                data = resp.json()
                results = self._parse(data, fetched_at)
                if results:
                    return results
            except Exception as exc:
                log.debug('SALDOAR_FETCH_ERROR url=%s error=%s', url, exc)

        log.warning('SALDOAR_ALL_URLS_FAILED — no data from any endpoint')
        return []

    def _parse(self, data: dict | list, fetched_at) -> list[FetchResult]:
        """
        SaldoAR returns ARS per USD (how many ARS buy 1 USD).
        We need ARS/BOB (how many BOB for 1000 ARS).
        """
        # Try to extract buy/sell ARS per USD — handle nested structures
        if isinstance(data, list) and data:
            item = data[0]
        elif isinstance(data, dict):
            # Unwrap common nested keys
            for key in ('data', 'rates', 'result', 'banco', 'oficial'):
                if key in data and isinstance(data[key], (dict, list)):
                    inner = data[key]
                    if isinstance(inner, list) and inner:
                        item = inner[0]
                    else:
                        item = inner
                    break
            else:
                item = data
        else:
            log.debug('SALDOAR_UNEXPECTED_FORMAT data=%s', type(data))
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
        usd_bob, usd_bob_is_real = _get_usd_bob_parallel()

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

        # Si la pata USD/BOB fue el constante de fallback (BD sin referencia),
        # el cross-rate ARS/BOB es una ESTIMACIÓN, no un dato de mercado real:
        # se emite como INFERENCE con baja confianza para que el compliance lo
        # bloquee en transacciones (antes se colaba como API/0.82).
        confidence    = 0.82 if usd_bob_is_real else 0.40
        source_method = 'API' if usd_bob_is_real else 'INFERENCE'
        if not usd_bob_is_real:
            log.warning(
                'SALDOAR_USD_BOB_FALLBACK usd_bob=%s (constante) — ARS/BOB '
                'degradada a INFERENCE', usd_bob,
            )

        result = FetchResult(
            currency_code = 'ARS',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = (buy_scaled + sell_scaled) / Decimal('2'),
            buy_rate      = buy_scaled,
            sell_rate     = sell_scaled,
            scale_factor  = ARS_SCALE,
            confidence    = confidence,
            source_method = source_method,
            source_url    = SALDOAR_URL,
            fetched_at    = fetched_at,
            raw_data      = {
                'ars_per_usd_buy':  float(ars_per_usd_buy),
                'ars_per_usd_sell': float(ars_per_usd_sell),
                'usd_bob_used':     float(usd_bob),
                'usd_bob_is_real':  usd_bob_is_real,
            },
        )

        if not result.is_valid():
            log.warning('SALDOAR_INVALID_RESULT buy=%s sell=%s', buy_scaled, sell_scaled)
            return []

        log.info('SALDOAR_PARSED ars/bob_per_1000 buy=%s sell=%s', buy_scaled, sell_scaled)
        return [result]
