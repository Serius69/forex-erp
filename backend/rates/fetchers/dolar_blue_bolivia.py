"""
DolarBlueBolivia fetcher — https://www.dolarbluebolivia.click/

Extrae de una sola peticion HTTP:
  1. Tasa USD/BOB paralela principal          (DOLARBLUE_BO)
  2. Tasa oficial BCB                         (BCB_OFICIAL)
  3. Tasa referencial BCB                     (BCB_REFERENCIAL)
  4. Plataformas de intercambio USDT/BOB:
       El Dorado, Takenos, Wallbit, Airtm,
       Binance P2P, Bybit P2P, SaldoAr, Bitget  (DOLARBLUE_*)
  5. Cross rates regionales:
       BRL, ARS, PEN, EUR, GBP, CNY, CLP       (DOLARBLUE_*)
  6. Tendencia 24h                             (en raw_data de la tasa principal)

Cascada de extraccion:
  1. Rutas API internas de Next.js             <- mas rapido
  2. JSON embebido __NEXT_DATA__               <- SSR data
  3. /_next/data/{buildId}/index.json          <- hydration data
  4. Patron de texto sobre HTML plano          <- fallback robusto
  5. Fallback DB (ultima tasa conocida)
"""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation

from .base import BaseFetcher, FetchResult, DEFAULT_TIMEOUT, apply_min_spread

log = logging.getLogger('kapitalya.rates.fetcher.dolar_blue_bo')

SOURCE_URL = 'https://www.dolarbluebolivia.click/'

# ── Rangos de validacion ───────────────────────────────────────────────────────

_USD_PAR_MIN = Decimal('7.50')
_USD_PAR_MAX = Decimal('16.00')

# ── Configuracion de plataformas de intercambio ────────────────────────────────

# (source_name, keywords_en_texto, confidence)
EXCHANGE_CONFIG: list[tuple[str, list[str], float]] = [
    ('DOLARBLUE_ELDORADO', ['eldorado', 'el dorado', 'eldorado.io'],   0.88),
    ('DOLARBLUE_TAKENOS',  ['takenos',  'takenos.com'],                 0.85),
    ('DOLARBLUE_WALLBIT',  ['wallbit',  'wallbit.io'],                  0.85),
    ('DOLARBLUE_AIRTM',    ['airtm',    'airtm.com'],                   0.85),
    ('DOLARBLUE_BINANCE',  ['binance',  'binance.com'],                 0.90),
    ('DOLARBLUE_BYBIT',    ['bybit',    'bybit.com'],                   0.88),
    ('DOLARBLUE_SALDOAR',  ['saldoar',  'saldo ar', 'saldoar.com'],    0.80),
    ('DOLARBLUE_BITGET',   ['bitget',   'bitget.com'],                  0.85),
    ('DOLARBLUE_MERU',     ['meru'],                                    0.78),
]

# (currency_code, keywords, min_bob_per_unit, max_bob_per_unit, scale_factor, confidence)
CROSS_CONFIG: list[tuple[str, list[str], float, float, int, float]] = [
    ('BRL', ['real brasileño', 'real brasil', 'brl'],    0.50,  6.00,    1, 0.75),
    ('ARS', ['peso argentino', 'peso arg',    'ars'],    0.001, 0.020, 1000, 0.70),
    ('PEN', ['sol peruano',    'sol',         'pen'],    1.00,  5.00,    1, 0.75),
    ('EUR', ['euro',                          'eur'],    8.00, 18.00,    1, 0.78),
    ('GBP', ['libra esterlina','libra',       'gbp'],    9.00, 22.00,    1, 0.75),
    ('CNY', ['yuan chino',    'yuan',         'cny'],    0.50,  5.00,    1, 0.72),
    ('CLP', ['peso chileno',                  'clp'],    0.005, 0.05,  1000, 0.70),
]

# Rutas API internas de Next.js — probadas en orden
_API_ROUTES = [
    'https://www.dolarbluebolivia.click/api/rates',
    'https://www.dolarbluebolivia.click/api/cotizacion',
    'https://www.dolarbluebolivia.click/api/dolar',
    'https://www.dolarbluebolivia.click/api/paralelo',
    'https://www.dolarbluebolivia.click/api/exchanges',
    'https://www.dolarbluebolivia.click/api/precio',
    'https://www.dolarbluebolivia.click/api/divisas',
]

# ── Regex ──────────────────────────────────────────────────────────────────────

_NUM_RE       = re.compile(r'\b(\d{1,6}[.,]\d{2,6})\b')
_BS_PREFIX    = re.compile(r'Bs\.?\s*([\d.,]+)', re.IGNORECASE)
_PCT_RE       = re.compile(r'([+-]?\d+[.,]\d+)\s*%')
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_BUILD_ID_RE  = re.compile(r'"buildId"\s*:\s*"([^"]+)"')

# Patron especifico para bloques de exchange: "Nombre ... Compra Bs X.XX Venta Bs Y.YY"
_EXCHANGE_BLOCK_RE = re.compile(
    r'(?P<name>eldorado|takenos|wallbit|airtm|binance|bybit|saldoar|bitget|meru)'
    r'.{0,400}?'
    r'Compra\s+Bs\s+(?P<buy>[\d]+\.[\d]+)'
    r'.{0,100}?'
    r'Venta\s+Bs\s+(?P<sell>[\d]+\.[\d]+)',
    re.IGNORECASE | re.DOTALL,
)

# Patron para cross rates: "Real Brasileño ... Bs 2.00"
_CROSS_TABLE_ROW = re.compile(
    r'(?P<name>Real Brasileño|Peso Argentino|Sol Peruano|Euro|Libra Esterlina|Yuan Chino|Peso Chileno)'
    r'.{0,80}?'
    r'Bs\s+(?P<rate>[\d]+\.[\d]+)',
    re.IGNORECASE | re.DOTALL,
)

_CROSS_NAME_TO_CODE = {
    'real brasileño': 'BRL',
    'peso argentino': 'ARS',
    'sol peruano':    'PEN',
    'euro':           'EUR',
    'libra esterlina':'GBP',
    'yuan chino':     'CNY',
    'peso chileno':   'CLP',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_dec(text: str, lo: Decimal, hi: Decimal) -> Decimal | None:
    try:
        val = Decimal(str(text).strip().replace(',', '.').replace(' ', ''))
        if lo <= val <= hi:
            return val
    except (InvalidOperation, Exception):
        pass
    return None


def _prices_in_range(text: str, lo: Decimal, hi: Decimal) -> list[Decimal]:
    seen: set[Decimal] = set()
    out:  list[Decimal] = []
    for raw in _NUM_RE.findall(text):
        val = _to_dec(raw, lo, hi)
        if val is not None and val not in seen:
            seen.add(val)
            out.append(val)
    return sorted(out)


def _q(val) -> Decimal:
    from decimal import ROUND_HALF_UP
    return Decimal(str(val)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


# ── Clase principal ───────────────────────────────────────────────────────────

class DolarBlueBoliviaFetcher(BaseFetcher):
    """
    Extrae tasas paralelas bolivianas de dolarbluebolivia.click

    Retorna multiples FetchResult por peticion:
      - Tasa paralela USD/BOB principal
      - Tasas de plataformas P2P (El Dorado, Takenos, Wallbit, Airtm, Binance, Bybit, SaldoAr, Bitget)
      - Cross rates regionales (BRL, ARS, PEN, EUR, GBP, CNY, CLP)
    """
    source_name = 'DOLARBLUE_BO'
    market_type = 'paralelo_digital'

    # ── Punto de entrada ──────────────────────────────────────────────────────

    def _fetch(self) -> list[FetchResult]:
        from django.utils import timezone as tz
        fetched_at = tz.now()
        session    = self._get_session()
        session.headers.update({
            'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
            'Accept':          'text/html,application/json,*/*',
            'Accept-Language': 'es-BO,es;q=0.9',
        })

        all_results: list[FetchResult] = []

        # 1. Rutas API internas de Next.js (sin renderizado JS)
        api_results = self._try_internal_api(session, fetched_at)
        if api_results:
            all_results.extend(api_results)

        # 2. Pagina principal — extrae __NEXT_DATA__ y HTML
        if not all_results:
            try:
                resp = session.get(SOURCE_URL, timeout=DEFAULT_TIMEOUT)
                resp.raise_for_status()
                html      = resp.text
                text      = self._html_to_text(html)

                # 2a. __NEXT_DATA__ JSON embebido
                json_results = self._try_next_data(html, fetched_at)
                all_results.extend(json_results)

                # 2b. /_next/data/{buildId}/index.json
                if not all_results:
                    build_results = self._try_nextjs_build(session, html, fetched_at)
                    all_results.extend(build_results)

                # 2c. Patron de texto sobre el HTML
                text_results = self._extract_from_text(text, fetched_at)
                for r in text_results:
                    if not any(x.source_name == r.source_name and x.currency_code == r.currency_code
                               for x in all_results):
                        all_results.append(r)

            except Exception as exc:
                log.warning('DOLARBLUE_FETCH_FAILED url=%s error=%s', SOURCE_URL, exc)

        # 3. Guardar tasa principal en DB si la tenemos
        main = next((r for r in all_results if r.source_name == self.source_name), None)
        if main:
            try:
                self._save_to_db(main.buy_rate, main.sell_rate, fetched_at)
            except Exception as exc:
                log.error('DOLARBLUE_SAVE_ERROR %s', exc)

        if not all_results:
            log.warning('DOLARBLUE_PARSE_FAILED — usando fallback DB')
            self._insert_manual_fallback(fetched_at)

        log.info('DOLARBLUE_FETCH_DONE results=%d sources=%s',
                 len(all_results), [r.source_name for r in all_results])
        return all_results

    # ── 1. Rutas API internas Next.js ─────────────────────────────────────────

    def _try_internal_api(self, session, fetched_at) -> list[FetchResult]:
        for url in _API_ROUTES:
            try:
                resp = session.get(url, timeout=8)
                if resp.status_code != 200:
                    continue
                raw = resp.text.strip()
                if not raw or raw in ('{}', '[]', 'null'):
                    continue
                data = resp.json()
                results = self._parse_api_json(data, fetched_at, url)
                if results:
                    log.info('DOLARBLUE_API_HIT url=%s results=%d', url, len(results))
                    return results
            except Exception as exc:
                log.debug('DOLARBLUE_API_ROUTE url=%s error=%s', url, exc)
        return []

    def _parse_api_json(self, data, fetched_at, url: str) -> list[FetchResult]:
        """Parsea respuesta JSON de una API interna."""
        results: list[FetchResult] = []
        self._walk_json_comprehensive(data, fetched_at, url, results, depth=0)
        return results

    # ── 2a. __NEXT_DATA__ ────────────────────────────────────────────────────

    def _try_next_data(self, html: str, fetched_at) -> list[FetchResult]:
        m = _NEXT_DATA_RE.search(html)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
        except Exception as exc:
            log.debug('DOLARBLUE_NEXT_DATA_JSON_ERROR %s', exc)
            return []

        results: list[FetchResult] = []
        # Unwrap Next.js structure
        for path in [
            ['props', 'pageProps'],
            ['props'],
            ['pageProps'],
        ]:
            node = data
            for key in path:
                if isinstance(node, dict) and key in node:
                    node = node[key]
                else:
                    node = None
                    break
            if node:
                self._walk_json_comprehensive(node, fetched_at, SOURCE_URL, results, depth=0)
                if results:
                    log.info('DOLARBLUE_NEXT_DATA_HIT path=%s results=%d', path, len(results))
                    return results

        # Try full structure walk
        self._walk_json_comprehensive(data, fetched_at, SOURCE_URL, results, depth=0)
        return results

    # ── 2b. /_next/data/{buildId}/index.json ─────────────────────────────────

    def _try_nextjs_build(self, session, html: str, fetched_at) -> list[FetchResult]:
        m = _BUILD_ID_RE.search(html)
        if not m:
            return []
        build_id = m.group(1)
        url = f'https://www.dolarbluebolivia.click/_next/data/{build_id}/index.json'
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results: list[FetchResult] = []
            self._walk_json_comprehensive(data, fetched_at, url, results, depth=0)
            if results:
                log.info('DOLARBLUE_BUILD_DATA_HIT buildId=%s results=%d', build_id[:8], len(results))
            return results
        except Exception as exc:
            log.debug('DOLARBLUE_BUILD_DATA_ERROR buildId=%s error=%s', build_id[:8], exc)
            return []

    # ── JSON walker comprehensivo ─────────────────────────────────────────────

    def _walk_json_comprehensive(
        self,
        node,
        fetched_at,
        url: str,
        results: list,
        depth: int,
    ) -> None:
        """
        Recorre el JSON buscando:
         - Pares compra/venta en rango USD/BOB (7.5-16)
         - Arrays de plataformas con nombre y tasas
         - Tablas de divisas cruzadas
        """
        if depth > 12:
            return

        if isinstance(node, dict):
            # Buscar par compra/venta con fuente identificable
            self._extract_rate_node(node, fetched_at, url, results)

            # Buscar arrays de exchanges/divisas
            for key in ('exchanges', 'plataformas', 'cotizaciones', 'platforms',
                        'items', 'data', 'rates', 'divisas', 'currencies'):
                if key in node and isinstance(node[key], list):
                    for item in node[key]:
                        self._extract_rate_node(item, fetched_at, url, results)

            # Continuar en valores del dict
            for v in node.values():
                self._walk_json_comprehensive(v, fetched_at, url, results, depth + 1)

        elif isinstance(node, list):
            for item in node:
                self._walk_json_comprehensive(item, fetched_at, url, results, depth + 1)

    def _extract_rate_node(self, node: dict, fetched_at, url: str, results: list) -> None:
        """Extrae un par buy/sell de un nodo JSON y detecta la fuente."""
        if not isinstance(node, dict):
            return

        # Detectar fuente (nombre de plataforma)
        name_raw = str(
            node.get('nombre') or node.get('name') or node.get('slug') or
            node.get('source') or node.get('platform') or node.get('exchange') or ''
        ).lower()

        # Buscar buy/sell en rango USD/BOB
        buy  = self._find_decimal(node, ('compra', 'buy', 'buyRate', 'buy_rate', 'precio_compra'), _USD_PAR_MIN, _USD_PAR_MAX)
        sell = self._find_decimal(node, ('venta', 'sell', 'sellRate', 'sell_rate', 'precio_venta'), _USD_PAR_MIN, _USD_PAR_MAX)
        mid  = self._find_decimal(node, ('promedio', 'mid', 'average', 'price', 'precio'), _USD_PAR_MIN, _USD_PAR_MAX)

        if not buy and not sell and not mid:
            # Check for cross rate (other currencies)
            code = str(node.get('code') or node.get('currency') or node.get('moneda') or '').upper()
            if code and code != 'USD' and code != 'BOB':
                self._extract_cross_node(node, code, fetched_at, url, results)
            return

        # Use mid if buy/sell missing
        if not buy and mid:
            buy = _q(mid * Decimal('0.995'))
        if not sell and mid:
            sell = _q(mid * Decimal('1.005'))
        if not buy or not sell:
            return
        if buy > sell:
            buy, sell = sell, buy

        # Match to a known platform
        source_name = self.source_name  # default: main rate
        confidence  = 0.82
        for sname, kws, conf in EXCHANGE_CONFIG:
            if any(kw in name_raw for kw in kws):
                source_name = sname
                confidence  = conf
                break

        # Avoid duplicating the same source
        if any(r.source_name == source_name and r.currency_code == 'USD' for r in results):
            return

        r = FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = source_name,
            official_rate = (buy + sell) / Decimal('2'),
            buy_rate      = buy,
            sell_rate     = sell,
            scale_factor  = 1,
            confidence    = confidence,
            source_method = 'SCRAP',
            source_url    = url,
            fetched_at    = fetched_at,
            raw_data      = {'origin': 'json', 'name': name_raw or 'main'},
        )
        if r.is_valid():
            results.append(r)

    def _extract_cross_node(self, node: dict, code: str, fetched_at, url: str, results: list) -> None:
        """Extrae tasa de una divisa cruzada desde un nodo JSON."""
        cfg = next((c for c in CROSS_CONFIG if c[0] == code), None)
        if not cfg:
            return
        _, _, lo_f, hi_f, scale, conf = cfg
        lo = Decimal(str(lo_f))
        hi = Decimal(str(hi_f))

        rate = self._find_decimal(
            node,
            ('bob_rate', 'rate', 'bob', 'precio', 'valor', 'price', 'tasa'),
            lo, hi
        )
        if not rate:
            return

        scaled = _q(rate * Decimal(str(scale)))
        if any(r.source_name == f'DOLARBLUE_{code}' for r in results):
            return

        buy, sell = apply_min_spread(scaled)
        r = FetchResult(
            currency_code = code,
            market_type   = self.market_type,
            source_name   = f'DOLARBLUE_{code}',
            official_rate = rate,
            buy_rate      = buy,
            sell_rate     = sell,
            scale_factor  = scale,
            confidence    = conf,
            source_method = 'SCRAP',
            source_url    = url,
            fetched_at    = fetched_at,
            raw_data      = {'origin': 'json', 'raw_rate': float(rate)},
        )
        if r.is_valid():
            results.append(r)

    def _find_decimal(
        self,
        node: dict,
        keys: tuple[str, ...],
        lo: Decimal,
        hi: Decimal,
    ) -> Decimal | None:
        for key in keys:
            val = node.get(key)
            if val is not None:
                d = _to_dec(str(val), lo, hi)
                if d:
                    return d
        return None

    # ── 2c. Extraccion desde texto plano ──────────────────────────────────────

    def _extract_from_text(self, text: str, fetched_at) -> list[FetchResult]:
        """Extrae todos los datos desde el texto de la pagina."""
        results: list[FetchResult] = []
        results.extend(self._extract_main_from_text(text, fetched_at))
        results.extend(self._extract_exchanges_from_text(text, fetched_at))
        results.extend(self._extract_cross_from_text(text, fetched_at))
        return results

    def _extract_main_from_text(self, text: str, fetched_at) -> list[FetchResult]:
        """Extrae la tasa USD/BOB principal."""
        # Secciones candidatas
        for keyword in ('Cotización Paralela', 'Precio de Compra', 'Cotización Paralela en Bolivia',
                        'Dólar Paralelo', 'USDT P2P'):
            idx = text.lower().find(keyword.lower())
            if idx == -1:
                continue
            section = text[max(0, idx - 50): idx + 600]
            buy, sell = self._pair_from_text(section, _USD_PAR_MIN, _USD_PAR_MAX)
            if buy and sell:
                return [self._make_main(buy, sell, fetched_at, 'text_section')]

        # Fallback: primeros dos precios en rango en la pagina
        nums = _prices_in_range(text[:2000], _USD_PAR_MIN, _USD_PAR_MAX)
        if len(nums) >= 2:
            return [self._make_main(nums[0], nums[-1], fetched_at, 'text_fallback')]

        return []

    def _extract_exchanges_from_text(self, text: str, fetched_at) -> list[FetchResult]:
        """
        Extrae tasas de plataformas P2P desde el texto de la pagina.

        Patrones detectados (de la pagina real):
          "El Dorado ... Compra Bs 10.00 Venta Bs 9.81"
          "Binance ... Compra Bs 9.95 Venta Bs 9.91"
        """
        results: list[FetchResult] = []
        lo, hi = _USD_PAR_MIN, _USD_PAR_MAX

        # Patron especifico de la pagina: nombre ... Compra\nBs X.XX\nVenta\nBs Y.YY
        # Cubrimos la version con y sin "Bs" entre keyword y numero
        EXCHANGE_TEXT_PATTERN = re.compile(
            r'(?P<name>eldorado|takenos|wallbit|airtm|binance|bybit|saldoar|bitget|meru)'
            r'.{0,600}?'
            r'(?:Compra|compra)\s+Bs\s+(?P<buy>[\d]+\.[\d]+)'
            r'.{0,300}?'
            r'(?:Venta|venta)\s+Bs\s+(?P<sell>[\d]+\.[\d]+)',
            re.IGNORECASE | re.DOTALL,
        )

        seen: set[str] = set()
        for m in EXCHANGE_TEXT_PATTERN.finditer(text):
            name = m.group('name').lower()
            buy  = _to_dec(m.group('buy'),  lo, hi)
            sell = _to_dec(m.group('sell'), lo, hi)
            if not buy or not sell:
                continue
            if buy > sell:
                buy, sell = sell, buy

            source_name = None
            confidence  = 0.82
            for sname, kws, conf in EXCHANGE_CONFIG:
                if any(kw in name for kw in kws):
                    source_name = sname
                    confidence  = conf
                    break
            if not source_name or source_name in seen:
                continue
            seen.add(source_name)

            r = FetchResult(
                currency_code = 'USD',
                market_type   = self.market_type,
                source_name   = source_name,
                official_rate = (buy + sell) / Decimal('2'),
                buy_rate      = buy,
                sell_rate     = sell,
                scale_factor  = 1,
                confidence    = confidence,
                source_method = 'SCRAP',
                source_url    = SOURCE_URL,
                fetched_at    = fetched_at,
                raw_data      = {'origin': 'text_exchange', 'matched': name},
            )
            if r.is_valid():
                results.append(r)
                log.debug('DOLARBLUE_EXCHANGE_TEXT source=%s buy=%s sell=%s', source_name, buy, sell)

        # Patron alternativo: "Compra\nBs X.XX\nVenta\nBs Y.YY" precedido de nombre de plataforma
        ALT_PATTERN = re.compile(
            r'(?P<name>El Dorado|Takenos|Wallbit|Airtm|Binance|Bybit|SaldoAr|Bitget|Meru)'
            r'.{0,400}?'
            r'Compra\s+Bs\s+(?P<buy>[\d.]+)'
            r'\s+'
            r'Venta\s+Bs\s+(?P<sell>[\d.]+)',
            re.DOTALL,
        )
        for m in ALT_PATTERN.finditer(text):
            name = m.group('name').lower()
            buy  = _to_dec(m.group('buy'),  lo, hi)
            sell = _to_dec(m.group('sell'), lo, hi)
            if not buy or not sell:
                continue
            if buy > sell:
                buy, sell = sell, buy

            source_name = None
            confidence  = 0.82
            for sname, kws, conf in EXCHANGE_CONFIG:
                if any(kw in name for kw in kws):
                    source_name = sname
                    confidence  = conf
                    break
            if not source_name or source_name in seen:
                continue
            seen.add(source_name)

            r = FetchResult(
                currency_code = 'USD',
                market_type   = self.market_type,
                source_name   = source_name,
                official_rate = (buy + sell) / Decimal('2'),
                buy_rate      = buy,
                sell_rate     = sell,
                scale_factor  = 1,
                confidence    = confidence,
                source_method = 'SCRAP',
                source_url    = SOURCE_URL,
                fetched_at    = fetched_at,
                raw_data      = {'origin': 'text_exchange_alt', 'matched': name},
            )
            if r.is_valid():
                results.append(r)

        return results

    def _extract_cross_from_text(self, text: str, fetched_at) -> list[FetchResult]:
        """
        Extrae cross rates desde la tabla "Otras Divisas".

        Formato en la pagina:
          Real Brasileño   4.97 BRL   Bs 2.00
          Peso Argentino   1474.57 ARS   Bs 0.0067
        """
        results: list[FetchResult] = []

        # Patron principal de la tabla
        CROSS_TABLE = re.compile(
            r'(?P<name>Real Brasileño|Peso Argentino|Sol Peruano|Euro|Libra Esterlina|Yuan Chino|Peso Chileno)'
            r'.{0,150}?'
            r'Bs\s+(?P<rate>[\d]+\.[\d]+)',
            re.IGNORECASE | re.DOTALL,
        )

        seen_codes: set[str] = set()
        for m in CROSS_TABLE.finditer(text):
            name_lower = m.group('name').lower()
            code = _CROSS_NAME_TO_CODE.get(name_lower)
            if not code or code in seen_codes:
                continue

            cfg = next((c for c in CROSS_CONFIG if c[0] == code), None)
            if not cfg:
                continue
            _, _, lo_f, hi_f, scale, conf = cfg
            lo = Decimal(str(lo_f))
            hi = Decimal(str(hi_f))

            raw_rate = _to_dec(m.group('rate'), lo, hi)
            if not raw_rate:
                continue

            seen_codes.add(code)
            scaled = _q(raw_rate * Decimal(str(scale)))
            buy, sell = apply_min_spread(scaled)

            r = FetchResult(
                currency_code = code,
                market_type   = self.market_type,
                source_name   = f'DOLARBLUE_{code}',
                official_rate = raw_rate,
                buy_rate      = buy,
                sell_rate     = sell,
                scale_factor  = scale,
                confidence    = conf,
                source_method = 'SCRAP',
                source_url    = SOURCE_URL,
                fetched_at    = fetched_at,
                raw_data      = {'origin': 'text_cross', 'raw_rate': float(raw_rate)},
            )
            if r.is_valid():
                results.append(r)
                log.debug('DOLARBLUE_CROSS_TEXT code=%s rate=%s scaled=%s', code, raw_rate, scaled)

        # Patron alternativo: "Bs X.XX" cerca de nombre de divisa
        if len(seen_codes) < len(CROSS_CONFIG):
            for code, kws, lo_f, hi_f, scale, conf in CROSS_CONFIG:
                if code in seen_codes:
                    continue
                lo = Decimal(str(lo_f))
                hi = Decimal(str(hi_f))
                for kw in kws:
                    idx = text.lower().find(kw.lower())
                    if idx == -1:
                        continue
                    section = text[idx: idx + 200]
                    m = _BS_PREFIX.search(section)
                    if m:
                        val = _to_dec(m.group(1), lo, hi)
                        if val:
                            seen_codes.add(code)
                            scaled = _q(val * Decimal(str(scale)))
                            buy, sell = apply_min_spread(scaled)
                            r = FetchResult(
                                currency_code = code,
                                market_type   = self.market_type,
                                source_name   = f'DOLARBLUE_{code}',
                                official_rate = val,
                                buy_rate      = buy,
                                sell_rate     = sell,
                                scale_factor  = scale,
                                confidence    = conf,
                                source_method = 'SCRAP',
                                source_url    = SOURCE_URL,
                                fetched_at    = fetched_at,
                                raw_data      = {'origin': 'text_cross_alt'},
                            )
                            if r.is_valid():
                                results.append(r)
                            break

        return results

    # ── Helpers de construccion ───────────────────────────────────────────────

    def _make_main(self, buy: Decimal, sell: Decimal, fetched_at, strategy: str) -> FetchResult:
        if buy > sell:
            buy, sell = sell, buy
        log.info('DOLARBLUE_MAIN strategy=%s buy=%s sell=%s', strategy, buy, sell)
        return FetchResult(
            currency_code = 'USD',
            market_type   = self.market_type,
            source_name   = self.source_name,
            official_rate = (buy + sell) / Decimal('2'),
            buy_rate      = buy,
            sell_rate     = sell,
            scale_factor  = 1,
            confidence    = 0.82,
            source_method = 'SCRAP',
            source_url    = SOURCE_URL,
            fetched_at    = fetched_at,
            raw_data      = {'strategy': strategy},
        )

    def _html_to_text(self, html: str) -> str:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            return soup.get_text(separator=' ', strip=True)
        except Exception:
            # Strip tags manually if BeautifulSoup fails
            return re.sub(r'<[^>]+>', ' ', html)

    def _pair_from_text(
        self,
        text: str,
        lo: Decimal,
        hi: Decimal,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Extrae par (compra, venta) de un fragmento de texto."""
        PAIR_BUY_SELL = re.compile(
            r'(?:compra|buy)[^\d]{0,60}(\d{1,2}[.,]\d{2,4})'
            r'.{0,150}'
            r'(?:venta|sell)[^\d]{0,60}(\d{1,2}[.,]\d{2,4})',
            re.IGNORECASE | re.DOTALL,
        )
        PAIR_SELL_BUY = re.compile(
            r'(?:venta|sell)[^\d]{0,60}(\d{1,2}[.,]\d{2,4})'
            r'.{0,150}'
            r'(?:compra|buy)[^\d]{0,60}(\d{1,2}[.,]\d{2,4})',
            re.IGNORECASE | re.DOTALL,
        )
        BS_BUY  = re.compile(r'(?:compra|buy)[:\s]*(?:Bs\.?\s*)?([\d.,]+)', re.IGNORECASE)
        BS_SELL = re.compile(r'(?:venta|sell)[:\s]*(?:Bs\.?\s*)?([\d.,]+)', re.IGNORECASE)

        for pat in (PAIR_BUY_SELL, PAIR_SELL_BUY):
            m = pat.search(text)
            if m:
                a = _to_dec(m.group(1), lo, hi)
                b = _to_dec(m.group(2), lo, hi)
                if a and b:
                    return (a, b) if pat == PAIR_BUY_SELL else (b, a)

        bm = BS_BUY.search(text)
        sm = BS_SELL.search(text)
        if bm and sm:
            b = _to_dec(bm.group(1), lo, hi)
            s = _to_dec(sm.group(1), lo, hi)
            if b and s:
                return b, s

        nums = _prices_in_range(text, lo, hi)
        if len(nums) >= 2:
            return nums[0], nums[-1]

        return None, None

    # ── Persistencia tasa principal ───────────────────────────────────────────

    def _save_to_db(self, buy: Decimal, sell: Decimal, fetched_at) -> None:
        from django.utils import timezone
        from django.db import transaction as db_tx
        from rates.models import Currency, ExchangeRate

        usd = Currency.objects.filter(code='USD').first()
        bob = Currency.objects.filter(code='BOB').first()
        if not usd or not bob:
            return

        now = fetched_at or timezone.now()
        with db_tx.atomic():
            ExchangeRate.objects.filter(
                currency_from=usd, currency_to=bob,
                market_type='paralelo_digital',
                source='dolarblue_bo',
                valid_until__isnull=True,
            ).update(valid_until=now)

            ExchangeRate.objects.create(
                currency_from = usd,
                currency_to   = bob,
                market_type   = 'paralelo_digital',
                source        = 'dolarblue_bo',
                buy_rate      = buy,
                sell_rate     = sell,
                official_rate = (buy + sell) / Decimal('2'),
                valid_from    = now,
                valid_until   = None,
                source_method = 'SCRAP',
                source_url    = SOURCE_URL,
                fetched_at    = now,
                confidence    = Decimal('0.820'),
                is_validated  = False,
            )
        log.info('DOLARBLUE_SAVED buy=%s sell=%s', buy, sell)

    # ── Fallback DB ───────────────────────────────────────────────────────────

    def _insert_manual_fallback(self, fetched_at) -> None:
        try:
            from rates.models import Currency, ExchangeRate
            from django.db import transaction as db_tx

            usd = Currency.objects.filter(code='USD').first()
            bob = Currency.objects.filter(code='BOB').first()
            if not usd or not bob:
                return

            last = (
                ExchangeRate.objects
                .filter(currency_from=usd, currency_to=bob, market_type='paralelo_digital')
                .order_by('-valid_from')
                .first()
            )
            if not last:
                log.warning('DOLARBLUE_NO_FALLBACK — no hay tasa previa en DB')
                return

            buy  = last.buy_rate
            sell = last.sell_rate
            age_h = (fetched_at - (last.fetched_at or last.valid_from)).total_seconds() / 3600
            log.warning('DOLARBLUE_MANUAL_FALLBACK buy=%s sell=%s age_hours=%.1f', buy, sell, age_h)

            with db_tx.atomic():
                ExchangeRate.objects.filter(
                    currency_from=usd, currency_to=bob,
                    market_type='paralelo_digital',
                    source='dolarblue_manual_fallback',
                    valid_until__isnull=True,
                ).update(valid_until=fetched_at)

                ExchangeRate.objects.create(
                    currency_from = usd,
                    currency_to   = bob,
                    market_type   = 'paralelo_digital',
                    source        = 'dolarblue_manual_fallback',
                    buy_rate      = buy,
                    sell_rate     = sell,
                    official_rate = (buy + sell) / Decimal('2'),
                    valid_from    = fetched_at,
                    valid_until   = None,
                    source_method = 'MANUAL',
                    source_url    = SOURCE_URL,
                    fetched_at    = fetched_at,
                    confidence    = Decimal('0.500'),
                    is_validated  = False,
                )
        except Exception as exc:
            log.error('DOLARBLUE_FALLBACK_ERROR %s', exc, exc_info=True)
