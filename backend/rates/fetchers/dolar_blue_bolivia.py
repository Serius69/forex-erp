"""
Fetcher multi-plataforma para DolarBlueBolivia.

URL base: https://www.dolarbluebolivia.click/

El sitio agrega cotizaciones del mercado paralelo boliviano desde múltiples
plataformas digitales. Esta versión intenta extraer cada plataforma como una
FetchResult independiente con trazabilidad propia.

Plataformas objetivo:
  - Paralelo principal (referencia general del sitio)
  - Airtm          (plataforma P2P latinoamericana)
  - Binance P2P    (tabla publicada en el sitio, no la API)
  - Takenos        (P2P argentino con operaciones en Bolivia)
  - Wallbit        (remesas digitales)
  - Otras plataformas que aparezcan

Estrategia en cascada por plataforma:
  1. Buscar sección/tabla con nombre de plataforma
  2. Extraer compra/venta del bloque
  3. Si la sección no existe → saltar (no INFERENCE)

Estrategia general (si plataformas no detectadas):
  1. CSS selectors con clases compra/venta
  2. Tablas HTML con columnas detectadas
  3. Regex sobre HTML completo
  4. Extracción numérica de último recurso

source_method = 'SCRAP'
confidence per plataforma:
  - Sitio principal: 0.80
  - Binance P2P (referencia del sitio): 0.75
  - Airtm: 0.75
  - Takenos: 0.75
  - Wallbit: 0.70
"""
from __future__ import annotations
import logging
import re
from decimal import Decimal, InvalidOperation

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.dolar_blue_bo')

SOURCE_URL = 'https://www.dolarbluebolivia.click/'

# Rango de validación: USD/BOB paralelo razonable
_MIN_BOB = Decimal('7.50')
_MAX_BOB = Decimal('16.00')

# Regex para extraer pares compra/venta de texto HTML
_PAIR_RE = re.compile(
    r'(?:compra|buy|comprar)[^\d]{0,40}(\d{1,2}[.,]\d{2,4})'
    r'.{0,80}'
    r'(?:venta|sell|vender)[^\d]{0,40}(\d{1,2}[.,]\d{2,4})',
    re.IGNORECASE | re.DOTALL,
)
_PAIR_RE_REV = re.compile(
    r'(?:venta|sell)[^\d]{0,40}(\d{1,2}[.,]\d{2,4})'
    r'.{0,80}'
    r'(?:compra|buy)[^\d]{0,40}(\d{1,2}[.,]\d{2,4})',
    re.IGNORECASE | re.DOTALL,
)
_NUMBERS_RE = re.compile(r'\b(\d{1,2}[.,]\d{2,4})\b')

# Plataformas a buscar en el sitio con sus configuraciones
PLATFORM_CONFIG: dict[str, dict] = {
    'DOLARBLUE_AIRTM': {
        'keywords':   ['airtm'],
        'confidence': 0.75,
        'source_name': 'DOLARBLUE_AIRTM',
    },
    'DOLARBLUE_BINANCE': {
        'keywords':   ['binance'],
        'confidence': 0.75,
        'source_name': 'DOLARBLUE_BINANCE',
    },
    'DOLARBLUE_TAKENOS': {
        'keywords':   ['takenos'],
        'confidence': 0.75,
        'source_name': 'DOLARBLUE_TAKENOS',
    },
    'DOLARBLUE_WALLBIT': {
        'keywords':   ['wallbit'],
        'confidence': 0.70,
        'source_name': 'DOLARBLUE_WALLBIT',
    },
    'DOLARBLUE_SALDOAR': {
        'keywords':   ['saldo', 'saldoar'],
        'confidence': 0.68,
        'source_name': 'DOLARBLUE_SALDOAR',
    },
}


def _to_dec(text: str) -> Decimal | None:
    try:
        cleaned = str(text).strip().replace(',', '.').replace(' ', '')
        value = Decimal(cleaned)
        if _MIN_BOB <= value <= _MAX_BOB:
            return value
    except (InvalidOperation, Exception):
        pass
    return None


class DolarBlueBoliviaFetcher(BaseFetcher):
    """
    Scraper multi-plataforma de DolarBlueBolivia.

    Retorna una FetchResult por cada plataforma encontrada en la página,
    más la tasa general del sitio si se puede extraer.
    Si ninguna plataforma responde → retorna [] (no genera INFERENCE).
    """
    source_name = 'DOLARBLUE_BO'
    market_type = 'paralelo_digital'

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone as tz
        import requests
        from bs4 import BeautifulSoup

        fetched_at = tz.now()
        session    = self._get_session()

        try:
            resp = session.get(SOURCE_URL, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:
            log.warning('DOLARBLUE_FETCH_FAILED url=%s error=%s', SOURCE_URL, exc)
            return []

        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')

        all_results: list[FetchResult] = []

        # 1. Extraer tasas por plataforma
        platform_results = self._extract_platforms(soup, html, fetched_at)
        all_results.extend(platform_results)

        # 2. Extraer tasa principal del sitio (puede solaparse con plataformas)
        main_buy, main_sell = self._extract_main_rate(soup, html)
        if main_buy is not None and main_sell is not None:
            if main_buy > main_sell:
                main_buy, main_sell = main_sell, main_buy

            log.info('DOLARBLUE_MAIN buy=%s sell=%s', main_buy, main_sell)

            result = FetchResult(
                currency_code = 'USD',
                market_type   = self.market_type,
                source_name   = self.source_name,
                official_rate = Decimal('6.96'),
                buy_rate      = main_buy,
                sell_rate     = main_sell,
                scale_factor  = 1,
                confidence    = 0.80,
                raw_data      = {'source_url': SOURCE_URL, 'platform': 'main'},
                source_method = 'SCRAP',
                source_url    = SOURCE_URL,
                fetched_at    = fetched_at,
            )
            all_results.append(result)

            # Persistir la tasa principal en la DB
            try:
                self._save_to_db(main_buy, main_sell, fetched_at, source_label='dolarblue_bo')
            except Exception as exc:
                log.error('DOLARBLUE_SAVE_ERROR %s', exc, exc_info=True)

        if not all_results:
            log.warning(
                'DOLARBLUE_PARSE_FAILED — no se pudieron extraer tasas de %s', SOURCE_URL
            )

        return all_results

    # ── Extracción por plataforma ─────────────────────────────────────────────

    def _extract_platforms(self, soup, html: str, fetched_at) -> list[FetchResult]:
        """Busca secciones específicas de cada plataforma en el HTML."""
        results: list[FetchResult] = []

        for platform_key, cfg in PLATFORM_CONFIG.items():
            buy, sell = self._extract_platform_section(soup, html, cfg['keywords'])
            if buy is None or sell is None:
                continue

            if buy > sell:
                buy, sell = sell, buy

            log.info(
                'DOLARBLUE_PLATFORM platform=%s buy=%s sell=%s',
                platform_key, buy, sell,
            )

            results.append(FetchResult(
                currency_code = 'USD',
                market_type   = self.market_type,
                source_name   = cfg['source_name'],
                official_rate = Decimal('6.96'),
                buy_rate      = buy,
                sell_rate     = sell,
                scale_factor  = 1,
                confidence    = cfg['confidence'],
                raw_data      = {
                    'source_url': SOURCE_URL,
                    'platform':   platform_key,
                    'keywords':   cfg['keywords'],
                },
                source_method = 'SCRAP',
                source_url    = SOURCE_URL,
                fetched_at    = fetched_at,
            ))

        return results

    def _extract_platform_section(
        self,
        soup,
        html: str,
        keywords: list[str],
    ) -> tuple[Decimal | None, Decimal | None]:
        """
        Localiza el bloque HTML de una plataforma específica y extrae buy/sell.

        Estrategias:
          1. Buscar contenedores/secciones que contengan el keyword en texto/id/class
          2. Dentro del contenedor, buscar valores numéricos BOB
        """
        for keyword in keywords:
            # Buscar cualquier elemento cuyo texto o clase contenga el keyword
            candidates = soup.find_all(
                lambda tag: (
                    keyword in (tag.get_text(separator=' ', strip=True) or '').lower()[:200]
                    or keyword in ' '.join(tag.get('class', [])).lower()
                    or keyword in (tag.get('id', '') or '').lower()
                ),
                limit=5,
            )

            for container in candidates:
                # Buscar numbers dentro del contenedor y sus siblings cercanos
                context_text = self._get_context_text(container)
                buy, sell = self._extract_pair_from_text(context_text)
                if buy is not None and sell is not None:
                    return buy, sell

                # Buscar en la tabla más cercana al contenedor
                nearby_table = container.find_next('table') or container.find('table')
                if nearby_table:
                    buy, sell = self._strategy_table_single(nearby_table)
                    if buy is not None and sell is not None:
                        return buy, sell

        return None, None

    def _get_context_text(self, element) -> str:
        """Extrae texto del elemento más sus N siblings siguientes para ampliar contexto."""
        parts = [element.get_text(separator=' ', strip=True)]
        sibling = element.find_next_sibling()
        for _ in range(3):
            if sibling is None:
                break
            parts.append(sibling.get_text(separator=' ', strip=True))
            sibling = sibling.find_next_sibling()
        return ' '.join(parts)

    def _extract_pair_from_text(self, text: str) -> tuple[Decimal | None, Decimal | None]:
        """Extrae par compra/venta de un fragmento de texto."""
        m = _PAIR_RE.search(text)
        if m:
            buy  = _to_dec(m.group(1))
            sell = _to_dec(m.group(2))
            if buy and sell:
                return buy, sell

        m = _PAIR_RE_REV.search(text)
        if m:
            sell = _to_dec(m.group(1))
            buy  = _to_dec(m.group(2))
            if buy and sell:
                return buy, sell

        # Números en rango BOB sin etiquetas → tomar mín=compra, máx=venta
        nums = sorted(set(d for r in _NUMBERS_RE.findall(text) if (d := _to_dec(r)) is not None))
        if len(nums) >= 2:
            return nums[0], nums[-1]

        return None, None

    def _strategy_table_single(self, table) -> tuple[Decimal | None, Decimal | None]:
        """Extrae compra/venta de una tabla dada."""
        headers = []
        header_row = table.find('tr')
        if header_row:
            headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th', 'td'])]

        buy_col = sell_col = None
        for i, h in enumerate(headers):
            if any(k in h for k in ('compra', 'buy', 'comprar')):
                buy_col = i
            if any(k in h for k in ('venta', 'sell', 'vender')):
                sell_col = i

        for row in table.find_all('tr')[1:]:
            cells = row.find_all(['td', 'th'])
            nums  = [_to_dec(c.get_text(strip=True)) for c in cells]
            nums  = [n for n in nums if n is not None]

            if buy_col is not None and sell_col is not None:
                buy  = _to_dec(cells[buy_col].get_text(strip=True))  if buy_col  < len(cells) else None
                sell = _to_dec(cells[sell_col].get_text(strip=True)) if sell_col < len(cells) else None
                if buy and sell:
                    return buy, sell
            elif len(nums) >= 2:
                return nums[0], nums[-1]

        return None, None

    # ── Extracción de tasa principal del sitio ────────────────────────────────

    def _extract_main_rate(self, soup, html: str) -> tuple[Decimal | None, Decimal | None]:
        """Intenta extraer la tasa principal del sitio usando múltiples estrategias."""
        result = self._strategy_class_selectors(soup)
        if result != (None, None):
            log.debug('DOLARBLUE_STRATEGY=class_selectors')
            return result

        result = self._strategy_table(soup)
        if result != (None, None):
            log.debug('DOLARBLUE_STRATEGY=table')
            return result

        result = self._strategy_regex(html)
        if result != (None, None):
            log.debug('DOLARBLUE_STRATEGY=regex')
            return result

        result = self._strategy_number_extraction(soup)
        if result != (None, None):
            log.debug('DOLARBLUE_STRATEGY=number_extraction')
            return result

        return None, None

    def _strategy_class_selectors(self, soup) -> tuple[Decimal | None, Decimal | None]:
        buy_selectors = [
            '[class*="compra"]', '[class*="buy"]', '[class*="comprar"]',
            '[id*="compra"]', '[id*="buy"]',
            '[data-label*="compra"]', '[data-type*="buy"]',
        ]
        sell_selectors = [
            '[class*="venta"]', '[class*="sell"]', '[class*="vender"]',
            '[id*="venta"]', '[id*="sell"]',
            '[data-label*="venta"]', '[data-type*="sell"]',
        ]
        buy  = self._first_decimal_in_selectors(soup, buy_selectors)
        sell = self._first_decimal_in_selectors(soup, sell_selectors)
        return buy, sell

    def _first_decimal_in_selectors(self, soup, selectors: list[str]) -> Decimal | None:
        for sel in selectors:
            try:
                for el in soup.select(sel):
                    text = el.get_text(strip=True)
                    for n in _NUMBERS_RE.findall(text):
                        dec = _to_dec(n)
                        if dec is not None:
                            return dec
            except Exception:
                continue
        return None

    def _strategy_table(self, soup) -> tuple[Decimal | None, Decimal | None]:
        for table in soup.find_all('table'):
            buy, sell = self._strategy_table_single(table)
            if buy is not None and sell is not None:
                return buy, sell
        return None, None

    def _strategy_regex(self, html: str) -> tuple[Decimal | None, Decimal | None]:
        m = _PAIR_RE.search(html)
        if m:
            buy  = _to_dec(m.group(1))
            sell = _to_dec(m.group(2))
            if buy and sell:
                return buy, sell
        m = _PAIR_RE_REV.search(html)
        if m:
            sell = _to_dec(m.group(1))
            buy  = _to_dec(m.group(2))
            if buy and sell:
                return buy, sell
        return None, None

    def _strategy_number_extraction(self, soup) -> tuple[Decimal | None, Decimal | None]:
        text = soup.get_text(separator=' ', strip=True)
        candidates = sorted(set(
            d for raw in _NUMBERS_RE.findall(text)
            if (d := _to_dec(raw)) is not None
        ))
        if len(candidates) >= 2:
            return candidates[0], candidates[-1]
        return None, None

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _save_to_db(
        self,
        buy: Decimal,
        sell: Decimal,
        fetched_at,
        source_label: str = 'dolarblue_bo',
    ) -> None:
        from django.utils import timezone
        from django.db import transaction as db_tx
        from rates.models import Currency, ExchangeRate

        usd = Currency.objects.filter(code='USD').first()
        bob = Currency.objects.filter(code='BOB').first()
        if not usd or not bob:
            log.error('DOLARBLUE_SAVE_SKIP missing USD or BOB')
            return

        now = fetched_at or timezone.now()

        with db_tx.atomic():
            ExchangeRate.objects.filter(
                currency_from       = usd,
                currency_to         = bob,
                market_type         = 'paralelo_digital',
                source              = source_label,
                valid_until__isnull = True,
            ).update(valid_until=now)

            ExchangeRate.objects.create(
                currency_from = usd,
                currency_to   = bob,
                market_type   = 'paralelo_digital',
                source        = source_label,
                buy_rate      = buy,
                sell_rate     = sell,
                official_rate = Decimal('6.96'),
                valid_from    = now,
                valid_until   = None,
                source_method = 'SCRAP',
                source_url    = SOURCE_URL,
                fetched_at    = now,
                confidence    = Decimal('0.800'),
                is_validated  = False,
            )
        log.info('DOLARBLUE_SAVED source=%s buy=%s sell=%s', source_label, buy, sell)
