"""
Binance P2P fetcher — USDT/BOB → USD/BOB

Endpoint oficial de Binance P2P:
  POST https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search

Lógica:
  1. Consulta anunciantes de COMPRA (tipo SELL desde perspectiva del mercado)
     y VENTA (BUY) de USDT contra BOB.
  2. Calcula precio mediano de los primeros N anuncios.
  3. USDT ≈ 1 USD (stablecoin), por lo que precio es prácticamente USD/BOB.
  4. Guarda como market_type='paralelo_digital', source='binance_p2p'.
  5. Cachea resultado 5 minutos para no saturar la API.
"""
import logging
import requests
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger('kapitalya.rates.binance')

BINANCE_P2P_URL = 'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'
CACHE_KEY       = 'binance_p2p_usd_bob'
CACHE_TTL       = 300   # 5 minutos
TOP_N           = 10    # Usar los primeros 10 anuncios para el precio mediano
TIMEOUT         = 15    # segundos

_HEADERS = {
    'Content-Type':  'application/json',
    'User-Agent':    'Mozilla/5.0 (compatible; KapitalyaERP/1.0)',
    'Accept':        'application/json',
}


def _fetch_side(trade_type: str, fiat: str = 'BOB', asset: str = 'USDT') -> list[float]:
    """
    trade_type: 'BUY'  → anuncios donde el anunciante compra USDT con BOB
                           (= alguien dispuesto a vender BOB por USDT → precio compra)
                'SELL' → anuncios donde el anunciante vende USDT por BOB
                           (= alguien dispuesto a comprar BOB → precio venta)
    Devuelve lista de precios (float) de los primeros TOP_N anuncios.
    """
    payload = {
        'asset':         asset,
        'fiat':          fiat,
        'merchantCheck': False,
        'page':          1,
        'payTypes':      [],
        'publisherType': None,
        'rows':          TOP_N,
        'tradeType':     trade_type,
    }
    resp = requests.post(BINANCE_P2P_URL, json=payload, headers=_HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    ads = data.get('data', [])
    prices = []
    for ad in ads:
        try:
            price = float(ad['adv']['price'])
            if price > 0:
                prices.append(price)
        except (KeyError, TypeError, ValueError):
            continue
    return prices


def fetch_binance_p2p() -> dict:
    """
    Obtiene precio USDT/BOB desde Binance P2P y lo guarda en la DB.

    Trazabilidad: source_method='API', source_url=BINANCE_P2P_URL, confidence=0.95.

    Retorna:
        {
          'buy':          Decimal,
          'sell':         Decimal,
          'official':     Decimal,
          'source':       'binance_p2p',
          'source_method':'API',
          'source_url':   str,
          'from_cache':   bool,
        }
    o lanza excepción en caso de fallo.
    """
    cached = cache.get(CACHE_KEY)
    if cached:
        log.debug('BINANCE_P2P from cache')
        return {**cached, 'from_cache': True}

    log.info('BINANCE_P2P fetching live data')

    fetched_at = timezone.now()

    # Anuncios SELL (anunciante vende USDT) → usuario compra USDT → precio más alto = sell
    sell_prices = _fetch_side('SELL')
    # Anuncios BUY  (anunciante compra USDT) → usuario vende USDT → precio más bajo = buy
    buy_prices  = _fetch_side('BUY')

    if not sell_prices or not buy_prices:
        raise ValueError('Binance P2P devolvió lista vacía de anuncios')

    sell_price = Decimal(str(round(median(sell_prices), 4)))
    buy_price  = Decimal(str(round(median(buy_prices),  4)))

    result = {
        'buy':           buy_price,
        'sell':          sell_price,
        'official':      buy_price,
        'source':        'binance_p2p',
        'source_method': 'API',
        'source_url':    BINANCE_P2P_URL,
        'fetched_at':    fetched_at,
        'from_cache':    False,
    }

    cache.set(CACHE_KEY, result, CACHE_TTL)
    _save_to_db(buy_price, sell_price, fetched_at=fetched_at)

    log.info('BINANCE_P2P fetched buy=%s sell=%s', buy_price, sell_price)
    return result


def _save_to_db(buy_rate: Decimal, sell_rate: Decimal, fetched_at=None) -> None:
    """
    Persiste la tasa en ExchangeRate como paralelo_digital con trazabilidad completa.
    source_method='API' — Binance P2P es una API REST pública, dato en tiempo real.
    """
    try:
        from rates.models import Currency, ExchangeRate
        from django.db import transaction as db_tx

        usd = Currency.objects.filter(code='USD').first()
        bob = Currency.objects.filter(code='BOB').first()
        if not usd or not bob:
            log.error('BINANCE_P2P_SAVE_SKIP missing USD or BOB currency')
            return

        now = fetched_at or timezone.now()

        with db_tx.atomic():
            ExchangeRate.objects.filter(
                currency_from=usd,
                currency_to=bob,
                market_type='paralelo_digital',
                source='binance_p2p',
                valid_until__isnull=True,
            ).update(valid_until=now)

            ExchangeRate.objects.create(
                currency_from = usd,
                currency_to   = bob,
                market_type   = 'paralelo_digital',
                source        = 'binance_p2p',
                buy_rate      = buy_rate,
                sell_rate     = sell_rate,
                official_rate = buy_rate,
                valid_from    = now,
                valid_until   = None,
                # ── Trazabilidad ──────────────────────────────────────────────
                source_method = 'API',
                source_url    = BINANCE_P2P_URL,
                fetched_at    = now,
                confidence    = Decimal('0.950'),
                is_validated  = False,
            )
        log.info('BINANCE_P2P_SAVED buy=%s sell=%s method=API', buy_rate, sell_rate)

    except Exception as exc:
        log.error('BINANCE_P2P_SAVE_ERROR %s', exc, exc_info=True)
