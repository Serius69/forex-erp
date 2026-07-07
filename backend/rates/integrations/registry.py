"""
Registro dinámico de fetchers activos.

Uso:
    from rates.integrations.registry import get_active_fetchers
    fetchers = get_active_fetchers()
    for f in fetchers:
        rates = f.fetch_safe()

El registro prioriza las fuentes activas en DB (is_active=True, necesita_revision=False).
"""
from __future__ import annotations

import logging
from typing import Type

from rates.integrations.base import AbstractRateFetcher

log = logging.getLogger('kapitalya.integrations.registry')

# ── Registro estático de clases disponibles ───────────────────────────────────
# Importaciones lazy para no fallar si una dependencia no está instalada

_FETCHER_CLASSES: dict[str, str] = {
    'binance_p2p_bob': 'rates.integrations.sources.binance_p2p.BinanceP2PMultiFetcher',
    'binance_p2p_ars': 'rates.integrations.sources.binance_p2p.BinanceP2PMultiFetcher',
    'binance_p2p_clp': 'rates.integrations.sources.binance_p2p.BinanceP2PMultiFetcher',
    'binance_p2p_pen': 'rates.integrations.sources.binance_p2p.BinanceP2PMultiFetcher',
    'binance_p2p_brl': 'rates.integrations.sources.binance_p2p.BinanceP2PMultiFetcher',
    'binance_p2p_eur': 'rates.integrations.sources.binance_p2p.BinanceP2PMultiFetcher',
    'bybit_p2p':       'rates.integrations.sources.bybit_p2p.BybitP2PIntFetcher',
    'bitget_p2p':      'rates.integrations.sources.bitget_p2p.BitgetP2PIntFetcher',
    'saldoar':         'rates.integrations.sources.saldoar.SaldoARIntFetcher',
    'eldorado':        'rates.integrations.sources.eldorado.EldoradoIntFetcher',
    'okx_convert':     'rates.integrations.sources.okx_convert.OKXConvertFetcher',
    'dolarbluebolivia_click': 'rates.integrations.sources.dolar_blue_bolivia.DolarBlueBoliviaIntFetcher',
    'usdtbol':              'rates.integrations.sources.aggregators.USDTBolFetcher',
    'ayudabolivia':         'rates.integrations.sources.aggregators.AyudaBoliviaFetcher',
    'dolarparalelobolivia': 'rates.integrations.sources.aggregators.DolarParaleloBoliviaFetcher',
    'dolarbolivia':         'rates.integrations.sources.aggregators.DolarBoliviaFetcher',
    'bolivianblue':         'rates.integrations.sources.aggregators.BolivianBlueFetcher',
    'boliviadolarblue':     'rates.integrations.sources.aggregators.BoliviaDolarBlueFetcher',
    'bolidolar':            'rates.integrations.sources.aggregators.BoliDolarFetcher',
}

# Cache en proceso: evitar reinstanciar cada 5 minutos
_fetcher_cache: dict[str, AbstractRateFetcher] = {}


def _import_class(dotted: str) -> Type[AbstractRateFetcher] | None:
    try:
        module_path, class_name = dotted.rsplit('.', 1)
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except Exception as exc:
        log.warning('REGISTRY_IMPORT_FAIL class=%s error=%s', dotted, exc)
        return None


def get_active_fetchers() -> list[AbstractRateFetcher]:
    """
    Retorna instancias de fetchers para todas las fuentes activas en DB.
    Omite fuentes con necesita_revision=True (bloqueadas temporalmente).
    """
    try:
        from rates.models import ExchangeRateSource
        active_ids = set(
            ExchangeRateSource.objects
            .filter(is_active=True, necesita_revision=False)
            .exclude(id_fuente__isnull=True)
            .values_list('id_fuente', flat=True)
        )
    except Exception as exc:
        log.error('REGISTRY_DB_FAIL %s — usando todos los fetchers registrados', exc)
        active_ids = set(_FETCHER_CLASSES.keys())

    fetchers: list[AbstractRateFetcher] = []
    seen_classes: set[str] = set()  # evitar instanciar BinanceMulti 6 veces

    for id_fuente, class_path in _FETCHER_CLASSES.items():
        if id_fuente not in active_ids:
            continue
        if class_path in seen_classes:
            continue

        cls = _import_class(class_path)
        if cls is None:
            continue

        try:
            instance = cls()
            fetchers.append(instance)
            seen_classes.add(class_path)
        except Exception as exc:
            log.warning('REGISTRY_INSTANTIATE_FAIL id=%s error=%s', id_fuente, exc)

    log.info('REGISTRY fetchers=%d active_ids=%d', len(fetchers), len(active_ids))
    return fetchers


def get_fetcher(id_fuente: str) -> AbstractRateFetcher | None:
    """Retorna un fetcher específico por id_fuente, o None si no existe."""
    class_path = _FETCHER_CLASSES.get(id_fuente)
    if not class_path:
        return None
    cls = _import_class(class_path)
    if cls is None:
        return None
    try:
        return cls()
    except Exception:
        return None
