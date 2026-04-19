"""
Base classes and shared types for all rate fetchers.

Convention:
  - Every fetcher returns List[FetchResult] — empty list on total failure
  - Rates are always expressed per scale_factor units (consistent with ExchangeRate model)
  - official_rate is always per-unit (BCB standard)
  - Fetchers never raise — they log and return []
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

log = logging.getLogger('kapitalya.rates.fetcher')

# Timeout HTTP por defecto (segundos)
DEFAULT_TIMEOUT = 12

# Headers comunes — evitar bloqueos básicos de anti-bot
DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/json,*/*',
    'Accept-Language': 'es-BO,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
}


@dataclass
class FetchResult:
    """
    Resultado normalizado de una consulta a una fuente de tipos de cambio.

    Convenciones de escala:
      official_rate → BOB por 1 unidad de la divisa (lo que publica BCB)
      buy_rate      → BOB por scale_factor unidades (lo que cotiza el mercado)
      sell_rate     → BOB por scale_factor unidades

    Para USD (scale=1):  official=6.96, buy=9.30, sell=9.60
    Para CLP (scale=1000): official=0.0076, buy=10.00, sell=10.60

    Trazabilidad (Phase 3):
      source_method → 'API' | 'SCRAP' | 'MANUAL' | 'INFERENCE'
      source_url    → URL exacta consultada (puede ser None)
      fetched_at    → datetime UTC de cuando se realizó la consulta
    """
    currency_code:  str
    market_type:    str           # 'official' | 'bcb' | 'digital' | 'parallel'
    source_name:    str
    official_rate:  Decimal
    buy_rate:       Decimal
    sell_rate:      Decimal
    scale_factor:   int = 1
    confidence:     float = 1.0   # 0.0–1.0, usado en la ponderación del agregador
    raw_data:       dict = field(default_factory=dict)
    # ── Trazabilidad ─────────────────────────────────────────────────────────
    source_method:  str = 'SCRAP'   # API | SCRAP | MANUAL | INFERENCE
    source_url:     Optional[str] = None
    fetched_at:     Optional[object] = None  # datetime, set by fetcher

    def is_valid(self) -> bool:
        """Validación básica de sanidad numérica."""
        try:
            return (
                self.buy_rate > 0
                and self.sell_rate > 0
                and self.official_rate > 0
                and self.buy_rate <= self.sell_rate
            )
        except Exception:
            return False

    @property
    def mid_rate(self) -> Decimal:
        return (self.buy_rate + self.sell_rate) / Decimal('2')

    @property
    def spread_pct(self) -> float:
        if self.buy_rate == 0:
            return 0.0
        return float((self.sell_rate - self.buy_rate) / self.buy_rate * 100)


class BaseFetcher:
    """
    Clase base para fetchers de tipos de cambio.
    Implementa manejo de errores, logging y reintentos básicos.
    """
    source_name: str = 'unknown'
    market_type: str = 'parallel'

    def fetch(self) -> list[FetchResult]:
        """
        Punto de entrada principal. Nunca lanza excepciones.
        Returns lista vacía si la fuente no está disponible.
        """
        try:
            results = self._fetch()
            valid   = [r for r in (results or []) if r.is_valid()]
            if valid:
                log.info(
                    "FETCH_SUCCESS source=%s results=%d",
                    self.source_name, len(valid),
                )
            else:
                log.warning("FETCH_EMPTY source=%s — no se obtuvieron tasas válidas", self.source_name)
            return valid
        except Exception as exc:
            log.error(
                "FETCH_ERROR source=%s error=%s",
                self.source_name, exc, exc_info=True,
            )
            return []

    def _fetch(self) -> list[FetchResult]:
        """Implementar en subclases."""
        raise NotImplementedError

    def _get_session(self):
        """Sesión requests con headers y timeout configurados."""
        import requests
        s = requests.Session()
        s.headers.update(DEFAULT_HEADERS)
        s.timeout = DEFAULT_TIMEOUT
        return s

    @staticmethod
    def _to_decimal(value: str | float | int | None, default: Decimal = Decimal('0')) -> Decimal:
        """Convierte cualquier valor numérico a Decimal de forma segura."""
        if value is None:
            return default
        try:
            cleaned = str(value).strip().replace(',', '.').replace(' ', '')
            return Decimal(cleaned)
        except Exception:
            return default
