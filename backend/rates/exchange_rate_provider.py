"""
Exchange Rate Provider — Single Source of Truth Layer
=====================================================

This module is the ONLY authorised entry point for obtaining exchange rates.

All callers (views, tasks, services, serializers) MUST go through this provider.
Direct access to individual fetchers is reserved for Celery background tasks.

Approved rate sources (Phase 9):
    1. API-based   → Binance P2P REST (real-time, confidence ≥ 0.90)
    2. SCRAP-based → BCB official HTML / JSON (real-time, confidence ≥ 0.80)
    3. MANUAL      → Admin-entered via Django admin or API (always is_validated=True)
    4. INFERENCE   → Hardcoded spreads (emergency only, never used for transactions)

INFERENCE rates are BLOCKED from:
    - calculate_exchange() transaction calculations
    - Any automatic rate-change confirmations

Usage:
    from rates.exchange_rate_provider import ExchangeRateProvider

    provider = ExchangeRateProvider()

    # Get current best rate from DB (no live fetch)
    rate = provider.get_current_rate('USD')

    # Force a live fetch from API
    rate = provider.get_rate_from_api('USD')

    # Force a live fetch via scraping
    rate = provider.get_rate_from_scraping('USD', market_type='paralelo_digital')

    # Calculate exchange with source verification
    result = provider.calculate_exchange(Decimal('100'), 'USD', 'BOB', 'BUY')
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.utils import timezone

log = logging.getLogger('kapitalya.rates.provider')


# ---------------------------------------------------------------------------
# Data transfer object for provider results
# ---------------------------------------------------------------------------

@dataclass
class RateResult:
    """
    Unified rate result from any source.
    Frontend and backend consumers should use this exclusively.
    """
    currency_from:  str
    currency_to:    str
    buy_rate:       Decimal
    sell_rate:      Decimal
    official_rate:  Decimal
    scale_factor:   int

    # Traceability (required for compliance)
    source_method:  str             # API | SCRAP | MANUAL | INFERENCE
    source_url:     Optional[str]
    fetched_at:     object          # datetime
    confidence:     float           # 0.0 – 1.0
    sources:        list[str]       # raw source names
    market_type:    str

    # Audit flags
    is_validated:   bool = False
    requires_warning: bool = False  # True if INFERENCE or low confidence

    @property
    def is_inference(self) -> bool:
        return self.source_method == 'INFERENCE'

    @property
    def is_safe_for_transaction(self) -> bool:
        """
        A rate is safe to use in a transaction if:
          - It is NOT INFERENCE (estimated/hardcoded)
          - Confidence ≥ 0.70
          - Has a known source
        """
        return (
            self.source_method != 'INFERENCE'
            and self.confidence >= 0.70
            and bool(self.sources)
        )

    def to_dict(self) -> dict:
        return {
            'currency_from':    self.currency_from,
            'currency_to':      self.currency_to,
            'buy_rate':         str(self.buy_rate),
            'sell_rate':        str(self.sell_rate),
            'official_rate':    str(self.official_rate),
            'scale_factor':     self.scale_factor,
            'source_method':    self.source_method,
            'source_url':       self.source_url,
            'fetched_at':       self.fetched_at.isoformat() if self.fetched_at else None,
            'confidence':       round(self.confidence, 3),
            'sources':          self.sources,
            'market_type':      self.market_type,
            'is_validated':     self.is_validated,
            'requires_warning': self.requires_warning,
            'is_safe_for_transaction': self.is_safe_for_transaction,
        }


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class ExchangeRateProvider:
    """
    Unified exchange rate provider.

    Single source of truth for ALL rate lookups in the system.
    Every returned rate carries its origin method and provenance metadata.
    """

    MIN_CONFIDENCE_FOR_TRANSACTION = 0.70

    def get_current_rate(
        self,
        currency_code: str,
        currency_to: str = 'BOB',
        market_type: str | None = None,
    ) -> RateResult | None:
        """
        Returns the best active rate from DB without triggering a live fetch.
        Priority: parallel > digital > bcb > official (same as aggregator).
        """
        from .models import Currency, ExchangeRate
        from .aggregator import MARKET_PRIORITY

        try:
            cur_from = Currency.objects.get(code=currency_code.upper())
            cur_to   = Currency.objects.get(code=currency_to.upper())
        except Currency.DoesNotExist:
            log.error("PROVIDER get_current_rate: unknown currency %s/%s", currency_code, currency_to)
            return None

        # Prefer is_primary=True rate first (Phase 10)
        if not market_type:
            primary = ExchangeRate.objects.filter(
                currency_from    = cur_from,
                currency_to      = cur_to,
                is_primary       = True,
                valid_until__isnull = True,
            ).order_by('-valid_from').first()
            if primary:
                return self._rate_to_result(primary, cur_from)

        qs = ExchangeRate.objects.filter(
            currency_from=cur_from,
            currency_to=cur_to,
            valid_until__isnull=True,
        ).order_by('-valid_from')

        if market_type:
            qs = qs.filter(market_type=market_type)

        # Iterate from highest-priority market to lowest
        for market in sorted(MARKET_PRIORITY, key=lambda m: MARKET_PRIORITY[m], reverse=True):
            if market_type and market != market_type:
                continue
            rate = qs.filter(market_type=market).first()
            if rate:
                return self._rate_to_result(rate, cur_from)

        # Fallback: any active rate
        rate = qs.first()
        if rate:
            return self._rate_to_result(rate, cur_from)

        log.warning("PROVIDER no active rate found for %s/%s", currency_code, currency_to)
        return None

    def get_rate_from_api(
        self,
        currency_code: str,
        currency_to: str = 'BOB',
    ) -> RateResult | None:
        """
        Fetches a rate from a direct REST API (e.g. Binance P2P for USD).
        source_method will be 'API'.
        Only USD/BOB is supported via Binance P2P currently.
        """
        log.info("PROVIDER get_rate_from_api currency=%s", currency_code)

        if currency_code.upper() == 'USD':
            try:
                from .fetchers.binance_p2p import fetch_binance_p2p
                result = fetch_binance_p2p()
                return RateResult(
                    currency_from  = 'USD',
                    currency_to    = 'BOB',
                    buy_rate       = result['buy'],
                    sell_rate      = result['sell'],
                    official_rate  = result['official'],
                    scale_factor   = 1,
                    source_method  = 'API',
                    source_url     = result.get('source_url'),
                    fetched_at     = result.get('fetched_at') or timezone.now(),
                    confidence     = 0.95,
                    sources        = ['binance_p2p'],
                    market_type    = 'paralelo_digital',
                    requires_warning = False,
                )
            except Exception as exc:
                log.error("PROVIDER get_rate_from_api FAILED currency=%s error=%s", currency_code, exc)
                return None

        log.warning(
            "PROVIDER get_rate_from_api: no direct API source for %s, "
            "falling back to DB", currency_code
        )
        return self.get_current_rate(currency_code, currency_to)

    def get_rate_from_scraping(
        self,
        currency_code: str,
        currency_to: str = 'BOB',
        market_type: str = 'paralelo_digital',
    ) -> RateResult | None:
        """
        Fetches a rate via web scraping (parallel market).
        source_method will be 'SCRAP' (or 'INFERENCE' if scraping fails).
        """
        log.info("PROVIDER get_rate_from_scraping currency=%s market=%s", currency_code, market_type)

        try:
            from .fetchers.parallel_scraper import ParallelMarketFetcher
            from .aggregator import RateAggregator

            results = ParallelMarketFetcher().fetch()

            # Filter to the requested currency
            results = [r for r in results if r.currency_code == currency_code.upper()]
            if not results:
                log.warning("PROVIDER scraping returned no result for %s/%s", currency_code, market_type)
                return None

            # Pick the highest-confidence result
            best = max(results, key=lambda r: r.confidence)

            return RateResult(
                currency_from  = currency_code.upper(),
                currency_to    = 'BOB',
                buy_rate       = best.buy_rate,
                sell_rate      = best.sell_rate,
                official_rate  = best.official_rate,
                scale_factor   = best.scale_factor,
                source_method  = best.source_method,
                source_url     = best.source_url,
                fetched_at     = best.fetched_at or timezone.now(),
                confidence     = best.confidence,
                sources        = [best.source_name],
                market_type    = market_type,
                requires_warning = best.source_method == 'INFERENCE',
            )
        except Exception as exc:
            log.error("PROVIDER get_rate_from_scraping FAILED %s", exc, exc_info=True)
            return None

    def get_rate_from_inference(
        self,
        currency_code: str,
        amount_to: Decimal | None = None,
        amount_from: Decimal | None = None,
    ) -> RateResult | None:
        """
        Calculates a rate by inference (e.g. rate = amount_to / amount_from).

        COMPLIANCE: Always marks source_method='INFERENCE', is_validated=False.
        This rate MUST NOT be used for transactions without explicit operator confirmation.

        Args:
            currency_code: the currency being inferred.
            amount_to:     BOB amount received/paid.
            amount_from:   foreign currency amount.
        """
        log.warning(
            "PROVIDER get_rate_from_inference currency=%s — "
            "inferred rate requested; will be tagged INFERENCE",
            currency_code,
        )

        if amount_to and amount_from and amount_from != 0:
            inferred_rate = Decimal(str(amount_to)) / Decimal(str(amount_from))
        else:
            log.error("PROVIDER get_rate_from_inference: cannot infer without amounts")
            return None

        return RateResult(
            currency_from  = currency_code.upper(),
            currency_to    = 'BOB',
            buy_rate       = inferred_rate,
            sell_rate      = inferred_rate,
            official_rate  = inferred_rate,
            scale_factor   = 1,
            source_method  = 'INFERENCE',
            source_url     = None,
            fetched_at     = timezone.now(),
            confidence     = 0.50,
            sources        = ['INFERRED_FROM_TRANSACTION'],
            market_type    = 'parallel',
            is_validated   = False,
            requires_warning = True,
        )

    def calculate_exchange(
        self,
        amount: Decimal,
        currency_from_code: str,
        currency_to_code: str,
        transaction_type: str,  # 'BUY' | 'SELL'
        user=None,
    ) -> dict:
        """
        Calculates an exchange amount using the current best rate.

        Phase 9 enforcement:
            - Raises ValueError if the active rate is INFERENCE.
            - Raises ValueError if confidence < MIN_CONFIDENCE_FOR_TRANSACTION.

        Returns a dict including full rate provenance for audit trail.
        """
        from core.finance import quantize_rate, quantize_money

        rate_result = self.get_current_rate(currency_from_code, currency_to_code)
        if not rate_result:
            raise ValueError(
                f"No hay tasa activa disponible para {currency_from_code}/{currency_to_code}"
            )

        # ── Phase 9: Block INFERENCE rates from transactions ──────────────────
        if rate_result.is_inference:
            raise ValueError(
                f"COMPLIANCE ERROR: La tasa de {currency_from_code} proviene de "
                f"estimación (INFERENCE) y no puede usarse en transacciones. "
                f"Un administrador debe ingresar la tasa manualmente o esperar "
                f"a que las fuentes en línea se restauren."
            )

        if rate_result.confidence < self.MIN_CONFIDENCE_FOR_TRANSACTION:
            raise ValueError(
                f"COMPLIANCE ERROR: La tasa de {currency_from_code} tiene confianza "
                f"{rate_result.confidence:.0%} — por debajo del mínimo "
                f"({self.MIN_CONFIDENCE_FOR_TRANSACTION:.0%}) requerido para transacciones."
            )

        amount = quantize_rate(amount)

        if transaction_type == 'BUY':
            rate   = rate_result.buy_rate
            result = quantize_money(amount * rate)
        else:
            rate = rate_result.sell_rate
            if rate == 0:
                raise ValueError("Tasa de venta no puede ser cero")
            result = quantize_money(amount * rate)

        log.info(
            "PROVIDER calculate_exchange %s %s→%s type=%s rate=%s method=%s conf=%.2f",
            amount, currency_from_code, currency_to_code,
            transaction_type, rate,
            rate_result.source_method, rate_result.confidence,
        )

        return {
            'amount_from':    str(amount),
            'amount_to':      str(result),
            'rate':           str(quantize_rate(rate)),
            'scale_factor':   rate_result.scale_factor,
            'transaction_type': transaction_type,
            'currency_from':  currency_from_code,
            'currency_to':    currency_to_code,
            # ── Provenance (for audit log) ─────────────────────────────────────
            'source_method':  rate_result.source_method,
            'source_url':     rate_result.source_url,
            'fetched_at':     rate_result.fetched_at.isoformat() if rate_result.fetched_at else None,
            'confidence':     rate_result.confidence,
            'market_type':    rate_result.market_type,
            'is_validated':   rate_result.is_validated,
        }

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _rate_to_result(rate, currency_from) -> RateResult:
        """Converts a DB ExchangeRate instance to a RateResult."""
        conf = float(rate.confidence) if rate.confidence else 1.0
        return RateResult(
            currency_from    = currency_from.code,
            currency_to      = 'BOB',
            buy_rate         = rate.buy_rate,
            sell_rate        = rate.sell_rate,
            official_rate    = rate.official_rate,
            scale_factor     = currency_from.scale_factor,
            source_method    = rate.source_method,
            source_url       = rate.source_url,
            fetched_at       = rate.fetched_at,
            confidence       = conf,
            sources          = [rate.source] if rate.source else [],
            market_type      = rate.market_type,
            is_validated     = rate.is_validated,
            requires_warning = rate.source_method == 'INFERENCE' or conf < 0.70,
        )
