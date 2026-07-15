"""
Referencia de mercado para los fallbacks de estimación (INFERENCE).

Antes los fetchers estimaban con constantes hardcodeadas (USD=9.60) que quedaban
obsoletas en cuanto el paralelo se movía — el 2026-07 el USD real estaba en 10.50
y el fallback seguía emitiendo 9.60 como si fuera dato. Este módulo reemplaza esas
constantes: la referencia es SIEMPRE la última tasa REAL observada en BD
(source_method ≠ INFERENCE) y, si no hay ninguna reciente, NO se estima nada.

Unidades: igual que `ExchangeRate` — BOB por `scale_factor` unidades de la divisa
(ARS/CLP van por 1000), que es también lo que esperan los SANITY_BOUNDS del
normalizador.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

log = logging.getLogger('kapitalya.rates.fetcher.reference')

# Máxima antigüedad de una tasa real para servir de referencia de estimación.
# Pasado esto, mejor no emitir nada que emitir un número viejo como si fuera hoy.
MAX_REFERENCE_AGE_DAYS = 7


def real_reference_rates(max_age_days: int = MAX_REFERENCE_AGE_DAYS) -> dict[str, Decimal]:
    """
    Última tasa media REAL por divisa vs BOB: {'USD': Decimal('10.54'), ...}.

    Solo considera filas con source_method distinto de INFERENCE (API/SCRAP/MANUAL)
    y valid_from dentro de la ventana. Devuelve {} si no hay nada utilizable —
    el caller debe interpretar eso como "no estimar".
    """
    from django.utils import timezone

    from ..models import ExchangeRate

    cutoff = timezone.now() - timedelta(days=max_age_days)
    rows = (
        ExchangeRate.objects
        .filter(currency_to__code='BOB', valid_from__gte=cutoff)
        .exclude(source_method='INFERENCE')
        .exclude(currency_from__code='BOB')
        .order_by('currency_from__code', '-valid_from')
        .values_list('currency_from__code', 'buy_rate', 'sell_rate')
    )

    refs: dict[str, Decimal] = {}
    for code, buy, sell in rows:
        if code in refs:
            continue  # ya tenemos la más reciente (orden -valid_from)
        if len(code) != 3:
            continue  # variantes internas (USD_CASH_LOOSE, etc.) no son base de estimación
        try:
            buy_d, sell_d = Decimal(buy), Decimal(sell)
        except Exception:
            continue
        if buy_d > 0 and sell_d > 0:
            refs[code] = (buy_d + sell_d) / 2

    if not refs:
        log.warning(
            'REFERENCE_EMPTY — sin tasas reales en %d días; los fallbacks de '
            'estimación no emitirán nada', max_age_days,
        )
    return refs
