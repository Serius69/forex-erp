"""
Tests para rates/scrapers/dolar_blue_bolivia.py

Cubre:
  - Extracción correcta con selectores CSS
  - Fallback a regex cuando CSS no resuelve
  - Manejo de errores de red (sitio caído → no crash)
  - Validación de rango (valores fuera de 8–15 rechazados)
  - Cálculo de mid cuando hay buy+sell
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

from rates.scrapers.dolar_blue_bolivia import scrape_parallel_rate, _parse_decimal


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_response(html: str, status_code: int = 200):
    """Crea un mock de httpx.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = html
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock
        )
    return mock


# ── Tests: _parse_decimal ─────────────────────────────────────────────────────

class TestParseDecimal:
    def test_clean_number(self):
        assert _parse_decimal("9.50") == Decimal("9.50")

    def test_comma_separator(self):
        assert _parse_decimal("9,50") == Decimal("9.50")

    def test_with_bs_prefix(self):
        assert _parse_decimal("Bs 10.20") == Decimal("10.20")

    def test_out_of_range_low(self):
        assert _parse_decimal("5.00") is None

    def test_out_of_range_high(self):
        assert _parse_decimal("20.00") is None

    def test_invalid_text(self):
        assert _parse_decimal("N/A") is None

    def test_boundary_min(self):
        assert _parse_decimal("8.00") == Decimal("8.00")

    def test_boundary_max(self):
        assert _parse_decimal("15.00") == Decimal("15.00")


# ── Tests: scrape_parallel_rate con CSS selectors ────────────────────────────

HTML_WITH_SELECTORS = """
<html><body>
  <div class="compra">9.30</div>
  <div class="venta">9.60</div>
  <div class="precio">9.45</div>
</body></html>
"""


class TestScrapeWithSelectors:
    @patch("rates.scrapers.dolar_blue_bolivia.httpx.get")
    def test_extracts_buy_sell_mid_from_css(self, mock_get):
        mock_get.return_value = _make_response(HTML_WITH_SELECTORS)

        result = scrape_parallel_rate()

        assert result["buy"]  == Decimal("9.30")
        assert result["sell"] == Decimal("9.60")
        assert result["mid"]  == Decimal("9.45")
        assert result["source_url"] == "https://dolarbluebolivia.click/"

    @patch("rates.scrapers.dolar_blue_bolivia.httpx.get")
    def test_calculates_mid_if_missing(self, mock_get):
        html = "<html><body><div class='compra'>9.20</div><div class='venta'>9.80</div></body></html>"
        mock_get.return_value = _make_response(html)

        result = scrape_parallel_rate()

        assert result["buy"]  == Decimal("9.20")
        assert result["sell"] == Decimal("9.80")
        assert result["mid"]  == (Decimal("9.20") + Decimal("9.80")) / Decimal("2")


# ── Tests: fallback regex ─────────────────────────────────────────────────────

HTML_NO_SELECTORS = """
<html><body>
  <p>Hoy el dólar blue en Bolivia cotiza a compra 9.35 y venta 9.65 bolivianos.</p>
</body></html>
"""

HTML_ONLY_NUMBERS = """
<html><body>
  <p>Precio actual: 9.40 / 9.70 BOB</p>
</body></html>
"""


class TestScrapeRegexFallback:
    @patch("rates.scrapers.dolar_blue_bolivia.httpx.get")
    def test_extracts_from_plain_text_regex(self, mock_get):
        mock_get.return_value = _make_response(HTML_NO_SELECTORS)

        result = scrape_parallel_rate()

        assert result["buy"] is not None
        assert result["sell"] is not None
        # buy debe ser menor que sell
        assert result["buy"] <= result["sell"]

    @patch("rates.scrapers.dolar_blue_bolivia.httpx.get")
    def test_fallback_two_numbers_min_max(self, mock_get):
        mock_get.return_value = _make_response(HTML_ONLY_NUMBERS)

        result = scrape_parallel_rate()

        assert result["buy"]  == Decimal("9.40")
        assert result["sell"] == Decimal("9.70")

    @patch("rates.scrapers.dolar_blue_bolivia.httpx.get")
    def test_out_of_range_numbers_ignored(self, mock_get):
        html = "<html><body><p>Año 2024, precio: 3.00 y 50.00 BOB. Tasa válida: 9.55</p></body></html>"
        mock_get.return_value = _make_response(html)

        result = scrape_parallel_rate()

        # Solo 9.55 es válido → mid debería ser ese valor
        assert result["mid"] == Decimal("9.55")


# ── Tests: manejo de errores ──────────────────────────────────────────────────

class TestScrapeErrorHandling:
    @patch("rates.scrapers.dolar_blue_bolivia.httpx.get")
    def test_http_error_raises(self, mock_get):
        """Errores de red deben propagarse para que el task de Celery haga retry."""
        import httpx
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            scrape_parallel_rate()

    @patch("rates.scrapers.dolar_blue_bolivia.httpx.get")
    def test_http_status_error_raises(self, mock_get):
        """500 del servidor → raise_for_status lanza excepción."""
        mock_get.return_value = _make_response("<html>error</html>", status_code=500)

        import httpx
        with pytest.raises(httpx.HTTPStatusError):
            scrape_parallel_rate()

    @patch("rates.scrapers.dolar_blue_bolivia.httpx.get")
    def test_empty_page_returns_none_values(self, mock_get):
        """HTML sin números válidos → retorna None en buy/sell/mid (no lanza excepción)."""
        mock_get.return_value = _make_response("<html><body><p>Hola mundo</p></body></html>")

        result = scrape_parallel_rate()

        assert result["buy"]  is None
        assert result["sell"] is None
        assert result["mid"]  is None
        assert result["source_url"] is not None

    @patch("rates.scrapers.dolar_blue_bolivia.httpx.get")
    def test_timeout_raises(self, mock_get):
        """Timeout debe propagarse para que Celery haga retry."""
        import httpx
        mock_get.side_effect = httpx.TimeoutException("timed out")

        with pytest.raises(httpx.TimeoutException):
            scrape_parallel_rate()
