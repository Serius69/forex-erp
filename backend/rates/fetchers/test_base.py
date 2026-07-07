"""Tests de FetchResult.is_valid — sanidad numérica de tasas (sin red ni Django)."""
from decimal import Decimal as D

from rates.fetchers.base import FetchResult


def _fr(buy, sell, official="6.96"):
    return FetchResult(
        currency_code="USD", market_type="parallel", source_name="test",
        official_rate=D(official), buy_rate=D(str(buy)), sell_rate=D(str(sell)),
    )


def test_valida_normal():
    assert _fr("9.30", "9.60").is_valid() is True


def test_rechaza_buy_mayor_que_sell():
    assert _fr("9.60", "9.30").is_valid() is False


def test_rechaza_no_positivos():
    assert _fr("-1", "9.60").is_valid() is False
    assert _fr("9.30", "0").is_valid() is False


def test_rechaza_spread_imposible():
    # sell > 2×buy => error de parseo (mezcla de dos números)
    assert _fr("9.30", "25.00").is_valid() is False


def test_acepta_spread_amplio_pero_plausible():
    # 9.30 -> 18.00 es < 2× (borde): sigue siendo válido
    assert _fr("9.30", "18.00").is_valid() is True
