"""
Agregador de tasas de cambio multi-fuente.

Estrategia de combinación:
  1. Recolectar resultados de TODOS los fetchers activos
  2. Normalizar (validar, escalar, deduplicar)
  3. Rechazar outliers con IQR (opcional si hay >= 3 fuentes)
  4. Calcular promedio ponderado por confidence
  5. Prioridad: parallel > digital > bcb > official
  6. Guardar en DB como ExchangeRate con market_type y rate_source adecuados

El aggregator es stateless: puede llamarse en cualquier momento y produce
el mejor estimado disponible con los datos actuales.
"""
from __future__ import annotations
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from .fetchers.base import FetchResult
from .fetchers.normalizer import RateNormalizer, NormalizedResult

log = logging.getLogger('kapitalya.rates.aggregator')

# Prioridad de mercado (mayor número = más confiable para el negocio)
MARKET_PRIORITY = {
    'parallel': 4,
    'digital':  3,
    'bcb':      2,
    'official': 1,
}


class AggregatedRate:
    """Resultado final del proceso de agregación para una divisa."""

    # Priority of source methods — worst wins (most conservative for compliance)
    _SOURCE_METHOD_PRIORITY = {'API': 0, 'SCRAP': 1, 'MANUAL': 2, 'INFERENCE': 3}

    def __init__(
        self,
        currency_code:  str,
        market_type:    str,
        buy_rate:       Decimal,
        sell_rate:      Decimal,
        official_rate:  Decimal,
        scale_factor:   int,
        confidence:     float,
        sources:        list[str],
        source_count:   int,
        outliers_removed: int = 0,
        source_method:  str = 'SCRAP',
        source_url:     str | None = None,
        fetched_at=None,
    ):
        self.currency_code     = currency_code
        self.market_type       = market_type
        self.buy_rate          = buy_rate
        self.sell_rate         = sell_rate
        self.official_rate     = official_rate
        self.scale_factor      = scale_factor
        self.confidence        = confidence
        self.sources           = sources
        self.source_count      = source_count
        self.outliers_removed  = outliers_removed
        # Trazabilidad: el método más "débil" entre todos los componentes
        self.source_method     = source_method
        self.source_url        = source_url
        self.fetched_at        = fetched_at

    @property
    def mid_rate(self) -> Decimal:
        return (self.buy_rate + self.sell_rate) / Decimal('2')

    @property
    def spread_pct(self) -> float:
        if self.buy_rate == 0:
            return 0.0
        return float((self.sell_rate - self.buy_rate) / self.buy_rate * 100)

    def __repr__(self) -> str:
        return (
            f"<AggregatedRate {self.currency_code} "
            f"{self.market_type} "
            f"buy={self.buy_rate} sell={self.sell_rate} "
            f"conf={self.confidence:.2f} src={self.source_count}>"
        )


class RateAggregator:
    """
    Combina resultados de múltiples fetchers en una tasa representativa.

    Uso típico (desde Celery task):
        aggregator = RateAggregator()
        results    = aggregator.collect_and_aggregate()
        aggregator.save_to_db(results)
    """

    def __init__(self, use_iqr_filter: bool = True, min_sources_for_iqr: int = 3):
        self.use_iqr_filter        = use_iqr_filter
        self.min_sources_for_iqr   = min_sources_for_iqr
        self._normalizer           = RateNormalizer()

    # ------------------------------------------------------------------ #
    #  Colección desde fetchers                                            #
    # ------------------------------------------------------------------ #

    def collect_all(self) -> list[FetchResult]:
        """Ejecuta todos los fetchers activos y devuelve resultados crudos."""
        from .fetchers.bcb_fetcher      import BCBOfficialFetcher, BCBReferenceFetcher
        from .fetchers.digital_fetcher  import TakenosFetcher, AirtmFetcher
        from .fetchers.parallel_scraper import ParallelMarketFetcher
        from .fetchers.dolarapi_fetcher import (
            OpenExchangeRatesFetcher, ExchangeRateAPIFetcher,
            FixerIOFetcher, BCBJsonAPIFetcher,
        )
        from .fetchers.bcp_fetcher        import BCPBoliviaFetcher, BCPJsonAPIFetcher
        from .fetchers.dolar_blue_bolivia import DolarBlueBoliviaFetcher
        # ── New parallel market fetchers ──────────────────────────────────────
        from .fetchers.p2p_exchanges  import BinanceP2PFetcher, BitgetP2PFetcher, BybitP2PFetcher
        from .fetchers.eldorado_fetcher import EldoradoFetcher
        from .fetchers.wallbit_fetcher  import WallbitFetcher
        from .fetchers.saldoar_fetcher  import SaldoARFetcher
        from .fetchers.airtm_v2_fetcher import AirtmQuoteFetcher

        fetchers = [
            # Reference / official (low confidence for parallel market)
            BCBOfficialFetcher(),
            BCBReferenceFetcher(),
            BCBJsonAPIFetcher(),
            BCPJsonAPIFetcher(),
            BCPBoliviaFetcher(),
            OpenExchangeRatesFetcher(),
            ExchangeRateAPIFetcher(),
            FixerIOFetcher(),
            # Digital / legacy
            TakenosFetcher(),
            AirtmFetcher(),
            DolarBlueBoliviaFetcher(),
            ParallelMarketFetcher(),
            # ── Real parallel market P2P sources ─────────────────────────────
            BinanceP2PFetcher(),
            BitgetP2PFetcher(),
            BybitP2PFetcher(),
            AirtmQuoteFetcher(),
            EldoradoFetcher(),
            WallbitFetcher(),
            SaldoARFetcher(),
        ]

        all_results: list[FetchResult] = []
        for fetcher in fetchers:
            try:
                results = fetcher.fetch()
                all_results.extend(results)
                log.debug(
                    "AGGREGATE_COLLECT source=%s results=%d",
                    fetcher.source_name, len(results),
                )
            except Exception as exc:
                log.error(
                    "AGGREGATE_FETCHER_ERROR source=%s error=%s",
                    fetcher.source_name, exc, exc_info=True,
                )

        log.info("AGGREGATE_COLLECT_TOTAL results=%d", len(all_results))
        return all_results

    def collect_by_market(self, market_type: str) -> list[FetchResult]:
        """Ejecuta sólo los fetchers de un tipo de mercado específico."""
        from .fetchers.bcb_fetcher      import BCBOfficialFetcher, BCBReferenceFetcher
        from .fetchers.digital_fetcher  import TakenosFetcher, AirtmFetcher
        from .fetchers.parallel_scraper import ParallelMarketFetcher
        from .fetchers.dolarapi_fetcher import (
            OpenExchangeRatesFetcher, ExchangeRateAPIFetcher, BCBJsonAPIFetcher,
        )
        from .fetchers.bcp_fetcher        import BCPBoliviaFetcher, BCPJsonAPIFetcher
        from .fetchers.p2p_exchanges      import BinanceP2PFetcher, BitgetP2PFetcher, BybitP2PFetcher
        from .fetchers.eldorado_fetcher   import EldoradoFetcher
        from .fetchers.wallbit_fetcher    import WallbitFetcher
        from .fetchers.saldoar_fetcher    import SaldoARFetcher
        from .fetchers.airtm_v2_fetcher   import AirtmQuoteFetcher

        fetcher_map = {
            'official': [BCBOfficialFetcher, BCBJsonAPIFetcher],
            'bcb':      [BCBReferenceFetcher, BCPBoliviaFetcher, BCPJsonAPIFetcher,
                         OpenExchangeRatesFetcher, ExchangeRateAPIFetcher],
            'digital':  [TakenosFetcher, AirtmFetcher, AirtmQuoteFetcher],
            'parallel': [
                ParallelMarketFetcher, BinanceP2PFetcher,
                BitgetP2PFetcher, BybitP2PFetcher,
                EldoradoFetcher, WallbitFetcher, SaldoARFetcher,
            ],
        }

        classes = fetcher_map.get(market_type, [])
        all_results: list[FetchResult] = []
        for cls in classes:
            try:
                all_results.extend(cls().fetch())
            except Exception as exc:
                log.error("AGGREGATE_FETCHER_ERROR cls=%s error=%s", cls.__name__, exc)
        return all_results

    # ------------------------------------------------------------------ #
    #  Agregación                                                          #
    # ------------------------------------------------------------------ #

    def aggregate(self, raw_results: list[FetchResult]) -> dict[str, AggregatedRate]:
        """
        Agrega una lista de FetchResults en tasas finales por divisa.
        Retorna {currency_code: AggregatedRate}.
        """
        normalized = self._normalizer.normalize(raw_results)
        by_currency = self._normalizer.group_by_currency(normalized)

        aggregated: dict[str, AggregatedRate] = {}
        for code, items in by_currency.items():
            rate = self._aggregate_currency(code, items)
            if rate:
                aggregated[code] = rate

        log.info("AGGREGATE_DONE currencies=%d", len(aggregated))
        return aggregated

    def collect_and_aggregate(self) -> dict[str, AggregatedRate]:
        """Colecta de todas las fuentes y agrega."""
        raw     = self.collect_all()
        return self.aggregate(raw)

    def _aggregate_currency(
        self, code: str, items: list[NormalizedResult]
    ) -> AggregatedRate | None:
        """Agrega resultados para una divisa específica."""
        if not items:
            return None

        # Separar por tipo de mercado
        by_market: dict[str, list[NormalizedResult]] = {}
        for item in items:
            by_market.setdefault(item.market_type, []).append(item)

        # Priorizar: parallel > digital > bcb > official
        for market in sorted(MARKET_PRIORITY, key=lambda m: MARKET_PRIORITY[m], reverse=True):
            market_items = by_market.get(market, [])
            if not market_items:
                continue

            # IQR outlier rejection si hay suficientes fuentes
            filtered, outliers_removed = self._iqr_filter(market_items)
            if not filtered:
                filtered = market_items
                outliers_removed = 0

            result = self._weighted_average(code, market, filtered, outliers_removed)
            if result:
                return result

        return None

    def _iqr_filter(
        self, items: list[NormalizedResult]
    ) -> tuple[list[NormalizedResult], int]:
        """
        Rechaza outliers basado en IQR del mid_rate.
        Sólo aplica si hay >= min_sources_for_iqr elementos.
        """
        if not self.use_iqr_filter or len(items) < self.min_sources_for_iqr:
            return items, 0

        mids = sorted(float((r.buy_rate + r.sell_rate) / 2) for r in items)
        n    = len(mids)
        q1   = mids[n // 4]
        q3   = mids[(3 * n) // 4]
        iqr  = q3 - q1

        lo = q1 - 1.5 * iqr
        hi = q3 + 1.5 * iqr

        filtered = []
        outliers = 0
        for r in items:
            mid = float((r.buy_rate + r.sell_rate) / 2)
            if lo <= mid <= hi:
                filtered.append(r)
            else:
                outliers += 1
                log.info(
                    "IQR_OUTLIER_REMOVED code=%s source=%s mid=%s [%s, %s]",
                    r.currency_code, r.source_name, mid, lo, hi,
                )

        return (filtered if filtered else items), outliers

    def _weighted_average(
        self,
        code: str,
        market_type: str,
        items: list[NormalizedResult],
        outliers_removed: int,
    ) -> AggregatedRate | None:
        """Calcula promedio ponderado de buy/sell por confidence."""
        total_weight = sum(r.confidence for r in items)
        if total_weight <= 0:
            return None

        buy_wavg  = sum(r.buy_rate  * Decimal(str(r.confidence)) for r in items) / Decimal(str(total_weight))
        sell_wavg = sum(r.sell_rate * Decimal(str(r.confidence)) for r in items) / Decimal(str(total_weight))
        off_wavg  = sum(r.official_rate * Decimal(str(r.confidence)) for r in items) / Decimal(str(total_weight))

        # Cuantizar a 4 decimales
        q = Decimal('0.0001')
        buy_wavg  = buy_wavg.quantize(q,  rounding=ROUND_HALF_UP)
        sell_wavg = sell_wavg.quantize(q, rounding=ROUND_HALF_UP)
        off_wavg  = off_wavg.quantize(q,  rounding=ROUND_HALF_UP)

        # Confidence agregada = promedio ponderado de confidences individuales
        agg_confidence = total_weight / len(items)

        # Reducir confidence si sólo hay una fuente
        if len(items) == 1:
            agg_confidence *= 0.85

        scale = items[0].scale_factor

        # Dominant source_method: most "weak" wins for compliance
        # (INFERENCE > MANUAL > SCRAP > API  in terms of trust level)
        source_methods = [getattr(r, 'source_method', 'SCRAP') for r in items]
        dominant_method = max(
            source_methods,
            key=lambda m: AggregatedRate._SOURCE_METHOD_PRIORITY.get(m, 1),
        )

        # Primary source_url: from the item with the highest confidence
        best_item = max(items, key=lambda r: r.confidence)
        source_url = getattr(best_item, 'source_url', None)
        fetched_at = getattr(best_item, 'fetched_at', None)

        return AggregatedRate(
            currency_code    = code,
            market_type      = market_type,
            buy_rate         = buy_wavg,
            sell_rate        = sell_wavg,
            official_rate    = off_wavg,
            scale_factor     = scale,
            confidence       = round(min(1.0, agg_confidence), 4),
            sources          = [r.source_name for r in items],
            source_count     = len(items),
            outliers_removed = outliers_removed,
            source_method    = dominant_method,
            source_url       = source_url,
            fetched_at       = fetched_at,
        )

    # ------------------------------------------------------------------ #
    #  Persistencia en DB                                                  #
    # ------------------------------------------------------------------ #

    def save_to_db(
        self,
        aggregated: dict[str, AggregatedRate],
        bob_currency=None,
    ) -> int:
        """
        Persiste las tasas agregadas en ExchangeRate.
        Cierra la tasa anterior (valid_until) y crea la nueva.
        Retorna el número de tasas guardadas.
        """
        from django.utils import timezone
        from .models import Currency, ExchangeRate, ExchangeRateSource

        now = timezone.now()

        # Obtener BOB
        if bob_currency is None:
            try:
                bob_currency = Currency.objects.get(code='BOB')
            except Currency.DoesNotExist:
                log.error("AGGREGATOR_SAVE_FAIL BOB currency not found")
                return 0

        saved = 0
        saved_rates: list[tuple[str, ExchangeRate]] = []

        for code, rate in aggregated.items():
            try:
                currency_from = Currency.objects.get(code=code)
            except Currency.DoesNotExist:
                log.warning("AGGREGATOR_SAVE_SKIP code=%s not in Currency table", code)
                continue

            source_obj = self._get_or_none_source(rate.sources)

            # Cerrar tasas activas previas del mismo tipo de mercado
            ExchangeRate.objects.filter(
                currency_from = currency_from,
                currency_to   = bob_currency,
                market_type   = rate.market_type,
                valid_until__isnull = True,
            ).update(valid_until=now, is_primary=False)

            try:
                from decimal import Decimal as _D
                avg = (rate.buy_rate + rate.sell_rate) / _D('2')
                new_rate = ExchangeRate(
                    currency_from = currency_from,
                    currency_to   = bob_currency,
                    market_type   = rate.market_type,
                    rate_source   = source_obj,
                    official_rate = rate.official_rate,
                    buy_rate      = rate.buy_rate,
                    sell_rate     = rate.sell_rate,
                    avg_rate      = avg.quantize(_D('0.0001')),
                    source        = ','.join(rate.sources[:3]),
                    valid_from    = now,
                    valid_until   = None,
                    source_method = getattr(rate, 'source_method', 'SCRAP'),
                    source_url    = getattr(rate, 'source_url', None),
                    fetched_at    = getattr(rate, 'fetched_at', None) or now,
                    confidence    = _D(str(round(rate.confidence, 3))),
                    is_validated  = False,
                    is_primary    = False,
                )
                new_rate.save()
                saved_rates.append((code, new_rate))
                saved += 1
                log.debug(
                    "AGGREGATOR_SAVED code=%s market=%s buy=%s sell=%s conf=%.2f "
                    "method=%s sources=%s",
                    code, rate.market_type, rate.buy_rate, rate.sell_rate,
                    rate.confidence, getattr(rate, 'source_method', '?'), rate.sources,
                )
            except Exception as exc:
                log.error(
                    "AGGREGATOR_SAVE_ERROR code=%s error=%s",
                    code, exc, exc_info=True,
                )

        # Mark primary rates after all saves
        self._mark_primary_rates(saved_rates, bob_currency)

        log.info("AGGREGATOR_SAVE_DONE saved=%d total=%d", saved, len(aggregated))
        return saved

    def _mark_primary_rates(
        self,
        saved_rates: list[tuple[str, 'ExchangeRate']],
        bob_currency,
    ) -> None:
        """
        For each currency, select the single best rate to be is_primary=True.

        Selection criteria (in order):
          1. NOT INFERENCE source_method
          2. Highest confidence
          3. Market priority: parallel > digital > bcb > official
        """
        from .models import Currency, ExchangeRate as ER

        by_currency: dict[str, list] = {}
        for code, rate in saved_rates:
            by_currency.setdefault(code, []).append(rate)

        # Also consider existing active non-primary rates for currencies
        # not updated in this batch
        for code, candidates in by_currency.items():
            try:
                cur = Currency.objects.get(code=code)
            except Currency.DoesNotExist:
                continue

            # Clear existing primary for this currency pair
            ER.objects.filter(
                currency_from = cur,
                currency_to   = bob_currency,
                is_primary    = True,
            ).update(is_primary=False)

            # Filter out INFERENCE
            eligible = [r for r in candidates if r.source_method != 'INFERENCE']
            if not eligible:
                eligible = candidates  # all are inference, pick best anyway

            # Score: confidence (0–1) + market_priority_bonus
            def _score(r):
                mp = MARKET_PRIORITY.get(r.market_type, 0)
                return float(r.confidence) + mp * 0.1

            best = max(eligible, key=_score)
            ER.objects.filter(pk=best.pk).update(is_primary=True)
            log.info(
                "PRIMARY_RATE_SET code=%s market=%s conf=%.2f method=%s id=%d",
                code, best.market_type, float(best.confidence),
                best.source_method, best.pk,
            )

    @staticmethod
    def _get_or_none_source(source_names: list[str]):
        """Intenta encontrar ExchangeRateSource por nombre. Retorna None si no existe."""
        from .models import ExchangeRateSource
        for name in source_names:
            try:
                return ExchangeRateSource.objects.get(name=name)
            except ExchangeRateSource.DoesNotExist:
                continue
        return None

    # ------------------------------------------------------------------ #
    #  API rápida: get_current_rate(currency_code)                         #
    # ------------------------------------------------------------------ #

    def get_current_rate(self, currency_code: str) -> AggregatedRate | None:
        """
        Obtiene la mejor tasa disponible para una divisa desde la DB.
        Prioriza: parallel > digital > bcb > official.
        No hace fetch en tiempo real — usa datos ya guardados.
        """
        from django.utils import timezone
        from .models import Currency, ExchangeRate

        try:
            currency = Currency.objects.get(code=currency_code.upper())
            bob      = Currency.objects.get(code='BOB')
        except Currency.DoesNotExist:
            return None

        for market in sorted(MARKET_PRIORITY, key=lambda m: MARKET_PRIORITY[m], reverse=True):
            rate = (
                ExchangeRate.objects
                .filter(
                    currency_from = currency,
                    currency_to   = bob,
                    market_type   = market,
                    valid_until__isnull = True,
                )
                .order_by('-valid_from')
                .first()
            )
            if rate:
                return AggregatedRate(
                    currency_code  = currency_code,
                    market_type    = rate.market_type,
                    buy_rate       = rate.buy_rate,
                    sell_rate      = rate.sell_rate,
                    official_rate  = rate.official_rate,
                    scale_factor   = currency.scale_factor,
                    confidence     = float(rate.confidence),
                    sources        = [rate.source or 'DB'],
                    source_count   = 1,
                    source_method  = rate.source_method,
                    source_url     = rate.source_url,
                    fetched_at     = rate.fetched_at,
                )

        return None
