"""
Scraper standalone para dolarbluebolivia.click — fuente única de tasas.

Retorna tasa paralela USD/BOB (compra, venta, mid).
Sin dependencias del framework fetcher base — usable directamente desde tasks.
"""
from __future__ import annotations
import logging
import re
from decimal import Decimal
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger('kapitalya.scrapers.dolar_blue_bolivia')

DOLAR_BLUE_URL = "https://dolarbluebolivia.click/"

# Selectores CSS en orden de preferencia
SELECTORS = {
    "buy":  [".compra", ".precio-compra", "[data-type='compra']", ".buy-price",
             "[class*='compra']", "[id*='compra']"],
    "sell": [".venta",  ".precio-venta",  "[data-type='venta']",  ".sell-price",
             "[class*='venta']", "[id*='venta']"],
    "mid":  [".precio", ".rate", ".cotizacion", ".dolar-blue",
             "[class*='precio']", "[class*='cotizacion']"],
}

# Regex fallback — rango realista USD/BOB paralelo (8.50 – 14.00)
RATE_REGEX = re.compile(r'\b((?:8|9|10|11|12|13|14)[\.,]\d{1,4})\b')

_MIN_BOB = Decimal("8.0")
_MAX_BOB = Decimal("15.0")


def _parse_decimal(text: str) -> Optional[Decimal]:
    """Convierte texto a Decimal, limpia separadores y valida rango BOB."""
    cleaned = (
        str(text).strip()
        .replace(",", ".")
        .replace("Bs", "")
        .replace("$", "")
        .replace(" ", "")
    )
    try:
        val = Decimal(cleaned)
        if _MIN_BOB <= val <= _MAX_BOB:
            return val
    except Exception:
        pass
    return None


def scrape_parallel_rate() -> dict:
    """
    Scrape dolarbluebolivia.click y retorna tasas paralelas USD/BOB.

    Returns:
        {
            "buy":        Decimal | None,
            "sell":       Decimal | None,
            "mid":        Decimal | None,
            "source_url": str,
        }

    Raises:
        httpx.HTTPError: si el sitio no responde (para que el task haga retry).
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-BO,es;q=0.9,en;q=0.7",
    }

    resp = httpx.get(DOLAR_BLUE_URL, headers=headers, timeout=15, follow_redirects=True)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    result: dict = {"buy": None, "sell": None, "mid": None, "source_url": DOLAR_BLUE_URL}

    # Estrategia 1: selectores CSS
    for key, selectors in SELECTORS.items():
        for sel in selectors:
            try:
                el = soup.select_one(sel)
                if el:
                    val = _parse_decimal(el.get_text())
                    if val:
                        result[key] = val
                        break
            except Exception:
                continue

    # Estrategia 2: regex sobre texto completo si faltan valores
    if not result["mid"] or not result["buy"]:
        all_text = soup.get_text(" ", strip=True)
        raw_matches = RATE_REGEX.findall(all_text)
        valid = sorted(set(
            Decimal(m.replace(",", "."))
            for m in raw_matches
            if _MIN_BOB <= Decimal(m.replace(",", ".")) <= _MAX_BOB
        ))
        if valid:
            if not result["buy"]:
                result["buy"]  = valid[0]          # mínimo → compra
            if not result["sell"] and len(valid) >= 2:
                result["sell"] = valid[-1]          # máximo → venta
            if not result["mid"]:
                result["mid"]  = valid[len(valid) // 2]

    # Calcular mid si tenemos buy+sell pero no mid
    if result["buy"] and result["sell"] and not result["mid"]:
        result["mid"] = (result["buy"] + result["sell"]) / Decimal("2")

    logger.info(
        "DOLAR_BLUE_SCRAPED buy=%s sell=%s mid=%s",
        result["buy"], result["sell"], result["mid"],
    )
    return result
