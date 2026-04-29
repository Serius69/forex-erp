"""
Motor de tasas de cambio — orquesta fuentes reales y detecta anomalías.

Prioridad de fuentes:
  1. Binance P2P      — API real, confidence 0.95
  2. DolarBlueBolivia — scraping, confidence 0.80
  3. DB paralelo_digital cache — datos previos guardados
  4. BCB referencial  — solo como baseline, NO para transacciones

Anomalías detectadas:
  - Spread > MAX_SPREAD_PCT (8%)
  - Desviación entre Binance y DolarBlue > MAX_DEVIATION_PCT (5%)
  - Datos más viejos que STALE_MINUTES (30 min)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import timedelta
from typing import Optional

from django.utils import timezone

log = logging.getLogger('kapitalya.rates.engine')

# ── Umbrales de anomalía ──────────────────────────────────────────────────────
MAX_SPREAD_PCT    = Decimal('8.0')   # Alerta si spread > 8%
MAX_DEVIATION_PCT = Decimal('5.0')   # Alerta si desviación entre fuentes > 5%
STALE_MINUTES     = 30               # Datos considerados obsoletos pasado este tiempo
BINANCE_P2P_URL   = 'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'


@dataclass
class RateResult:
    """Resultado normalizado del motor de tasas."""
    pair:        str                       # e.g. 'USD/BOB'
    buy:         Decimal
    sell:        Decimal
    spread:      Decimal                   # sell - buy
    spread_pct:  Decimal                   # (sell-buy)/buy * 100
    source:      str                       # 'binance' | 'dolarblue' | 'db_cache' | 'bcb_ref'
    source_url:  Optional[str]
    confidence:  Decimal                   # 0.00 – 1.00
    timestamp:   object                    # datetime UTC
    is_live:     bool = True               # False = servido desde DB cache
    anomalies:   list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'pair':        self.pair,
            'buy':         float(self.buy),
            'sell':        float(self.sell),
            'spread':      float(self.spread),
            'spread_pct':  float(self.spread_pct),
            'source':      self.source,
            'source_url':  self.source_url,
            'confidence':  float(self.confidence),
            'timestamp':   self.timestamp.isoformat() if self.timestamp else None,
            'is_live':     self.is_live,
            'anomalies':   self.anomalies,
        }


class RateEngine:
    """
    Motor principal de tasas de cambio.

    Uso:
        engine = RateEngine()
        result = engine.get_best_rate('USD')
        print(result.to_dict())
    """

    # Orden de prioridad de fuentes (mayor índice = menor prioridad)
    SOURCE_PRIORITY = ['binance', 'dolarblue', 'db_cache', 'bcb_ref']

    def get_best_rate(self, currency: str = 'USD') -> RateResult | None:
        """
        Obtiene la mejor tasa disponible para la divisa dada.
        Intenta fuentes en orden de prioridad hasta obtener un resultado.
        """
        currency = currency.upper()

        # 1. Binance P2P — API real
        result = self._try_binance(currency)
        if result:
            result.anomalies = self._detect_anomalies(result)
            log.info('ENGINE_RATE source=binance currency=%s buy=%s sell=%s',
                     currency, result.buy, result.sell)
            return result

        # 2. DolarBlueBolivia — scraping
        result = self._try_dolar_blue(currency)
        if result:
            result.anomalies = self._detect_anomalies(result)
            log.info('ENGINE_RATE source=dolarblue currency=%s buy=%s sell=%s',
                     currency, result.buy, result.sell)
            return result

        # 3. DB cache — última tasa paralelo_digital guardada
        result = self._try_db_cache(currency)
        if result:
            result.anomalies = self._detect_anomalies(result)
            log.info('ENGINE_RATE source=db_cache currency=%s buy=%s sell=%s',
                     currency, result.buy, result.sell)
            return result

        # 4. BCB referencial — solo baseline
        result = self._try_bcb_ref(currency)
        if result:
            result.anomalies = self._detect_anomalies(result)
            log.warning('ENGINE_RATE source=bcb_ref currency=%s — all live sources failed',
                        currency)
            return result

        log.error('ENGINE_NO_RATE currency=%s — all sources exhausted', currency)
        return None

    def get_all_rates(self) -> dict[str, RateResult]:
        """Obtiene la mejor tasa para cada divisa activa."""
        from rates.models import Currency
        currencies = Currency.objects.filter(is_active=True).exclude(code='BOB')
        results = {}
        for cur in currencies:
            rate = self.get_best_rate(cur.code)
            if rate:
                results[cur.code] = rate
        return results

    # ------------------------------------------------------------------ #
    #  Fuentes individuales                                                 #
    # ------------------------------------------------------------------ #

    def _try_binance(self, currency: str) -> RateResult | None:
        if currency != 'USD':
            return None  # Binance P2P sólo USDT/BOB (equivalente USD/BOB)
        try:
            from rates.fetchers.binance_p2p import fetch_binance_p2p
            data = fetch_binance_p2p()
            buy  = Decimal(str(data['buy']))
            sell = Decimal(str(data['sell']))
            return self._build_result(
                currency   = currency,
                buy        = buy,
                sell       = sell,
                source     = 'binance',
                source_url = BINANCE_P2P_URL,
                confidence = Decimal('0.950'),
                timestamp  = data.get('fetched_at') or timezone.now(),
                is_live    = not data.get('from_cache', False),
            )
        except Exception as exc:
            log.warning('ENGINE_BINANCE_FAIL currency=%s error=%s', currency, exc)
            return None

    def _try_dolar_blue(self, currency: str) -> RateResult | None:
        if currency != 'USD':
            return None  # dolarbluebolivia.click solo publica USD/BOB
        try:
            from rates.fetchers.dolar_blue_bolivia import DolarBlueBoliviaFetcher, SOURCE_URL
            results = DolarBlueBoliviaFetcher().fetch()
            if not results:
                return None
            r = results[0]
            return self._build_result(
                currency   = currency,
                buy        = r.buy_rate,
                sell       = r.sell_rate,
                source     = 'dolarblue',
                source_url = SOURCE_URL,
                confidence = Decimal(str(r.confidence)),
                timestamp  = r.fetched_at or timezone.now(),
                is_live    = True,
            )
        except Exception as exc:
            log.warning('ENGINE_DOLARBLUE_FAIL currency=%s error=%s', currency, exc)
            return None

    def _try_db_cache(self, currency: str) -> RateResult | None:
        """Lee la tasa más reciente de paralelo_digital desde la DB."""
        try:
            from rates.models import Currency, ExchangeRate
            cur = Currency.objects.get(code=currency)
            bob = Currency.objects.get(code='BOB')

            # Preferir paralelo_digital, luego cualquier paralelo
            for market in ('paralelo_digital', 'parallel', 'digital'):
                rate = (
                    ExchangeRate.objects
                    .filter(
                        currency_from       = cur,
                        currency_to         = bob,
                        market_type         = market,
                        valid_until__isnull = True,
                    )
                    .order_by('-valid_from')
                    .first()
                )
                if rate:
                    return self._build_result(
                        currency   = currency,
                        buy        = rate.buy_rate,
                        sell       = rate.sell_rate,
                        source     = rate.source or 'db_cache',
                        source_url = rate.source_url,
                        confidence = Decimal(str(rate.confidence)) * Decimal('0.90'),
                        timestamp  = rate.fetched_at or rate.valid_from,
                        is_live    = False,
                    )
        except Exception as exc:
            log.warning('ENGINE_DB_CACHE_FAIL currency=%s error=%s', currency, exc)
        return None

    def _try_bcb_ref(self, currency: str) -> RateResult | None:
        """BCB referencial — sólo como último recurso, confidence muy baja."""
        BCB_REF = {
            'USD': Decimal('6.96'), 'EUR': Decimal('7.52'),
            'BRL': Decimal('1.22'), 'ARS': Decimal('0.007'),
            'CLP': Decimal('0.0076'), 'PEN': Decimal('1.85'),
        }
        ref = BCB_REF.get(currency)
        if ref is None:
            return None

        return self._build_result(
            currency   = currency,
            buy        = ref,
            sell       = ref,
            source     = 'bcb_ref',
            source_url = 'https://www.bcb.gob.bo/',
            confidence = Decimal('0.400'),
            timestamp  = timezone.now(),
            is_live    = False,
        )

    # ------------------------------------------------------------------ #
    #  Construcción de resultado                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_result(
        currency: str, buy: Decimal, sell: Decimal,
        source: str, source_url: str | None,
        confidence: Decimal, timestamp, is_live: bool,
    ) -> RateResult:
        spread     = sell - buy
        spread_pct = (spread / buy * 100) if buy else Decimal('0')
        return RateResult(
            pair       = f'{currency}/BOB',
            buy        = buy,
            sell       = sell,
            spread     = spread.quantize(Decimal('0.0001')),
            spread_pct = spread_pct.quantize(Decimal('0.01')),
            source     = source,
            source_url = source_url,
            confidence = min(confidence, Decimal('1.000')),
            timestamp  = timestamp,
            is_live    = is_live,
        )

    # ------------------------------------------------------------------ #
    #  Detección de anomalías                                               #
    # ------------------------------------------------------------------ #

    def _detect_anomalies(self, rate: RateResult) -> list[dict]:
        anomalies = []

        # 1. Spread demasiado alto
        if rate.spread_pct > MAX_SPREAD_PCT:
            anomalies.append({
                'type':      'HIGH_SPREAD',
                'severity':  'WARNING',
                'message':   f'Spread {rate.spread_pct:.2f}% supera el umbral de {MAX_SPREAD_PCT}%',
                'value':     float(rate.spread_pct),
                'threshold': float(MAX_SPREAD_PCT),
            })

        # 2. Spread negativo (buy > sell — datos corruptos)
        if rate.buy > rate.sell:
            anomalies.append({
                'type':    'NEGATIVE_SPREAD',
                'severity': 'CRITICAL',
                'message': 'Tasa de compra mayor que venta — dato corrupto',
                'value':   float(rate.buy - rate.sell),
            })

        # 3. Datos obsoletos
        if rate.timestamp:
            age_minutes = (timezone.now() - rate.timestamp).total_seconds() / 60
            if age_minutes > STALE_MINUTES:
                anomalies.append({
                    'type':      'STALE_DATA',
                    'severity':  'WARNING',
                    'message':   f'Dato tiene {age_minutes:.0f} minutos — umbral {STALE_MINUTES} min',
                    'value':     float(age_minutes),
                    'threshold': STALE_MINUTES,
                })

        # 4. Confianza baja
        if rate.confidence < Decimal('0.70'):
            anomalies.append({
                'type':      'LOW_CONFIDENCE',
                'severity':  'INFO',
                'message':   f'Confianza {float(rate.confidence)*100:.0f}% — se recomienda validación',
                'value':     float(rate.confidence),
                'threshold': 0.70,
            })

        # 5. Desviación excesiva vs Binance (solo para fuentes no-Binance)
        if rate.source != 'binance':
            binance_ref = self._get_binance_from_db('USD')
            if binance_ref and rate.pair == 'USD/BOB':
                deviation = abs(rate.buy - binance_ref) / binance_ref * 100
                if deviation > MAX_DEVIATION_PCT:
                    anomalies.append({
                        'type':      'BINANCE_DEVIATION',
                        'severity':  'WARNING',
                        'message':   (
                            f'Desviación de {deviation:.2f}% vs Binance P2P '
                            f'({float(binance_ref):.4f}) — umbral {MAX_DEVIATION_PCT}%'
                        ),
                        'value':     float(deviation),
                        'threshold': float(MAX_DEVIATION_PCT),
                        'binance_buy': float(binance_ref),
                    })

        return anomalies

    @staticmethod
    def _get_binance_from_db(currency: str) -> Decimal | None:
        """Lee la última tasa de Binance P2P guardada en DB (sin fetch en vivo)."""
        try:
            from rates.models import Currency, ExchangeRate
            usd = Currency.objects.get(code=currency)
            bob = Currency.objects.get(code='BOB')
            r = (
                ExchangeRate.objects
                .filter(
                    currency_from       = usd,
                    currency_to         = bob,
                    market_type         = 'paralelo_digital',
                    source              = 'binance_p2p',
                    valid_until__isnull = True,
                )
                .order_by('-valid_from')
                .first()
            )
            return r.buy_rate if r else None
        except Exception:
            return None
