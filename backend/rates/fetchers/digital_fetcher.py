"""
Fetcher para plataformas digitales de cambio de divisas en Bolivia.

Plataformas objetivo:
  - Takenos   (takenos.com) — opera en Bolivia, Argentina, Chile
  - Airtm     (airtm.com)  — billetera digital regional
  - LocalBitcoins / BinanceP2P — como referencia de mercado libre
  - Páginas de cambio digital bolivianas

Nota de implementación:
  Estas plataformas no tienen APIs públicas con autenticación abierta.
  Se implementa scraping de sus páginas de cotizaciones públicas.
  Cuando scraping falla, se usa estimación basada en spread típico del mercado
  digital boliviano (~5-15% sobre el oficial).
"""
from __future__ import annotations
import logging
from decimal import Decimal

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.digital')

# Las tasas base de estimación ya NO son constantes hardcodeadas: se derivan de
# la última tasa REAL en BD vía rates.fetchers.reference.real_reference_rates()
# (las constantes 9.60/10.40/... quedaban obsoletas al moverse el paralelo).

# Spread ±% aplicado sobre la tasa base para estimar buy/sell
DIGITAL_SPREAD_ESTIMATE = {
    'USD': {'buy_premium': Decimal('0.015'), 'sell_premium': Decimal('0.020')},
    'EUR': {'buy_premium': Decimal('0.015'), 'sell_premium': Decimal('0.020')},
    'BRL': {'buy_premium': Decimal('0.020'), 'sell_premium': Decimal('0.025')},
    'ARS': {'buy_premium': Decimal('0.025'), 'sell_premium': Decimal('0.030')},
    'CLP': {'buy_premium': Decimal('0.020'), 'sell_premium': Decimal('0.025')},
    'PEN': {'buy_premium': Decimal('0.020'), 'sell_premium': Decimal('0.025')},
}


SCALE_FACTORS = {'USD': 1, 'EUR': 1, 'BRL': 1, 'PEN': 1, 'ARS': 1000, 'CLP': 1000}


class TakenosFetcher(BaseFetcher):
    """
    Fetcher para Takenos — plataforma de cambio digital que opera en Bolivia.
    Scraping de la página pública de cotizaciones.
    """
    source_name = 'TAKENOS'
    market_type = 'paralelo_digital'

    def _fetch(self) -> list[FetchResult]:
        """Intenta scraping de Takenos, fallback a estimación de mercado digital."""
        results = self._scrape_takenos()
        if results:
            return results
        log.info("TAKENOS_SCRAPE_FAILED — usando estimación de mercado digital")
        return self._estimate_digital_rates('TAKENOS_EST')

    def _scrape_takenos(self) -> list[FetchResult]:
        """
        Takenos publica sus cotizaciones en su sitio web.
        source_method='API' si responde JSON, 'SCRAP' si HTML.
        """
        import requests
        from bs4 import BeautifulSoup
        from django.utils import timezone as tz

        urls = [
            'https://app.takenos.com/exchange',
            'https://takenos.com',
            'https://api.takenos.com/v1/rates',
        ]
        session = self._get_session()

        for url in urls:
            try:
                fetched_at = tz.now()
                resp = session.get(url, timeout=8)
                if resp.status_code != 200:
                    continue

                if 'json' in resp.headers.get('content-type', ''):
                    results = self._parse_takenos_json(resp.json())
                    for r in results:
                        r.source_method = 'API'
                        r.source_url    = url
                        r.fetched_at    = fetched_at
                    return results

                soup    = BeautifulSoup(resp.text, 'html.parser')
                results = self._parse_rate_html(soup, 'TAKENOS')
                if results:
                    for r in results:
                        r.source_method = 'SCRAP'
                        r.source_url    = url
                        r.fetched_at    = fetched_at
                    return results

            except Exception as exc:
                log.debug("TAKENOS_URL_FAILED url=%s error=%s", url, exc)
                continue

        return []

    def _parse_takenos_json(self, data: dict | list) -> list[FetchResult]:
        """Parsea respuesta JSON de Takenos."""
        results = []
        items   = data.get('rates', data.get('data', data)) if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = [items]

        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get('currency', item.get('code', ''))).upper()
            if code not in SCALE_FACTORS:
                continue

            try:
                buy   = self._to_decimal(item.get('buy',  item.get('compra')))
                sell  = self._to_decimal(item.get('sell', item.get('venta')))
                scale    = SCALE_FACTORS.get(code, 1)
                buy_sc   = buy  * Decimal(str(scale)) if scale > 1 else buy
                sell_sc  = sell * Decimal(str(scale)) if scale > 1 else sell

                result = FetchResult(
                    currency_code = code,
                    market_type   = self.market_type,
                    source_name   = self.source_name,
                    official_rate = (buy_sc + sell_sc) / Decimal('2'),
                    buy_rate      = buy_sc,
                    sell_rate     = sell_sc,
                    scale_factor  = scale,
                    confidence    = 0.80,
                    raw_data      = item,
                )
                if result.is_valid():
                    results.append(result)
            except Exception as exc:
                log.debug("TAKENOS_ITEM_ERROR item=%s error=%s", item, exc)

        return results

    def _parse_rate_html(self, soup, source_name: str) -> list[FetchResult]:
        """Extrae tasas de una página HTML genérica de plataforma digital."""
        results = []
        # Buscar elementos con clases comunes en plataformas de cambio
        selectors = [
            'div[class*="rate"]', 'span[class*="price"]',
            'td[class*="buy"]',   'td[class*="sell"]',
            '[data-currency]',
        ]

        for selector in selectors:
            try:
                elements = soup.select(selector)
                if elements:
                    log.debug("DIGITAL_HTML_FOUND selector=%s elements=%d", selector, len(elements))
                    break
            except Exception:
                pass

        return results  # Retorna vacío — parsing HTML de SPA React es complejo sin Selenium

    def _estimate_digital_rates(self, source_suffix: str = '') -> list[FetchResult]:
        """
        Estimación de tasas digitales derivada de la ÚLTIMA TASA REAL en BD
        (ver rates.fetchers.reference) + spread típico del mercado digital.

        COMPLIANCE WARNING: source_method='INFERENCE', confidence=0.55.
        Estas tasas NO provienen de una fuente en tiempo real. Si no hay tasa
        real reciente de la que derivar, NO se emite nada (mejor sin dato que
        con un número inventado).
        El frontend mostrará indicador rojo y requerirá confirmación del operador.
        """
        from django.utils import timezone as tz

        from .reference import real_reference_rates

        results    = []
        fetched_at = tz.now()
        references = real_reference_rates()

        for code, ref in references.items():
            spread = DIGITAL_SPREAD_ESTIMATE.get(code, {
                'buy_premium': Decimal('0.015'),
                'sell_premium': Decimal('0.020'),
            })
            scale = SCALE_FACTORS.get(code, 1)
            # ref ya viene en BOB por scale_factor unidades (igual que ExchangeRate)
            buy_sc  = ref * (1 - spread['buy_premium'])
            sell_sc = ref * (1 + spread['sell_premium'])

            result = FetchResult(
                currency_code = code,
                market_type   = self.market_type,
                source_name   = f'DIGITAL_EST_{source_suffix}' if source_suffix else 'DIGITAL_EST',
                official_rate = (buy_sc + sell_sc) / Decimal('2'),
                buy_rate      = buy_sc,
                sell_rate     = sell_sc,
                scale_factor  = scale,
                confidence    = 0.55,
                raw_data      = {
                    'method':      'estimated_from_last_real',
                    'base_rate':   float(ref),
                    'buy_premium': float(spread['buy_premium']),
                    'warning':     'NOT_REAL_TIME',
                },
                # ── Trazabilidad ──────────────────────────────────────────────
                source_method = 'INFERENCE',
                source_url    = None,
                fetched_at    = fetched_at,
            )
            if result.is_valid():
                results.append(result)

        log.warning(
            "DIGITAL_RATES_ESTIMATED source_suffix=%s currencies=%d — scraping "
            "failed, derived from last real rates (INFERENCE)",
            source_suffix, len(results),
        )
        return results


class AirtmFetcher(BaseFetcher):
    """
    Fetcher para Airtm — billetera digital que opera en Bolivia.
    Usa el mismo mecanismo de estimación que Takenos cuando el scraping falla.
    """
    source_name = 'AIRTM'
    market_type = 'paralelo_digital'

    def _fetch(self) -> list[FetchResult]:
        results = self._scrape_airtm()
        if results:
            return results
        log.info("AIRTM_SCRAPE_FAILED — usando estimación")
        return self._estimate_airtm()

    def _scrape_airtm(self) -> list[FetchResult]:
        """Intenta obtener cotizaciones de Airtm."""
        import requests
        try:
            session = self._get_session()
            # Airtm no tiene API pública documentada — intentar endpoint conocido
            resp = session.get('https://app.airtm.com/exchange', timeout=8)
            # Las SPAs de React no devuelven datos en el HTML inicial
            # Se necesitaría Selenium — por ahora retorna vacío
            return []
        except Exception as exc:
            log.debug("AIRTM_SCRAPE_FAILED error=%s", exc)
            return []

    def _estimate_airtm(self) -> list[FetchResult]:
        """
        Estimación derivada de la última tasa real (ver rates.fetchers.reference)
        con spread similar a Takenos pero ligeramente mayor.
        COMPLIANCE: source_method='INFERENCE', confidence=0.50. Sin tasa real
        reciente no se emite nada.
        """
        from django.utils import timezone as tz

        from .reference import real_reference_rates

        results    = []
        fetched_at = tz.now()

        for code, ref in real_reference_rates().items():
            scale     = SCALE_FACTORS.get(code, 1)
            spread    = DIGITAL_SPREAD_ESTIMATE.get(code, {
                'buy_premium': Decimal('0.015'), 'sell_premium': Decimal('0.020'),
            })
            # ref en BOB por scale_factor unidades — misma escala que ExchangeRate
            buy_sc  = ref * (1 - spread['buy_premium']  - Decimal('0.005'))
            sell_sc = ref * (1 + spread['sell_premium'] + Decimal('0.005'))

            result = FetchResult(
                currency_code = code,
                market_type   = self.market_type,
                source_name   = 'AIRTM_EST',
                official_rate = (buy_sc + sell_sc) / Decimal('2'),
                buy_rate      = buy_sc,
                sell_rate     = sell_sc,
                scale_factor  = scale,
                confidence    = 0.50,
                raw_data      = {'method': 'estimated_from_last_real',
                                 'base_rate': float(ref),
                                 'warning': 'NOT_REAL_TIME'},
                source_method = 'INFERENCE',
                source_url    = None,
                fetched_at    = fetched_at,
            )
            if result.is_valid():
                results.append(result)
        log.warning("AIRTM_RATES_ESTIMATED currencies=%d — scraping failed, "
                    "derived from last real rates (INFERENCE)", len(results))
        return results
