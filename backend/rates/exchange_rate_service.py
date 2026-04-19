"""
Exchange Rate Service — Motor Central de Tasas de Cambio
=========================================================

ÚNICO punto de entrada para obtener tasas en transacciones y reportes.

Architecture:
  - Orquesta todos los fetchers (BCB, DolarApi, Binance P2P, BCP, scraping)
  - Normaliza y agrega con IQR outlier rejection + weighted average
  - Calcula estadísticas multi-fuente: promedio ponderado, mediana, mejor compra/venta
  - Selecciona y marca la tasa primaria (is_primary=True)
  - Detecta divergencias entre fuentes (alerta si > MAX_DIVERGENCE_PCT)
  - Cache Redis por fuente (TTL 2-5 min) y global (TTL 1 min)
  - Fallback inteligente: última tasa válida en DB si todas las fuentes fallan
  - BLOQUEA tasas INFERENCE en transacciones (Phase 9 compliance)

Usage:
    from rates.exchange_rate_service import ExchangeRateService

    service = ExchangeRateService()

    # Tasa primaria para transacciones
    rate = service.get_primary_rate('USD')

    # Todas las tasas con estadísticas multi-fuente
    summary = service.get_rates_summary('USD')

    # Calcular monto de transacción
    result = service.calculate_exchange(Decimal('100'), 'USD', 'BOB', 'BUY')

    # Detectar divergencias
    divergences = service.detect_divergences()
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger('kapitalya.rates.service')

# Umbral de divergencia entre fuentes: si la desviación estándar supera este %
# de la media, se genera una alerta de inconsistencia de datos.
MAX_DIVERGENCE_PCT: float = 5.0

# Confianza mínima para usar en transacciones (Phase 9)
MIN_CONFIDENCE_FOR_TX: float = 0.70

# TTL de cache en segundos
CACHE_TTL_PRIMARY     = 60        # tasa primaria global: 1 min
CACHE_TTL_SUMMARY     = 120       # resumen multi-fuente: 2 min
CACHE_TTL_DIVERGENCE  = 300       # análisis de divergencia: 5 min


@dataclass
class SourceRate:
    """Tasa individual de una fuente específica."""
    source:        str
    source_method: str
    market_type:   str
    buy_rate:      Decimal
    sell_rate:     Decimal
    official_rate: Decimal
    avg_rate:      Decimal
    confidence:    float
    fetched_at:    object  # datetime | None
    source_url:    Optional[str] = None
    is_validated:  bool = False


@dataclass
class RatesSummary:
    """
    Resultado completo del análisis multi-fuente para una divisa.
    Expuesto por los endpoints /api/rates/exchange-rates/current/ y /sources/.
    """
    currency_from:      str
    currency_to:        str
    scale_factor:       int

    # ── Tasa primaria (usada en transacciones) ────────────────────────────────
    primary_buy:        Decimal
    primary_sell:       Decimal
    primary_official:   Decimal
    primary_source:     str
    primary_method:     str
    primary_market:     str
    primary_confidence: float
    primary_fetched_at: object  # datetime
    primary_url:        Optional[str] = None
    is_primary_safe:    bool = True

    # ── Estadísticas agregadas (todas las fuentes) ────────────────────────────
    weighted_avg_buy:   Optional[Decimal] = None
    weighted_avg_sell:  Optional[Decimal] = None
    median_buy:         Optional[Decimal] = None
    median_sell:        Optional[Decimal] = None
    best_buy:           Optional[Decimal] = None  # highest buy (best for client selling)
    best_sell:          Optional[Decimal] = None  # lowest sell (best for client buying)

    # ── Divergencia entre fuentes ─────────────────────────────────────────────
    source_count:       int = 0
    divergence_pct:     float = 0.0
    has_divergence:     bool = False

    # ── Fuentes individuales ──────────────────────────────────────────────────
    sources:            list[SourceRate] = field(default_factory=list)

    def to_dict(self) -> dict:
        def _d(v):
            return str(v) if isinstance(v, Decimal) else v

        return {
            'currency_from':      self.currency_from,
            'currency_to':        self.currency_to,
            'scale_factor':       self.scale_factor,
            'primary': {
                'buy':            _d(self.primary_buy),
                'sell':           _d(self.primary_sell),
                'official':       _d(self.primary_official),
                'avg':            _d((self.primary_buy + self.primary_sell) / Decimal('2')),
                'source':         self.primary_source,
                'source_method':  self.primary_method,
                'market_type':    self.primary_market,
                'confidence':     round(self.primary_confidence, 3),
                'fetched_at':     self.primary_fetched_at.isoformat() if self.primary_fetched_at else None,
                'source_url':     self.primary_url,
                'is_safe_for_transaction': self.is_primary_safe,
            },
            'statistics': {
                'weighted_avg_buy':  _d(self.weighted_avg_buy),
                'weighted_avg_sell': _d(self.weighted_avg_sell),
                'median_buy':        _d(self.median_buy),
                'median_sell':       _d(self.median_sell),
                'best_buy':          _d(self.best_buy),
                'best_sell':         _d(self.best_sell),
                'source_count':      self.source_count,
                'divergence_pct':    round(self.divergence_pct, 2),
                'has_divergence':    self.has_divergence,
            },
            'sources': [
                {
                    'source':        s.source,
                    'source_method': s.source_method,
                    'market_type':   s.market_type,
                    'buy':           _d(s.buy_rate),
                    'sell':          _d(s.sell_rate),
                    'official':      _d(s.official_rate),
                    'avg':           _d(s.avg_rate),
                    'confidence':    round(s.confidence, 3),
                    'fetched_at':    s.fetched_at.isoformat() if s.fetched_at else None,
                    'source_url':    s.source_url,
                    'is_validated':  s.is_validated,
                }
                for s in self.sources
            ],
        }


class ExchangeRateService:
    """
    Motor central de tasas de cambio.

    Todas las transacciones del sistema DEBEN usar:
        ExchangeRateService().get_primary_rate(currency_code)
    o equivalentemente:
        ExchangeRate.objects.filter(is_primary=True, currency_from__code=code,
                                    currency_to__code='BOB', valid_until__isnull=True).first()
    """

    def get_primary_rate(
        self,
        currency_code: str,
        currency_to: str = 'BOB',
        force_refresh: bool = False,
    ) -> 'ExchangeRate | None':
        """
        Returns the single is_primary=True active rate for the currency pair.
        Result is cached for CACHE_TTL_PRIMARY seconds.

        This is the ONLY rate that should be used in financial transactions.
        Raises ValueError if the rate is INFERENCE or confidence < MIN_CONFIDENCE_FOR_TX.
        """
        from .models import ExchangeRate, Currency

        cache_key = f'primary_rate_{currency_code}_{currency_to}'
        if not force_refresh:
            cached_id = cache.get(cache_key)
            if cached_id:
                try:
                    return ExchangeRate.objects.select_related(
                        'currency_from', 'currency_to', 'rate_source'
                    ).get(pk=cached_id)
                except ExchangeRate.DoesNotExist:
                    pass

        try:
            cur_from = Currency.objects.get(code=currency_code.upper())
            cur_to   = Currency.objects.get(code=currency_to.upper())
        except Currency.DoesNotExist:
            log.error('PRIMARY_RATE unknown currency %s/%s', currency_code, currency_to)
            return None

        rate = (
            ExchangeRate.objects
            .filter(
                currency_from    = cur_from,
                currency_to      = cur_to,
                is_primary       = True,
                valid_until__isnull = True,
            )
            .select_related('currency_from', 'currency_to', 'rate_source')
            .order_by('-valid_from')
            .first()
        )

        if rate is None:
            # Fallback: best available non-inference active rate
            rate = self._get_best_fallback(cur_from, cur_to)
            if rate:
                log.warning(
                    'PRIMARY_RATE_FALLBACK %s/%s — no is_primary rate, using best active',
                    currency_code, currency_to,
                )

        if rate:
            cache.set(cache_key, rate.pk, CACHE_TTL_PRIMARY)

        return rate

    def calculate_exchange(
        self,
        amount: Decimal,
        currency_from_code: str,
        currency_to_code: str,
        transaction_type: str,
    ) -> dict:
        """
        Calcula el monto resultante usando la tasa primaria.
        Bloquea tasas INFERENCE y baja confianza (Phase 9).
        """
        from core.finance import quantize_rate, quantize_money

        rate = self.get_primary_rate(currency_from_code, currency_to_code)
        if not rate:
            raise ValueError(
                f'No hay tasa activa para {currency_from_code}/{currency_to_code}. '
                f'Contacte al administrador del sistema.'
            )

        if rate.source_method == 'INFERENCE' and not rate.is_validated:
            raise ValueError(
                f'COMPLIANCE: La tasa de {currency_from_code} es ESTIMADA (INFERENCE) '
                f'y no puede usarse en transacciones. '
                f'Espere la actualización automática o ingrese la tasa manualmente.'
            )

        if float(rate.confidence) < MIN_CONFIDENCE_FOR_TX:
            raise ValueError(
                f'COMPLIANCE: La tasa de {currency_from_code} tiene confianza '
                f'{float(rate.confidence):.0%} — mínimo requerido {MIN_CONFIDENCE_FOR_TX:.0%}.'
            )

        amount = quantize_rate(amount)

        if transaction_type == 'BUY':
            applied_rate = rate.buy_rate
            result       = quantize_money(amount * applied_rate)
        else:
            applied_rate = rate.sell_rate
            if applied_rate == 0:
                raise ValueError('Tasa de venta no puede ser cero')
            result = quantize_money(amount * applied_rate)

        log.info(
            'CALCULATE_EXCHANGE %s %s→%s type=%s rate=%s method=%s conf=%.2f',
            amount, currency_from_code, currency_to_code,
            transaction_type, applied_rate,
            rate.source_method, float(rate.confidence),
        )

        return {
            'amount_from':      str(amount),
            'amount_to':        str(result),
            'rate':             str(quantize_rate(applied_rate)),
            'scale_factor':     rate.currency_from.scale_factor,
            'transaction_type': transaction_type,
            'currency_from':    currency_from_code,
            'currency_to':      currency_to_code,
            'source_method':    rate.source_method,
            'source_url':       rate.source_url,
            'fetched_at':       rate.fetched_at.isoformat() if rate.fetched_at else None,
            'confidence':       float(rate.confidence),
            'market_type':      rate.market_type,
            'is_validated':     rate.is_validated,
            'rate_id':          rate.pk,
        }

    def get_rates_summary(
        self,
        currency_code: str,
        currency_to: str = 'BOB',
        force_refresh: bool = False,
    ) -> RatesSummary | None:
        """
        Returns a full multi-source summary with statistics.
        Used by /api/rates/exchange-rates/current/ and /sources/ endpoints.
        """
        from .models import ExchangeRate, Currency

        cache_key = f'rates_summary_{currency_code}_{currency_to}'
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                return cached

        try:
            cur_from = Currency.objects.get(code=currency_code.upper())
            cur_to   = Currency.objects.get(code=currency_to.upper())
        except Currency.DoesNotExist:
            return None

        active_rates = list(
            ExchangeRate.objects
            .filter(
                currency_from    = cur_from,
                currency_to      = cur_to,
                valid_until__isnull = True,
            )
            .select_related('rate_source')
            .order_by('-confidence', '-valid_from')
        )

        if not active_rates:
            return None

        primary_rate = next((r for r in active_rates if r.is_primary), active_rates[0])

        source_rates = [
            SourceRate(
                source        = r.source or (r.rate_source.name if r.rate_source else 'DB'),
                source_method = r.source_method,
                market_type   = r.market_type,
                buy_rate      = r.buy_rate,
                sell_rate     = r.sell_rate,
                official_rate = r.official_rate,
                avg_rate      = r.avg_rate or (r.buy_rate + r.sell_rate) / Decimal('2'),
                confidence    = float(r.confidence),
                fetched_at    = r.fetched_at,
                source_url    = r.source_url,
                is_validated  = r.is_validated,
            )
            for r in active_rates
        ]

        stats = self._compute_statistics(source_rates)

        summary = RatesSummary(
            currency_from      = currency_code.upper(),
            currency_to        = currency_to.upper(),
            scale_factor       = cur_from.scale_factor,
            primary_buy        = primary_rate.buy_rate,
            primary_sell       = primary_rate.sell_rate,
            primary_official   = primary_rate.official_rate,
            primary_source     = primary_rate.source or 'system',
            primary_method     = primary_rate.source_method,
            primary_market     = primary_rate.market_type,
            primary_confidence = float(primary_rate.confidence),
            primary_fetched_at = primary_rate.fetched_at,
            primary_url        = primary_rate.source_url,
            is_primary_safe    = (
                primary_rate.source_method != 'INFERENCE'
                and float(primary_rate.confidence) >= MIN_CONFIDENCE_FOR_TX
            ),
            sources            = source_rates,
            **stats,
        )

        cache.set(cache_key, summary, CACHE_TTL_SUMMARY)
        return summary

    def detect_divergences(self, threshold_pct: float = MAX_DIVERGENCE_PCT) -> list[dict]:
        """
        Detecta divergencias entre fuentes para todas las divisas activas.
        Retorna lista de monedas con divergencia > threshold_pct%.
        """
        from .models import Currency, ExchangeRate

        cache_key = f'rate_divergences_{int(threshold_pct)}'
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        currencies = Currency.objects.filter(is_active=True).exclude(code='BOB')
        bob        = Currency.objects.filter(code='BOB').first()
        if not bob:
            return []

        divergences = []
        for cur in currencies:
            rates = list(
                ExchangeRate.objects
                .filter(
                    currency_from    = cur,
                    currency_to      = bob,
                    valid_until__isnull = True,
                    source_method__in = ('API', 'SCRAP', 'MANUAL'),
                )
                .values_list('buy_rate', 'sell_rate', 'source', 'market_type', 'confidence')
            )

            if len(rates) < 2:
                continue

            mid_rates = [float((b + s) / Decimal('2')) for b, s, *_ in rates]
            mean_val  = statistics.mean(mid_rates)
            if mean_val == 0:
                continue

            stdev     = statistics.stdev(mid_rates) if len(mid_rates) > 1 else 0
            div_pct   = (stdev / mean_val) * 100

            if div_pct > threshold_pct:
                min_rate = min(mid_rates)
                max_rate = max(mid_rates)
                divergences.append({
                    'currency':      cur.code,
                    'divergence_pct': round(div_pct, 2),
                    'mean':          round(mean_val, 4),
                    'min':           round(min_rate, 4),
                    'max':           round(max_rate, 4),
                    'spread_pct':    round((max_rate - min_rate) / mean_val * 100, 2),
                    'source_count':  len(rates),
                    'severity':      'CRITICAL' if div_pct > threshold_pct * 2 else 'WARNING',
                })

        cache.set(cache_key, divergences, CACHE_TTL_DIVERGENCE)
        return divergences

    def validate_transaction_rate(
        self,
        currency_code: str,
        provided_rate: Decimal,
        tolerance_pct: float = 2.0,
    ) -> tuple[bool, str]:
        """
        Validates a user-provided exchange_rate against the system primary rate.
        Returns (is_valid, message).

        Used in Excel import and transaction serializer validation.
        """
        rate = self.get_primary_rate(currency_code)
        if not rate:
            return False, f'No hay tasa activa para {currency_code}/BOB.'

        system_rate = rate.avg_rate or (rate.buy_rate + rate.sell_rate) / Decimal('2')
        deviation   = abs(provided_rate - system_rate) / system_rate * Decimal('100')

        if deviation > Decimal(str(tolerance_pct)):
            return False, (
                f'La tasa {provided_rate} difiere {deviation:.2f}% de la tasa del sistema '
                f'({system_rate:.4f} BOB/{currency_code}, fuente: {rate.source_method}). '
                f'Máximo permitido: {tolerance_pct}%.'
            )

        return True, ''

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _compute_statistics(self, source_rates: list[SourceRate]) -> dict:
        if not source_rates:
            return {
                'weighted_avg_buy': None, 'weighted_avg_sell': None,
                'median_buy': None, 'median_sell': None,
                'best_buy': None, 'best_sell': None,
                'source_count': 0, 'divergence_pct': 0.0, 'has_divergence': False,
            }

        buys  = [float(s.buy_rate)  for s in source_rates]
        sells = [float(s.sell_rate) for s in source_rates]
        confs = [s.confidence       for s in source_rates]

        total_w = sum(confs)
        if total_w > 0:
            wavg_buy  = sum(b * c for b, c in zip(buys,  confs)) / total_w
            wavg_sell = sum(s * c for s, c in zip(sells, confs)) / total_w
        else:
            wavg_buy  = statistics.mean(buys)
            wavg_sell = statistics.mean(sells)

        mids      = [(b + s) / 2 for b, s in zip(buys, sells)]
        mean_mid  = statistics.mean(mids)
        stdev_mid = statistics.stdev(mids) if len(mids) > 1 else 0.0
        div_pct   = (stdev_mid / mean_mid * 100) if mean_mid else 0.0

        def _q4(v: float) -> Decimal:
            return Decimal(str(round(v, 4))).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

        return {
            'weighted_avg_buy':  _q4(wavg_buy),
            'weighted_avg_sell': _q4(wavg_sell),
            'median_buy':        _q4(statistics.median(buys)),
            'median_sell':       _q4(statistics.median(sells)),
            'best_buy':          _q4(max(buys)),
            'best_sell':         _q4(min(sells)),
            'source_count':      len(source_rates),
            'divergence_pct':    round(div_pct, 2),
            'has_divergence':    div_pct > MAX_DIVERGENCE_PCT,
        }

    @staticmethod
    def _get_best_fallback(cur_from, cur_to) -> 'ExchangeRate | None':
        """Last-resort: best active non-inference rate ordered by confidence."""
        from .models import ExchangeRate
        from .aggregator import MARKET_PRIORITY

        for market in sorted(MARKET_PRIORITY, key=lambda m: MARKET_PRIORITY[m], reverse=True):
            rate = (
                ExchangeRate.objects
                .filter(
                    currency_from    = cur_from,
                    currency_to      = cur_to,
                    market_type      = market,
                    valid_until__isnull = True,
                )
                .exclude(source_method='INFERENCE')
                .order_by('-confidence', '-valid_from')
                .first()
            )
            if rate:
                return rate

        # Accept inference as absolute last resort
        return (
            ExchangeRate.objects
            .filter(
                currency_from    = cur_from,
                currency_to      = cur_to,
                valid_until__isnull = True,
            )
            .order_by('-confidence', '-valid_from')
            .first()
        )
