"""
Agregadores HTML — scraping de sitios que publican USD/BOB paralelo.

Clase genérica HtmlAggregatorFetcher con:
  1. Intento de detección de JSON interno (XHR endpoint)
  2. Fallback a BeautifulSoup con selectores CSS configurables
  3. Fallback a regex numérico sobre texto completo

Sitios cubiertos:
  usdtbol.com, ayudabolivia.com, dolarparalelobolivia.net,
  dolarbolivia.net, bolivianblue.net, boliviadolarblue.com, bolidolar.com
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone as tz
from decimal import Decimal
from typing import Optional

from rates.integrations.base import AbstractRateFetcher
from rates.schemas import NormalizedRate

log = logging.getLogger('kapitalya.integrations.aggregators')

_RATE_REGEX = re.compile(r'\b((?:8|9|10|11|12|13|14)[\.,]\d{1,4})\b')
_MIN_BOB    = Decimal('8.0')
_MAX_BOB    = Decimal('15.0')
_Q8         = Decimal('0.00000001')


@dataclass
class SiteConfig:
    id_fuente:  str
    url:        str
    json_paths: list[str] = field(default_factory=list)  # URLs de XHR a intentar
    css_buy:    list[str] = field(default_factory=list)
    css_sell:   list[str] = field(default_factory=list)
    css_mid:    list[str] = field(default_factory=list)
    confianza:  int       = 70


_SITE_CONFIGS: dict[str, SiteConfig] = {
    'usdtbol': SiteConfig(
        id_fuente  = 'usdtbol',
        url        = 'https://usdtbol.com',
        json_paths = ['https://usdtbol.com/api/rate', 'https://usdtbol.com/rates.json'],
        css_buy    = ['.buy', '.compra', '[data-type="buy"]'],
        css_sell   = ['.sell', '.venta', '[data-type="sell"]'],
        css_mid    = ['.price', '.rate', '.dolar', '[class*="rate"]'],
        confianza  = 70,
    ),
    'ayudabolivia': SiteConfig(
        id_fuente  = 'ayudabolivia',
        url        = 'https://ayudabolivia.com',
        json_paths = ['https://ayudabolivia.com/api/rate', 'https://ayudabolivia.com/rate.json'],
        css_buy    = ['.compra', '.buy-rate', '[id*="compra"]'],
        css_sell   = ['.venta', '.sell-rate', '[id*="venta"]'],
        css_mid    = ['.cotizacion', '.dolar', '.precio'],
        confianza  = 68,
    ),
    'dolarparalelobolivia': SiteConfig(
        id_fuente  = 'dolarparalelobolivia',
        url        = 'https://dolarparalelobolivia.net',
        json_paths = [],
        css_buy    = ['.compra', '.buy'],
        css_sell   = ['.venta', '.sell'],
        css_mid    = ['.precio', '.cotizacion', '.rate'],
        confianza  = 65,
    ),
    'dolarbolivia': SiteConfig(
        id_fuente  = 'dolarbolivia',
        url        = 'https://dolarbolivia.net',
        json_paths = [],
        css_buy    = ['.compra', '[class*="compra"]'],
        css_sell   = ['.venta',  '[class*="venta"]'],
        css_mid    = ['.precio', '[class*="precio"]'],
        confianza  = 65,
    ),
    'bolivianblue': SiteConfig(
        id_fuente  = 'bolivianblue',
        url        = 'https://bolivianblue.net',
        json_paths = ['https://bolivianblue.net/api/dolar'],
        css_buy    = ['.buy', '.compra'],
        css_sell   = ['.sell', '.venta'],
        css_mid    = ['.price', '.precio'],
        confianza  = 68,
    ),
    'boliviadolarblue': SiteConfig(
        id_fuente  = 'boliviadolarblue',
        url        = 'https://boliviadolarblue.com',
        json_paths = [],
        css_buy    = ['.compra'],
        css_sell   = ['.venta'],
        css_mid    = ['.precio', '.dolar'],
        confianza  = 65,
    ),
    'bolidolar': SiteConfig(
        id_fuente  = 'bolidolar',
        url        = 'https://bolidolar.com',
        json_paths = ['https://bolidolar.com/api/rate'],
        css_buy    = ['.buy', '.compra'],
        css_sell   = ['.sell', '.venta'],
        css_mid    = ['.price', '.rate'],
        confianza  = 67,
    ),
}


def _parse_decimal(text: str) -> Optional[Decimal]:
    cleaned = (
        str(text).strip()
        .replace(',', '.')
        .replace('Bs', '').replace('$', '').replace(' ', '')
    )
    try:
        val = Decimal(cleaned)
        if _MIN_BOB <= val <= _MAX_BOB:
            return val
    except Exception:
        pass
    return None


class HtmlAggregatorFetcher(AbstractRateFetcher):
    """
    Fetcher genérico para sitios HTML con configuración por sitio.

    Estrategia 1: JSON interno (XHR endpoint)
    Estrategia 2: BeautifulSoup CSS selectors
    Estrategia 3: Regex numérico sobre texto completo
    """
    tipo_fuente = 'AGREGADOR'

    def __init__(self, config: SiteConfig):
        self._config = config
        self.id_fuente = config.id_fuente

    def fetch(self) -> list[NormalizedRate]:
        cfg = self._config
        now = datetime.now(tz.utc)
        session = self._get_session()

        # Estrategia 1: JSON interno
        result = self._try_json(session, cfg)
        if not result:
            # Estrategia 2+3: HTML
            result = self._try_html(session, cfg)

        if not result:
            log.warning('HTML_AGG id=%s — sin datos', cfg.id_fuente)
            self._mark_needs_revision()
            return []

        buy, sell, mid = result

        if buy and sell and buy > sell:
            buy, sell = sell, buy
        if buy and sell and not mid:
            mid = (buy + sell) / Decimal('2')

        precio_compra = buy or mid
        precio_venta  = sell or mid

        if not precio_compra:
            return []

        return [NormalizedRate(
            moneda_base      = 'USD',
            moneda_cotizada  = 'BOB',
            precio           = precio_compra,
            precio_compra    = precio_compra,
            precio_venta     = precio_venta,
            spread_pct       = None,
            fuente           = cfg.id_fuente,
            tipo_fuente      = self.tipo_fuente,
            timestamp        = now,
            payload_raw      = {
                'buy': str(buy), 'sell': str(sell), 'mid': str(mid), 'url': cfg.url,
            },
            confianza        = cfg.confianza,
            es_valido        = True,
        )]

    def _try_json(self, session, cfg: SiteConfig) -> Optional[tuple]:
        for json_url in cfg.json_paths:
            try:
                resp = session.get(json_url, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                buy  = _parse_decimal(str(data.get('buy')  or data.get('compra') or data.get('bid') or ''))
                sell = _parse_decimal(str(data.get('sell') or data.get('venta')  or data.get('ask') or ''))
                mid  = _parse_decimal(str(data.get('mid')  or data.get('precio') or data.get('rate') or ''))
                if buy or mid:
                    log.info('HTML_AGG_JSON id=%s url=%s', cfg.id_fuente, json_url)
                    return buy, sell, mid
            except Exception as exc:
                log.debug('HTML_AGG_JSON_FAIL id=%s url=%s err=%s', cfg.id_fuente, json_url, exc)
        return None

    def _try_html(self, session, cfg: SiteConfig) -> Optional[tuple]:
        try:
            from bs4 import BeautifulSoup
            resp = session.get(cfg.url, timeout=self.timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            buy  = self._css_first(soup, cfg.css_buy)
            sell = self._css_first(soup, cfg.css_sell)
            mid  = self._css_first(soup, cfg.css_mid)

            # Fallback regex
            if not mid and not buy:
                all_text = soup.get_text(' ', strip=True)
                matches  = _RATE_REGEX.findall(all_text)
                valids   = sorted({
                    Decimal(m.replace(',', '.'))
                    for m in matches
                    if _MIN_BOB <= Decimal(m.replace(',', '.')) <= _MAX_BOB
                })
                if valids:
                    buy  = buy  or valids[0]
                    sell = sell or (valids[-1] if len(valids) > 1 else None)
                    mid  = mid  or valids[len(valids) // 2]

            if buy or mid:
                return buy, sell, mid
        except Exception as exc:
            log.warning('HTML_AGG_HTML_FAIL id=%s err=%s', cfg.id_fuente, exc)
        return None

    @staticmethod
    def _css_first(soup, selectors: list[str]) -> Optional[Decimal]:
        for sel in selectors:
            try:
                el = soup.select_one(sel)
                if el:
                    val = _parse_decimal(el.get_text())
                    if val:
                        return val
            except Exception:
                continue
        return None


# ── Clases concretas (una por sitio) ─────────────────────────────────────────

class USDTBolFetcher(HtmlAggregatorFetcher):
    def __init__(self):
        super().__init__(_SITE_CONFIGS['usdtbol'])

class AyudaBoliviaFetcher(HtmlAggregatorFetcher):
    def __init__(self):
        super().__init__(_SITE_CONFIGS['ayudabolivia'])

class DolarParaleloBoliviaFetcher(HtmlAggregatorFetcher):
    def __init__(self):
        super().__init__(_SITE_CONFIGS['dolarparalelobolivia'])

class DolarBoliviaFetcher(HtmlAggregatorFetcher):
    def __init__(self):
        super().__init__(_SITE_CONFIGS['dolarbolivia'])

class BolivianBlueFetcher(HtmlAggregatorFetcher):
    def __init__(self):
        super().__init__(_SITE_CONFIGS['bolivianblue'])

class BoliviaDolarBlueFetcher(HtmlAggregatorFetcher):
    def __init__(self):
        super().__init__(_SITE_CONFIGS['boliviadolarblue'])

class BoliDolarFetcher(HtmlAggregatorFetcher):
    def __init__(self):
        super().__init__(_SITE_CONFIGS['bolidolar'])
