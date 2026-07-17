"""
Utilidades centrales de tasas — mercado paralelo boliviano.

Regla: NUNCA usar BCB ni tasa oficial. Fuente única: mercado paralelo.
"""
from __future__ import annotations

import logging
from decimal import Decimal

log = logging.getLogger('kapitalya.rates.utils')

# Tipos de mercado aceptados (orden de prioridad descendente)
_PARALLEL_MARKETS = [
    'paralelo_digital',
    'paralelo_fisico_empresa',
    'paralelo_fisico_competencia',
]


def get_tasa_paralela(
    currency_from: str = 'USD',
    currency_to: str = 'BOB',
) -> 'ExchangeRate | dict | None':
    """
    Retorna la tasa paralela más reciente y confiable para un par de divisas.

    Estrategia:
      1. Redis (actualizado cada 5 min por Celery) — struct dict con 'rate', 'confidence'
      2. DB — última ExchangeRate paralela ordenada por confidence DESC

    Returns ExchangeRate ORM instance (o dict si viene de caché) o None si no hay datos.
    NUNCA retorna tasas BCB u oficiales.
    """
    from django.core.cache import cache
    from .models import ExchangeRate, Currency

    # 1. Intentar desde Redis
    cache_key = f'rates:paralelo:{currency_from.upper()}:{currency_to.upper()}'
    cached = cache.get(cache_key)
    if cached and not cached.get('stale'):
        return cached

    # 2. Fallback: DB — tasa paralela más confiable activa
    try:
        currency = Currency.objects.get(code=currency_from.upper())
        bob = Currency.objects.get(code=currency_to.upper())
    except Currency.DoesNotExist:
        log.warning('get_tasa_paralela: divisa no encontrada %s/%s', currency_from, currency_to)
        return None

    for market in _PARALLEL_MARKETS:
        rate = (
            ExchangeRate.objects
            .filter(
                currency_from=currency,
                currency_to=bob,
                market_type=market,
                valid_until__isnull=True,
            )
            .order_by('-confidence', '-valid_from')
            .first()
        )
        if rate:
            log.debug(
                'get_tasa_paralela %s/%s market=%s buy=%s sell=%s conf=%s',
                currency_from, currency_to, market, rate.buy_rate, rate.sell_rate, rate.confidence,
            )
            return rate

    log.warning('get_tasa_paralela: sin datos paralelos para %s/%s', currency_from, currency_to)
    return None


def get_mid_paralelo(currency_from: str = 'USD', currency_to: str = 'BOB') -> Decimal | None:
    """Retorna solo el mid-rate paralelo como Decimal, o None."""
    tasa = get_tasa_paralela(currency_from, currency_to)
    if tasa is None:
        return None
    if isinstance(tasa, dict):
        v = tasa.get('rate') or tasa.get('mid')
        return Decimal(str(v)) if v else None
    return (tasa.buy_rate + tasa.sell_rate) / Decimal('2')
