"""
Normalizador de resultados de fetchers de tipos de cambio.

Responsabilidades:
  1. Validar y filtrar FetchResults inválidos o con valores anómalos
  2. Normalizar escala — asegurar que buy/sell estén en la escala correcta
  3. Enriquecer con metadatos (timestamp, fuente, spread_pct)
  4. Deduplicar — un resultado por (currency_code, source_name)
  5. Registrar advertencias si hay inconsistencias entre fuentes

Nota: El normalizer NO combina múltiples fuentes (eso es el aggregator).
Sólo limpia y valida los resultados individuales de cada fetcher.
"""
from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import NamedTuple

from .base import FetchResult

log = logging.getLogger('kapitalya.rates.normalizer')

# Rangos de sanidad por divisa (buy/sell por scale_factor unidades)
# (min_bob, max_bob) — fuera de este rango → descartar
SANITY_BOUNDS = {
    'USD': (Decimal('5.00'),   Decimal('15.00')),   # BCB 6.96 + margen amplio
    'EUR': (Decimal('5.00'),   Decimal('18.00')),
    'BRL': (Decimal('0.50'),   Decimal('4.00')),
    'ARS': (Decimal('3.00'),   Decimal('30.00')),    # por 1000 ARS
    'CLP': (Decimal('5.00'),   Decimal('20.00')),    # por 1000 CLP
    'PEN': (Decimal('1.00'),   Decimal('5.00')),
}


class NormalizedResult(NamedTuple):
    """Resultado normalizado listo para el aggregator."""
    currency_code:  str
    market_type:    str
    source_name:    str
    official_rate:  Decimal      # por unidad (BCB)
    buy_rate:       Decimal      # por scale_factor unidades
    sell_rate:      Decimal      # por scale_factor unidades
    scale_factor:   int
    confidence:     float
    spread_pct:     float
    fetched_at:     datetime
    raw_data:       dict


class RateNormalizer:
    """
    Normaliza y valida resultados crudos de los fetchers.

    Uso:
        normalizer = RateNormalizer()
        normalized = normalizer.normalize(fetch_results)
    """

    def normalize(self, results: list[FetchResult]) -> list[NormalizedResult]:
        """
        Normaliza una lista de FetchResult.
        Filtra inválidos, deduplica y enriquece con metadatos.
        """
        now       = datetime.now(tz=timezone.utc)
        seen      = {}   # (currency_code, source_name) → NormalizedResult (el de mayor confidence)
        discarded = 0

        for r in results:
            normalized = self._normalize_single(r, now)
            if normalized is None:
                discarded += 1
                continue

            key = (normalized.currency_code, normalized.source_name)
            existing = seen.get(key)
            if existing is None or normalized.confidence > existing.confidence:
                seen[key] = normalized

        output = list(seen.values())
        log.debug(
            "NORMALIZER input=%d valid=%d discarded=%d",
            len(results), len(output), discarded,
        )
        return output

    def _normalize_single(
        self, r: FetchResult, now: datetime
    ) -> NormalizedResult | None:
        """Normaliza y valida un FetchResult individual."""

        # 1. Validación básica de tipos
        if not isinstance(r.currency_code, str) or not r.currency_code:
            log.debug("NORM_SKIP no currency_code source=%s", r.source_name)
            return None

        code = r.currency_code.upper().strip()

        # 2. Validación numérica básica
        try:
            buy  = Decimal(str(r.buy_rate))
            sell = Decimal(str(r.sell_rate))
            off  = Decimal(str(r.official_rate))
        except Exception as exc:
            log.debug("NORM_DECIMAL_ERROR code=%s error=%s", code, exc)
            return None

        if buy <= 0 or sell <= 0 or off <= 0:
            log.debug("NORM_ZERO_RATE code=%s buy=%s sell=%s", code, buy, sell)
            return None

        if buy > sell:
            # Algunos scrapers invierten compra/venta — corregir si la diferencia es pequeña
            if sell / buy > Decimal('0.90'):
                log.debug("NORM_BUY_SELL_SWAP code=%s — intercambiando", code)
                buy, sell = sell, buy
            else:
                log.debug("NORM_INVALID_SPREAD code=%s buy=%s > sell=%s", code, buy, sell)
                return None

        # 3. Sanity bounds
        bounds = SANITY_BOUNDS.get(code)
        if bounds:
            lo, hi = bounds
            if not (lo <= buy <= hi) or not (lo <= sell <= hi):
                log.warning(
                    "NORM_OUT_OF_BOUNDS code=%s buy=%s sell=%s bounds=[%s, %s] source=%s — descartado",
                    code, buy, sell, lo, hi, r.source_name,
                )
                return None

        # 4. Confidence en rango [0,1]
        confidence = max(0.0, min(1.0, float(r.confidence)))

        # 5. Calcular spread %
        spread_pct = float((sell - buy) / buy * 100) if buy > 0 else 0.0

        # 6. Escala
        scale = int(r.scale_factor) if r.scale_factor and r.scale_factor >= 1 else 1

        return NormalizedResult(
            currency_code = code,
            market_type   = str(r.market_type),
            source_name   = str(r.source_name),
            official_rate = off,
            buy_rate      = buy,
            sell_rate     = sell,
            scale_factor  = scale,
            confidence    = confidence,
            spread_pct    = spread_pct,
            fetched_at    = now,
            raw_data      = r.raw_data or {},
        )

    def group_by_currency(
        self, normalized: list[NormalizedResult]
    ) -> dict[str, list[NormalizedResult]]:
        """Agrupa resultados normalizados por código de divisa."""
        groups: dict[str, list[NormalizedResult]] = {}
        for r in normalized:
            groups.setdefault(r.currency_code, []).append(r)
        return groups

    def group_by_market_type(
        self, normalized: list[NormalizedResult]
    ) -> dict[str, list[NormalizedResult]]:
        """Agrupa por tipo de mercado."""
        groups: dict[str, list[NormalizedResult]] = {}
        for r in normalized:
            groups.setdefault(r.market_type, []).append(r)
        return groups
