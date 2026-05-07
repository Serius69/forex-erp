"""
Binance P2P — fetcher multi-fiat para la capa integrations/.

Un solo fetcher itera todos los fiats configurados: BOB, ARS, CLP, PEN, BRL, EUR.
Precio = mediana de las primeras 5 ofertas de cada lado (BUY/SELL).
USDT ≈ USD 1:1 (stablecoin).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as tz
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from typing import Optional

from rates.integrations.base import AbstractRateFetcher
from rates.schemas import NormalizedRate

log = logging.getLogger('kapitalya.integrations.binance_p2p')

BINANCE_P2P_URL = 'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'

# Cada fiat → moneda a reportar, escala (para ARS/CLP reportar por 1000)
FIAT_CONFIG: dict[str, dict] = {
    'BOB': {'moneda': 'USD', 'escala': Decimal('1')},
    'ARS': {'moneda': 'ARS', 'escala': Decimal('1000')},
    'CLP': {'moneda': 'CLP', 'escala': Decimal('1000')},
    'PEN': {'moneda': 'PEN', 'escala': Decimal('1')},
    'BRL': {'moneda': 'BRL', 'escala': Decimal('1')},
    'EUR': {'moneda': 'EUR', 'escala': Decimal('1')},
}

TOP_N    = 5
ASSET    = 'USDT'
_Q8      = Decimal('0.00000001')


class BinanceP2PMultiFetcher(AbstractRateFetcher):
    id_fuente       = 'binance_p2p_bob'   # slug base (el registry ya diferencia por fiat)
    tipo_fuente     = 'P2P'
    pares_soportados = [
        ('USD', 'BOB'), ('ARS', 'BOB'), ('CLP', 'BOB'),
        ('PEN', 'BOB'), ('BRL', 'BOB'), ('EUR', 'BOB'),
    ]

    def fetch(self) -> list[NormalizedRate]:
        session = self._get_session()
        session.headers['Content-Type'] = 'application/json'
        now = datetime.now(tz.utc)
        results: list[NormalizedRate] = []

        for fiat, cfg in FIAT_CONFIG.items():
            try:
                rate = self._fetch_pair(session, fiat, cfg, now)
                if rate:
                    results.append(rate)
            except Exception as exc:
                log.warning('BINANCE_P2P fiat=%s error=%s', fiat, exc)

        return results

    def _fetch_pair(
        self, session, fiat: str, cfg: dict, now: datetime,
    ) -> Optional[NormalizedRate]:
        moneda = cfg['moneda']
        escala = cfg['escala']

        # SELL = anunciante vende USDT → precio que paga el usuario (venta alta)
        sell_prices = self._fetch_side(session, 'SELL', fiat)
        # BUY  = anunciante compra USDT → precio que recibe el usuario (compra baja)
        buy_prices  = self._fetch_side(session, 'BUY',  fiat)

        if not sell_prices and not buy_prices:
            return None

        buy_prices  = sorted(buy_prices)[:TOP_N]
        sell_prices = sorted(sell_prices, reverse=True)[:TOP_N]

        raw_buy  = Decimal(str(round(median(buy_prices),  8))) if buy_prices  else None
        raw_sell = Decimal(str(round(median(sell_prices), 8))) if sell_prices else None

        if not raw_buy:
            raw_buy = (raw_sell * Decimal('0.995')).quantize(_Q8, ROUND_HALF_UP)
        if not raw_sell:
            raw_sell = (raw_buy * Decimal('1.005')).quantize(_Q8, ROUND_HALF_UP)

        if raw_buy >= raw_sell:
            mid      = (raw_buy + raw_sell) / 2
            raw_buy  = mid
            raw_sell = mid

        # Escalar para ARS/CLP: el precio de Binance ya es en esa fiat/USDT
        # Para ARS: precio = cuántos ARS compran 1 USDT → invertir → BOB/ARS
        # Aquí simplemente reportamos raw (BOB/ARS o CLP/BOB), el consenso normaliza
        if fiat != 'BOB':
            # precio_compra = cuántos BOB entrega la casa por escala unidades de moneda
            # cross: (1/raw_buy) * USD_BOB * escala — pero no tenemos USD_BOB aquí,
            # guardamos el precio raw para que el consenso lo cruce
            precio_compra = (Decimal('1') / raw_sell * escala).quantize(_Q8, ROUND_HALF_UP)
            precio_venta  = (Decimal('1') / raw_buy  * escala).quantize(_Q8, ROUND_HALF_UP)
        else:
            precio_compra = raw_buy
            precio_venta  = raw_sell

        if precio_compra > precio_venta:
            precio_compra, precio_venta = precio_venta, precio_compra

        id_fuente_slug = f'binance_p2p_{fiat.lower()}'
        return NormalizedRate(
            moneda_base      = moneda,
            moneda_cotizada  = 'BOB',
            precio           = precio_compra,
            precio_compra    = precio_compra,
            precio_venta     = precio_venta,
            spread_pct       = None,
            fuente           = id_fuente_slug,
            tipo_fuente      = self.tipo_fuente,
            timestamp        = now,
            payload_raw      = {
                'fiat':        fiat,
                'buy_prices':  [float(p) for p in buy_prices],
                'sell_prices': [float(p) for p in sell_prices],
                'escala':      float(escala),
            },
            confianza        = 95,
            es_valido        = True,
        )

    def _fetch_side(self, session, trade_type: str, fiat: str) -> list[float]:
        try:
            payload = {
                'asset':         ASSET,
                'fiat':          fiat,
                'merchantCheck': False,
                'page':          1,
                'payTypes':      [],
                'publisherType': None,
                'rows':          TOP_N * 2,
                'tradeType':     trade_type,
            }
            resp = session.post(BINANCE_P2P_URL, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            ads = resp.json().get('data', [])
            prices = []
            for ad in ads:
                try:
                    p = float(ad['adv']['price'])
                    if p > 0:
                        prices.append(p)
                except (KeyError, TypeError, ValueError):
                    continue
            return prices
        except Exception as exc:
            log.debug('BINANCE_P2P_SIDE fiat=%s side=%s error=%s', fiat, trade_type, exc)
            return []
