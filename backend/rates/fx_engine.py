"""
Production FX Engine — Kapitalya.

ARCHITECTURE:
  1. Fetch ALL parallel market sources concurrently (ThreadPoolExecutor)
  2. Normalize all prices to BOB
  3. Remove outliers (IQR)
  4. Calculate market_buy = avg(lowest prices), market_sell = avg(highest prices)
  5. Apply business margins per currency/variant type
  6. Round ALL values to exactly 2 decimals
  7. Save to ExchangeRate model and emit WebSocket event

SUPPORTED CURRENCIES:
  USD, EUR, CLP (×1000), PEN, PEN_COINS, USD_LOOSE, USD_SMALL, BRL, ARS (×1000)

DATA SOURCES (parallel market only):
  Binance P2P, Bitget P2P, Bybit P2P, Airtm, Eldorado, Wallbit, SaldoAR, DolarBlueBolivia

BCB/BCP: reference ONLY — stored in ReferenceRate, NEVER used for trading.

BUSINESS LOGIC:
  USD (50/100):    buy = market_buy - margin,  sell = market_sell + margin
  USD_LOOSE:       buy = USD_buy - 0.30,        sell = USD_sell
  USD_SMALL:       buy = USD_buy - 0.60,        sell = USD_sell
  PEN_COINS:       buy = PEN_buy - 0.10,        sell = PEN_sell + 0.05  (wider spread)
  ARS/CLP:         scale factor = 1000
"""
from __future__ import annotations
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

log = logging.getLogger('kapitalya.rates.fx_engine')

# ── Precision ──────────────────────────────────────────────────────────────────
_Q2 = Decimal('0.01')      # 2-decimal precision for all output rates
_Q4 = Decimal('0.0001')    # 4-decimal for intermediate calculations


def _q2(val) -> Decimal:
    """Round to exactly 2 decimal places."""
    return Decimal(str(val)).quantize(_Q2, rounding=ROUND_HALF_UP)


def _q4(val) -> Decimal:
    return Decimal(str(val)).quantize(_Q4, rounding=ROUND_HALF_UP)


# ── Supported currencies and their scale factors ───────────────────────────────
SUPPORTED_CURRENCIES = ['USD', 'EUR', 'CLP', 'PEN', 'BRL', 'ARS']
SCALE_FACTORS        = {'ARS': 1000, 'CLP': 1000}

# ── Base margins (BOB) applied per currency ────────────────────────────────────
# These are the starting margins before auto-profit adjustments.
# Operators can override via RateConfiguration in the DB.
DEFAULT_MARGINS: dict[str, dict[str, Decimal]] = {
    'USD': {'buy': Decimal('0.20'), 'sell': Decimal('0.20')},
    'EUR': {'buy': Decimal('0.25'), 'sell': Decimal('0.25')},
    'BRL': {'buy': Decimal('0.05'), 'sell': Decimal('0.05')},
    'PEN': {'buy': Decimal('0.10'), 'sell': Decimal('0.10')},
    'CLP': {'buy': Decimal('1.00'), 'sell': Decimal('1.00')},  # per 1000 CLP
    'ARS': {'buy': Decimal('0.10'), 'sell': Decimal('0.10')},  # per 1000 ARS
}

# ── Cash variant absolute adjustments (in BOB) ────────────────────────────────
CASH_VARIANT_ADJUSTMENTS = {
    'USD_LOOSE': {'buy_deduct': Decimal('0.30'), 'sell_add': Decimal('0.00')},
    'USD_SMALL': {'buy_deduct': Decimal('0.60'), 'sell_add': Decimal('0.00')},
    'PEN_COINS': {'buy_deduct': Decimal('0.10'), 'sell_add': Decimal('0.05')},
}

# ── Fetch timeout ──────────────────────────────────────────────────────────────
FETCH_TIMEOUT_SECONDS = 20

# ── IQR filter minimum sources ─────────────────────────────────────────────────
IQR_MIN_SOURCES = 3

# ── Fraction of prices used for market buy/sell calculation ───────────────────
# market_buy  = avg of the lowest PRICE_SAMPLE_FRACTION of prices
# market_sell = avg of the highest PRICE_SAMPLE_FRACTION of prices
PRICE_SAMPLE_FRACTION = 0.50   # use bottom/top 50%


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class MarketData:
    """Raw collected prices for a currency from all parallel sources."""
    currency:     str
    buy_prices:   list[Decimal] = field(default_factory=list)
    sell_prices:  list[Decimal] = field(default_factory=list)
    sources:      list[str]     = field(default_factory=list)
    scale_factor: int           = 1


@dataclass
class EngineRate:
    """Final computed rate after engine processing."""
    currency:     str
    buy_rate:     Decimal       # 2 decimals
    sell_rate:    Decimal       # 2 decimals
    avg_rate:     Decimal       # 2 decimals
    spread:       Decimal       # 2 decimals
    spread_pct:   Decimal       # 2 decimals
    market_buy:   Decimal       # 2 decimals — before margin
    market_sell:  Decimal       # 2 decimals — before margin
    margin_buy:   Decimal       # margin applied on buy side
    margin_sell:  Decimal       # margin applied on sell side
    sources:      list[str]
    source_count: int
    confidence:   Decimal
    scale_factor: int

    def to_dict(self) -> dict:
        return {
            'currency':     self.currency,
            'buy_rate':     float(self.buy_rate),
            'sell_rate':    float(self.sell_rate),
            'avg_rate':     float(self.avg_rate),
            'spread':       float(self.spread),
            'spread_pct':   float(self.spread_pct),
            'market_buy':   float(self.market_buy),
            'market_sell':  float(self.market_sell),
            'margin_buy':   float(self.margin_buy),
            'margin_sell':  float(self.margin_sell),
            'sources':      self.sources,
            'source_count': self.source_count,
            'confidence':   float(self.confidence),
            'scale_factor': self.scale_factor,
        }


@dataclass
class FXEngineResult:
    """Full result from one engine run."""
    rates:    dict[str, EngineRate]    # base currencies
    variants: dict[str, EngineRate]    # cash variants (USD_LOOSE, etc.)

    def all_rates(self) -> dict[str, EngineRate]:
        return {**self.rates, **self.variants}


# ── Engine ─────────────────────────────────────────────────────────────────────

class FXEngine:
    """
    Production exchange rate engine.

    Usage:
        engine = FXEngine()
        result = engine.run()          # → FXEngineResult
        engine.save_to_db(result)      # persist to ExchangeRate
        engine.emit_websocket(result)  # push to connected clients
    """

    def __init__(self, auto_profit: bool = True):
        self.auto_profit = auto_profit

    # ── Entry point ────────────────────────────────────────────────────────────

    def run(self) -> FXEngineResult:
        """Full engine run — fetch, clean, calculate, apply margins."""
        log.info('FX_ENGINE_START auto_profit=%s', self.auto_profit)

        raw = self._fetch_all_parallel()
        market = self._compute_market_data(raw)
        rates = self._compute_rates(market)
        variants = self._compute_variants(rates)

        log.info(
            'FX_ENGINE_DONE currencies=%d variants=%d',
            len(rates), len(variants),
        )
        return FXEngineResult(rates=rates, variants=variants)

    # ── Step 1: Parallel fetch ─────────────────────────────────────────────────

    def _fetch_all_parallel(self) -> list:
        """Run all parallel market fetchers concurrently."""
        from rates.fetchers.p2p_exchanges import (
            BinanceP2PFetcher, BitgetP2PFetcher, BybitP2PFetcher,
        )
        from rates.fetchers.eldorado_fetcher import EldoradoFetcher
        from rates.fetchers.wallbit_fetcher  import WallbitFetcher
        from rates.fetchers.saldoar_fetcher  import SaldoARFetcher
        from rates.fetchers.airtm_v2_fetcher import AirtmQuoteFetcher
        from rates.fetchers.dolar_blue_bolivia import DolarBlueBoliviaFetcher

        fetcher_classes = [
            BinanceP2PFetcher,
            BitgetP2PFetcher,
            BybitP2PFetcher,
            AirtmQuoteFetcher,
            EldoradoFetcher,
            WallbitFetcher,
            SaldoARFetcher,
            DolarBlueBoliviaFetcher,
        ]

        all_results = []

        with ThreadPoolExecutor(max_workers=len(fetcher_classes)) as executor:
            futures = {
                executor.submit(cls().fetch): cls.__name__
                for cls in fetcher_classes
            }
            for future in as_completed(futures, timeout=FETCH_TIMEOUT_SECONDS):
                name = futures[future]
                try:
                    results = future.result(timeout=2)
                    all_results.extend(results or [])
                    log.debug('FX_FETCH_OK source=%s count=%d', name, len(results or []))
                except FutureTimeout:
                    log.warning('FX_FETCH_TIMEOUT source=%s', name)
                except Exception as exc:
                    log.warning('FX_FETCH_ERROR source=%s error=%s', name, exc)

        log.info('FX_FETCH_TOTAL results=%d', len(all_results))
        return all_results

    # ── Step 2: Organize and clean raw results ─────────────────────────────────

    def _compute_market_data(self, raw_results: list) -> dict[str, MarketData]:
        """Group prices by currency, remove outliers."""
        by_currency: dict[str, MarketData] = {}

        for result in raw_results:
            if not result.is_valid():
                continue

            code = result.currency_code.upper()
            if code not in SUPPORTED_CURRENCIES:
                continue

            if code not in by_currency:
                by_currency[code] = MarketData(
                    currency     = code,
                    scale_factor = SCALE_FACTORS.get(code, 1),
                )

            md = by_currency[code]
            md.buy_prices.append(result.buy_rate)
            md.sell_prices.append(result.sell_rate)
            if result.source_name not in md.sources:
                md.sources.append(result.source_name)

        # Apply IQR outlier removal per currency
        for code, md in by_currency.items():
            md.buy_prices  = self._remove_outliers(md.buy_prices)
            md.sell_prices = self._remove_outliers(md.sell_prices)
            # Remove any zeros or negatives that slipped through
            md.buy_prices  = [p for p in md.buy_prices  if p > 0]
            md.sell_prices = [p for p in md.sell_prices if p > 0]

        return by_currency

    def _remove_outliers(self, prices: list[Decimal]) -> list[Decimal]:
        """
        IQR-based outlier removal.
        Only applied when there are >= IQR_MIN_SOURCES prices.
        """
        if len(prices) < IQR_MIN_SOURCES:
            return prices

        floats = sorted(float(p) for p in prices)
        n  = len(floats)
        q1 = floats[n // 4]
        q3 = floats[(3 * n) // 4]
        iqr = q3 - q1

        lo = q1 - 1.5 * iqr
        hi = q3 + 1.5 * iqr

        filtered = [p for p in prices if lo <= float(p) <= hi]
        removed  = len(prices) - len(filtered)

        if removed:
            log.info('IQR_OUTLIER_REMOVED count=%d from %d prices', removed, len(prices))

        return filtered if filtered else prices

    # ── Step 3: Market price calculation ──────────────────────────────────────

    def _market_buy(self, prices: list[Decimal]) -> Optional[Decimal]:
        """Average of the lowest fraction of buy prices."""
        if not prices:
            return None
        sorted_prices = sorted(prices)
        n_take = max(1, int(len(sorted_prices) * PRICE_SAMPLE_FRACTION))
        sample = sorted_prices[:n_take]
        avg = sum(sample) / Decimal(str(len(sample)))
        return _q4(avg)

    def _market_sell(self, prices: list[Decimal]) -> Optional[Decimal]:
        """Average of the highest fraction of sell prices."""
        if not prices:
            return None
        sorted_prices = sorted(prices, reverse=True)
        n_take = max(1, int(len(sorted_prices) * PRICE_SAMPLE_FRACTION))
        sample = sorted_prices[:n_take]
        avg = sum(sample) / Decimal(str(len(sample)))
        return _q4(avg)

    # ── Step 4: Rate calculation with margins ─────────────────────────────────

    def _compute_rates(self, market: dict[str, MarketData]) -> dict[str, EngineRate]:
        """Apply business margins and compute final trading rates."""
        rates: dict[str, EngineRate] = {}

        for code, md in market.items():
            if not md.buy_prices and not md.sell_prices:
                continue

            mkt_buy  = self._market_buy(md.buy_prices)
            mkt_sell = self._market_sell(md.sell_prices)

            if mkt_buy is None and mkt_sell is None:
                continue

            # If one side is missing, derive from the other
            if mkt_buy is None:
                mkt_buy = _q4(mkt_sell * Decimal('0.997'))
            if mkt_sell is None:
                mkt_sell = _q4(mkt_buy * Decimal('1.003'))

            # Ensure buy < sell
            if mkt_buy >= mkt_sell:
                mkt_sell = _q4(mkt_buy * Decimal('1.003'))

            # Get margins
            margins = self._get_margins(code, mkt_buy, mkt_sell)
            margin_buy  = margins['buy']
            margin_sell = margins['sell']

            # Apply business logic
            buy_rate  = _q2(mkt_buy  - margin_buy)
            sell_rate = _q2(mkt_sell + margin_sell)

            # Sanity: buy must be > 0 and < sell
            if buy_rate <= 0:
                buy_rate = _q2(mkt_buy * Decimal('0.98'))
            if sell_rate <= buy_rate:
                sell_rate = _q2(buy_rate + Decimal('0.01'))

            avg_rate   = _q2((buy_rate + sell_rate) / Decimal('2'))
            spread     = _q2(sell_rate - buy_rate)
            spread_pct = _q2(spread / buy_rate * 100) if buy_rate > 0 else Decimal('0')

            confidence = self._compute_confidence(md)

            rates[code] = EngineRate(
                currency     = code,
                buy_rate     = buy_rate,
                sell_rate    = sell_rate,
                avg_rate     = avg_rate,
                spread       = spread,
                spread_pct   = spread_pct,
                market_buy   = _q2(mkt_buy),
                market_sell  = _q2(mkt_sell),
                margin_buy   = _q2(margin_buy),
                margin_sell  = _q2(margin_sell),
                sources      = md.sources,
                source_count = len(md.sources),
                confidence   = confidence,
                scale_factor = md.scale_factor,
            )

            log.info(
                'FX_RATE %s: market=%s/%s → trading=%s/%s spread=%.2f%% sources=%d',
                code, mkt_buy, mkt_sell, buy_rate, sell_rate,
                float(spread_pct), len(md.sources),
            )

        return rates

    # ── Step 5: Cash variants ─────────────────────────────────────────────────

    def _compute_variants(self, rates: dict[str, EngineRate]) -> dict[str, EngineRate]:
        """Compute cash variant rates using absolute BOB adjustments."""
        variants: dict[str, EngineRate] = {}

        # USD_LOOSE (5, 10, 20 bills): buy = USD_buy - 0.30, sell = USD_sell
        usd = rates.get('USD')
        if usd:
            for variant_code, adj in CASH_VARIANT_ADJUSTMENTS.items():
                base_code = 'PEN' if 'PEN' in variant_code else 'USD'
                base_rate = rates.get(base_code)
                if not base_rate:
                    continue

                buy_rate  = _q2(base_rate.buy_rate  - adj['buy_deduct'])
                sell_rate = _q2(base_rate.sell_rate + adj['sell_add'])

                if buy_rate <= 0:
                    buy_rate = _q2(base_rate.buy_rate * Decimal('0.95'))
                if sell_rate <= buy_rate:
                    sell_rate = _q2(buy_rate + Decimal('0.01'))

                avg_rate   = _q2((buy_rate + sell_rate) / Decimal('2'))
                spread     = _q2(sell_rate - buy_rate)
                spread_pct = _q2(spread / buy_rate * 100) if buy_rate > 0 else Decimal('0')

                variants[variant_code] = EngineRate(
                    currency     = variant_code,
                    buy_rate     = buy_rate,
                    sell_rate    = sell_rate,
                    avg_rate     = avg_rate,
                    spread       = spread,
                    spread_pct   = spread_pct,
                    market_buy   = base_rate.market_buy,
                    market_sell  = base_rate.market_sell,
                    margin_buy   = _q2(base_rate.margin_buy + adj['buy_deduct']),
                    margin_sell  = _q2(base_rate.margin_sell + adj['sell_add']),
                    sources      = base_rate.sources,
                    source_count = base_rate.source_count,
                    confidence   = _q4(base_rate.confidence * Decimal('0.95')),
                    scale_factor = base_rate.scale_factor,
                )

                log.info(
                    'FX_VARIANT %s: buy=%s sell=%s (base %s deduct=%s add=%s)',
                    variant_code, buy_rate, sell_rate, base_code,
                    adj['buy_deduct'], adj['sell_add'],
                )

        return variants

    # ── Margin helpers ────────────────────────────────────────────────────────

    def _get_margins(
        self, currency: str, mkt_buy: Decimal, mkt_sell: Decimal
    ) -> dict[str, Decimal]:
        """
        Get margins for a currency.
        Tries DB RateConfiguration first, falls back to defaults.
        If auto_profit mode is on, adjusts based on market volatility.
        """
        margins = self._db_margins(currency)
        if margins is None:
            margins = {
                'buy':  DEFAULT_MARGINS.get(currency, {}).get('buy',  Decimal('0.20')),
                'sell': DEFAULT_MARGINS.get(currency, {}).get('sell', Decimal('0.20')),
            }

        if self.auto_profit:
            margins = self._auto_adjust_margins(currency, margins, mkt_buy, mkt_sell)

        return margins

    def _db_margins(self, currency: str) -> dict | None:
        """Load margins from RateConfiguration if available."""
        try:
            from rates.models import Currency, RateConfiguration
            cur = Currency.objects.filter(code=currency).first()
            bob = Currency.objects.filter(is_base_currency=True).first()
            if not cur or not bob:
                return None
            config = RateConfiguration.objects.filter(
                currency_from=cur, currency_to=bob, is_active=True
            ).first()
            if not config:
                return None
            buy_m, sell_m = config.get_current_margins()
            return {'buy': Decimal(str(buy_m)), 'sell': Decimal(str(sell_m))}
        except Exception as exc:
            log.debug('FX_DB_MARGINS_FAIL currency=%s error=%s', currency, exc)
            return None

    def _auto_adjust_margins(
        self,
        currency: str,
        margins: dict[str, Decimal],
        mkt_buy: Decimal,
        mkt_sell: Decimal,
    ) -> dict[str, Decimal]:
        """
        Auto Profit Mode:
        - Calculate market spread (volatility proxy)
        - If spread_pct > 3%: increase our margins by up to 30%
        - If spread_pct < 1%: reduce margins by up to 15% to stay competitive
        """
        if mkt_buy <= 0:
            return margins

        spread_pct = float((mkt_sell - mkt_buy) / mkt_buy * 100)

        if spread_pct > 3.0:
            # High volatility — widen our spread to capture more profit
            factor = min(Decimal('1.30'), Decimal('1') + Decimal(str(spread_pct)) / Decimal('20'))
        elif spread_pct < 1.0:
            # Very tight market — compress slightly to stay competitive
            factor = Decimal('0.85')
        else:
            factor = Decimal('1.00')

        adjusted = {
            'buy':  _q4(margins['buy']  * factor),
            'sell': _q4(margins['sell'] * factor),
        }

        if factor != Decimal('1.00'):
            log.debug(
                'AUTO_PROFIT %s spread_pct=%.2f%% factor=%.2f margin_buy=%s→%s sell=%s→%s',
                currency, spread_pct, float(factor),
                margins['buy'], adjusted['buy'],
                margins['sell'], adjusted['sell'],
            )

        return adjusted

    def _compute_confidence(self, md: MarketData) -> Decimal:
        """
        Confidence based on number of sources.
        1 source → 0.70, 2 → 0.85, 3+ → 0.95
        """
        n = len(md.sources)
        if n >= 3:
            return Decimal('0.950')
        elif n == 2:
            return Decimal('0.850')
        elif n == 1:
            return Decimal('0.700')
        return Decimal('0.500')

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_to_db(self, result: FXEngineResult) -> int:
        """
        Persist engine rates to ExchangeRate.
        Closes current active rates and creates new ones.
        """
        from django.utils import timezone
        from rates.models import Currency, ExchangeRate

        now = timezone.now()
        bob = Currency.objects.filter(is_base_currency=True).first()
        if not bob:
            log.error('FX_ENGINE_SAVE_NO_BOB')
            return 0

        saved = 0
        all_rates = result.all_rates()

        for code, rate in all_rates.items():
            # Map variant codes to base currency in DB
            # (USD_LOOSE, USD_SMALL stored under USD currency with source tag)
            is_variant = code in CASH_VARIANT_ADJUSTMENTS
            db_code    = 'USD' if 'USD' in code else ('PEN' if 'PEN' in code else code)

            try:
                currency = Currency.objects.filter(code=db_code).first()
                if not currency:
                    log.warning('FX_ENGINE_SAVE_SKIP code=%s no currency', db_code)
                    continue

                source_tag = code if is_variant else 'fx_engine'
                market_type = (
                    'paralelo_fisico_empresa' if is_variant else 'paralelo_digital'
                )

                # Close existing active rate
                ExchangeRate.objects.filter(
                    currency_from       = currency,
                    currency_to         = bob,
                    market_type         = market_type,
                    source              = source_tag,
                    valid_until__isnull = True,
                ).update(valid_until=now)

                # Intermediate avg in DB uses 4 decimals for precision
                avg_4 = _q4(
                    (Decimal(str(rate.buy_rate)) + Decimal(str(rate.sell_rate))) / 2
                )

                ExchangeRate.objects.create(
                    currency_from = currency,
                    currency_to   = bob,
                    market_type   = market_type,
                    source        = source_tag,
                    buy_rate      = rate.buy_rate,
                    sell_rate     = rate.sell_rate,
                    avg_rate      = avg_4,
                    official_rate = avg_4,  # engine rates don't use official_rate
                    valid_from    = now,
                    valid_until   = None,
                    source_method = 'API',
                    source_url    = None,
                    fetched_at    = now,
                    confidence    = rate.confidence,
                    is_validated  = False,
                    is_primary    = False,
                )
                saved += 1

            except Exception as exc:
                log.error('FX_ENGINE_SAVE_ERROR code=%s error=%s', code, exc, exc_info=True)

        # Mark primary rates after saving all
        self._mark_primary(all_rates, bob)

        log.info('FX_ENGINE_SAVE_DONE saved=%d', saved)
        return saved

    def _mark_primary(self, all_rates: dict[str, EngineRate], bob) -> None:
        """Mark the fx_engine rate as primary for each base currency."""
        from rates.models import Currency, ExchangeRate

        base_currencies = {
            'USD' if 'USD' in code else ('PEN' if 'PEN' in code else code)
            for code in all_rates
            if code not in CASH_VARIANT_ADJUSTMENTS
        }

        for db_code in base_currencies:
            try:
                currency = Currency.objects.filter(code=db_code).first()
                if not currency:
                    continue

                ExchangeRate.objects.filter(
                    currency_from=currency, currency_to=bob, is_primary=True
                ).update(is_primary=False)

                best = (
                    ExchangeRate.objects
                    .filter(
                        currency_from       = currency,
                        currency_to         = bob,
                        market_type         = 'paralelo_digital',
                        source              = 'fx_engine',
                        valid_until__isnull = True,
                    )
                    .order_by('-valid_from')
                    .first()
                )
                if best:
                    ExchangeRate.objects.filter(pk=best.pk).update(is_primary=True)
                    log.info('FX_PRIMARY_SET %s id=%d', db_code, best.pk)

            except Exception as exc:
                log.error('FX_MARK_PRIMARY_ERROR code=%s error=%s', db_code, exc)

    # ── WebSocket broadcast ───────────────────────────────────────────────────

    def emit_websocket(self, result: FXEngineResult) -> None:
        """Broadcast rate update to all connected WebSocket clients."""
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            layer = get_channel_layer()
            if layer is None:
                return

            payload = {
                'type':  'fx_engine_update',
                'rates': {
                    code: r.to_dict()
                    for code, r in result.all_rates().items()
                },
            }
            async_to_sync(layer.group_send)('rates_updates', payload)
            log.debug('FX_WS_EMITTED currencies=%d', len(result.all_rates()))

        except Exception as exc:
            log.debug('FX_WS_SKIP error=%s', exc)


# ── Convenience API ───────────────────────────────────────────────────────────

def run_engine(save: bool = True, emit: bool = True) -> FXEngineResult:
    """Run the FX engine, optionally saving to DB and emitting WebSocket."""
    engine = FXEngine(auto_profit=True)
    result = engine.run()
    if save:
        engine.save_to_db(result)
    if emit:
        engine.emit_websocket(result)
    return result


def get_live_rates() -> dict[str, dict]:
    """
    Returns the latest engine rates from DB cache.
    Does NOT trigger a fetch — uses the most recent saved rates.
    """
    from django.utils import timezone
    from datetime import timedelta
    from rates.models import Currency, ExchangeRate

    try:
        bob       = Currency.objects.filter(is_base_currency=True).first()
        cutoff    = timezone.now() - timedelta(minutes=30)
        rates_qs  = (
            ExchangeRate.objects
            .filter(
                currency_to         = bob,
                market_type__in     = ('paralelo_digital', 'paralelo_fisico_empresa'),
                source__in          = ['fx_engine'] + list(CASH_VARIANT_ADJUSTMENTS.keys()),
                valid_until__isnull = True,
                valid_from__gte     = cutoff,
            )
            .select_related('currency_from')
            .order_by('currency_from__code', '-valid_from')
        )

        rates: dict[str, dict] = {}
        for r in rates_qs:
            code = r.source if r.source in CASH_VARIANT_ADJUSTMENTS else r.currency_from.code
            if code not in rates:
                rates[code] = {
                    'currency':   code,
                    'buy_rate':   float(_q2(r.buy_rate)),
                    'sell_rate':  float(_q2(r.sell_rate)),
                    'spread':     float(_q2(r.sell_rate - r.buy_rate)),
                    'source':     r.source,
                    'confidence': float(r.confidence),
                    'updated_at': r.valid_from.isoformat() if r.valid_from else None,
                }
        return rates

    except Exception as exc:
        log.error('GET_LIVE_RATES_ERROR %s', exc)
        return {}
