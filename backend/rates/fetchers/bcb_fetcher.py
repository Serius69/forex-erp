"""
Fetcher para tasas del Banco Central de Bolivia (BCB).

Fuentes:
  1. BCB Oficial  → página principal bcb.gob.bo (tipo de cambio de referencia)
  2. BCB JSON API → endpoint interno del BCB (más estable que scraping HTML)

Notas técnicas:
  - El BCB fija el USD/BOB en 6.96 desde 2011 (tipo de cambio fijo)
  - EUR, BRL, etc. fluctúan según el mercado internacional
  - La tasa "referencial" es la que el BCB usa para transacciones interbanks
"""
from __future__ import annotations
import logging
from decimal import Decimal

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT

log = logging.getLogger('kapitalya.rates.fetcher.bcb')

# Tasas BCB conocidas y estables (fallback de último recurso)
# Actualizadas manualmente si el BCB cambia la política
BCB_HARDCODED_FALLBACK = {
    'USD': {'official': Decimal('6.96'),  'buy': Decimal('6.96'),  'sell': Decimal('6.96')},
    'EUR': {'official': Decimal('7.52'),  'buy': Decimal('7.52'),  'sell': Decimal('7.52')},
    'BRL': {'official': Decimal('1.22'),  'buy': Decimal('1.22'),  'sell': Decimal('1.22')},
    'ARS': {'official': Decimal('0.007'), 'buy': Decimal('0.007'), 'sell': Decimal('0.007')},
    'CLP': {'official': Decimal('0.0076'),'buy': Decimal('0.0076'),'sell': Decimal('0.0076')},
    'PEN': {'official': Decimal('1.85'),  'buy': Decimal('1.85'),  'sell': Decimal('1.85')},
}

# scale_factor por divisa (debe coincidir con Currency.scale_factor en DB)
SCALE_FACTORS = {
    'USD': 1, 'EUR': 1, 'BRL': 1, 'PEN': 1,
    'ARS': 1000, 'CLP': 1000,  # cotizados en lotes de 1000
}


class BCBOfficialFetcher(BaseFetcher):
    """
    Tasa oficial BCB — página principal del Banco Central de Bolivia.
    Intenta 3 estrategias en cascada:
      1. BCB API JSON interna
      2. Scraping HTML de bcb.gob.bo
      3. Fallback con valores históricos conocidos
    """
    source_name = 'BCB_OFICIAL'
    market_type = 'official'

    def _fetch(self) -> list[FetchResult]:
        # Estrategia 1: API JSON interna del BCB
        results = self._fetch_bcb_json()
        if results:
            return results

        # Estrategia 2: Scraping HTML
        results = self._fetch_bcb_html()
        if results:
            return results

        # Estrategia 3: Hardcoded fallback
        log.warning("BCB_FETCHER using hardcoded fallback — fuentes online no disponibles")
        return self._hardcoded_fallback()

    def _fetch_bcb_json(self) -> list[FetchResult]:
        """
        BCB expone datos JSON en algunos endpoints internos.
        Proba URLs conocidas del sitio del BCB.
        """
        import requests
        from django.utils import timezone as tz
        urls_to_try = [
            'https://www.bcb.gob.bo/librerias/indicadores/tipo_cambio.php',
            'https://www.bcb.gob.bo/estad/indicador.php?codSec=2&codNiv=21',
        ]
        session = self._get_session()

        for url in urls_to_try:
            try:
                fetched_at = tz.now()
                resp = session.get(url, timeout=DEFAULT_TIMEOUT)
                if resp.status_code != 200:
                    continue

                content_type = resp.headers.get('content-type', '')
                if 'json' in content_type:
                    results = self._parse_bcb_json(resp.json())
                else:
                    # Intentar parsear como HTML si no es JSON
                    results = self._parse_bcb_html_page(resp.text)

                # Tag traceability
                for r in results:
                    r.source_method = 'API' if 'json' in content_type else 'SCRAP'
                    r.source_url    = url
                    r.fetched_at    = fetched_at
                return results

            except requests.RequestException as exc:
                log.debug("BCB_JSON_URL_FAILED url=%s error=%s", url, exc)
                continue
            except Exception as exc:
                log.debug("BCB_JSON_PARSE_FAILED url=%s error=%s", url, exc)
                continue

        return []

    def _fetch_bcb_html(self) -> list[FetchResult]:
        """Scraping de la página principal del BCB."""
        import requests
        from django.utils import timezone as tz

        BCB_URL = 'https://www.bcb.gob.bo/'
        try:
            fetched_at = tz.now()
            session    = self._get_session()
            resp       = session.get(BCB_URL, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            results = self._parse_bcb_html_page(resp.text)
            for r in results:
                r.source_method = 'SCRAP'
                r.source_url    = BCB_URL
                r.fetched_at    = fetched_at
            return results
        except requests.RequestException as exc:
            log.debug("BCB_HTML_FETCH_FAILED error=%s", exc)
            return []

    def _parse_bcb_html_page(self, html: str) -> list[FetchResult]:
        """
        Parsea el HTML del BCB para extraer tasas de cambio.
        El BCB usa tablas con clase 'cotizaciones' o similares.
        Busca múltiples selectores por robustez.
        """
        from bs4 import BeautifulSoup
        soup    = BeautifulSoup(html, 'html.parser')
        results = []

        # Mapa de nombres en español → código ISO
        currency_map = {
            'DÓLAR ESTADOUNIDENSE':  'USD',
            'DOLAR ESTADOUNIDENSE':  'USD',
            'EURO':                  'EUR',
            'REAL BRASILEÑO':        'BRL',
            'REAL BRASILENO':        'BRL',
            'PESO ARGENTINO':        'ARS',
            'PESO CHILENO':          'CLP',
            'SOL PERUANO':           'PEN',
            'BOLIVIANO':             'BOB',
        }

        # Buscar en tablas con diferentes selectores
        tables = (
            soup.find_all('table', class_='cotizaciones') or
            soup.find_all('table', class_=lambda c: c and 'tipo' in c.lower()) or
            soup.find_all('table')
        )

        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all(['td', 'th'])
                if len(cols) < 2:
                    continue

                currency_text = cols[0].get_text(strip=True).upper()
                code          = currency_map.get(currency_text)
                if not code or code == 'BOB':
                    continue

                # Intentar extraer buy/sell — el BCB a veces sólo publica "tipo de cambio"
                try:
                    vals = [self._to_decimal(c.get_text(strip=True)) for c in cols[1:]]
                    vals = [v for v in vals if v > 0]
                    if not vals:
                        continue

                    official = vals[0]
                    buy      = vals[0] if len(vals) < 2 else vals[0]   # BCB a veces no diferencia
                    sell     = vals[1] if len(vals) >= 2 else vals[0]
                    scale    = SCALE_FACTORS.get(code, 1)

                    # Para divisas de escala, BCB publica por unidad — ajustamos buy/sell
                    official_scaled = official * Decimal(str(scale))
                    buy_scaled      = official_scaled
                    sell_scaled     = official_scaled

                    result = FetchResult(
                        currency_code = code,
                        market_type   = self.market_type,
                        source_name   = self.source_name,
                        official_rate = official,          # siempre por unidad
                        buy_rate      = buy_scaled,        # por scale_factor unidades
                        sell_rate     = sell_scaled,       # por scale_factor unidades
                        scale_factor  = scale,
                        confidence    = 0.95,
                        raw_data      = {'source_col0': cols[0].get_text(), 'vals': [float(v) for v in vals]},
                    )
                    if result.is_valid():
                        results.append(result)

                except Exception as exc:
                    log.debug("BCB_ROW_PARSE_ERROR row=%s error=%s", row.get_text()[:50], exc)
                    continue

        log.debug("BCB_HTML_PARSE results=%d", len(results))
        return results

    def _parse_bcb_json(self, data: dict | list) -> list[FetchResult]:
        """Parsea respuesta JSON del BCB."""
        results = []
        items   = data if isinstance(data, list) else [data]

        currency_map = {
            'USD': 'USD', 'EUR': 'EUR', 'BRL': 'BRL',
            'ARS': 'ARS', 'CLP': 'CLP', 'PEN': 'PEN',
        }

        for item in items:
            if not isinstance(item, dict):
                continue
            code_raw = str(item.get('moneda', item.get('currency', ''))).upper()
            code     = currency_map.get(code_raw)
            if not code:
                continue

            try:
                official = self._to_decimal(item.get('tc', item.get('rate', item.get('valor'))))
                buy      = self._to_decimal(item.get('compra', item.get('buy',  official)))
                sell     = self._to_decimal(item.get('venta',  item.get('sell', official)))
                scale    = SCALE_FACTORS.get(code, 1)

                result = FetchResult(
                    currency_code = code,
                    market_type   = self.market_type,
                    source_name   = self.source_name,
                    official_rate = official,
                    buy_rate      = buy  * Decimal(str(scale)) if scale > 1 else buy,
                    sell_rate     = sell * Decimal(str(scale)) if scale > 1 else sell,
                    scale_factor  = scale,
                    confidence    = 0.95,
                    raw_data      = item,
                )
                if result.is_valid():
                    results.append(result)
            except Exception as exc:
                log.debug("BCB_JSON_ITEM_ERROR item=%s error=%s", item, exc)

        return results

    def _hardcoded_fallback(self) -> list[FetchResult]:
        """
        Último recurso: tasas históricamente conocidas del BCB.

        IMPORTANTE — COMPLIANCE WARNING:
        Estas tasas son valores históricos hardcodeados, NO datos en tiempo real.
        Se marcan con source_method='INFERENCE', confidence=0.5 e is_validated=False.
        El sistema de alertas mostrará advertencia visible a los operadores.
        NUNCA deben usarse para completar transacciones sin confirmación explícita.
        """
        from django.utils import timezone as tz
        results = []
        fetched_at = tz.now()
        for code, rates in BCB_HARDCODED_FALLBACK.items():
            scale = SCALE_FACTORS.get(code, 1)
            result = FetchResult(
                currency_code = code,
                market_type   = self.market_type,
                source_name   = f'{self.source_name}_FALLBACK',
                official_rate = rates['official'],
                buy_rate      = rates['buy']  * Decimal(str(scale)),
                sell_rate     = rates['sell'] * Decimal(str(scale)),
                scale_factor  = scale,
                confidence    = 0.5,        # baja confianza — dato histórico
                raw_data      = {'source': 'hardcoded_fallback', 'warning': 'NOT_REAL_TIME'},
                # ── Trazabilidad ──────────────────────────────────────────────
                source_method = 'INFERENCE',
                source_url    = None,       # sin URL — dato embebido en código
                fetched_at    = fetched_at,
            )
            results.append(result)
        log.warning(
            "BCB_HARDCODED_FALLBACK_USED currencies=%s — "
            "fuentes online NO disponibles; rates marcadas como INFERENCE",
            list(BCB_HARDCODED_FALLBACK.keys()),
        )
        return results


class BCBReferenceFetcher(BaseFetcher):
    """
    Tasa referencial BCB — publicada para operaciones del sistema financiero.
    Puede diferir ligeramente de la tasa oficial del día.
    """
    source_name = 'BCB_REFERENCIAL'
    market_type = 'bcb'

    def _fetch(self) -> list[FetchResult]:
        """
        El BCB publica tasas referenciales para el sistema bancario.
        Mismo proceso que BCBOfficialFetcher pero marcado como 'bcb' (referencial).
        source_method se hereda del método que logró obtener datos.
        """
        official_fetcher = BCBOfficialFetcher()
        results = official_fetcher._fetch_bcb_html()
        if not results:
            results = official_fetcher._hardcoded_fallback()

        # Cambiar market_type a 'bcb', ajustar confianza, preservar source_method
        for r in results:
            r.market_type = self.market_type
            r.source_name = self.source_name
            r.confidence  = min(r.confidence, 0.85)
            # source_method ya está correctamente seteado por BCBOfficialFetcher

        return results
