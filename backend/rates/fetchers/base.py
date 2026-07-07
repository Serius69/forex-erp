"""
Base classes and shared types for all rate fetchers.

Convention:
  - Every fetcher returns List[FetchResult] — empty list on total failure
  - Rates are always expressed per scale_factor units (consistent with ExchangeRate model)
  - official_rate is always per-unit (BCB standard)
  - Fetchers never raise — they log and return []

Circuit Breaker states (stored in Redis):
  CLOSED  → normal operation
  OPEN    → failing, skip for OPEN_TIMEOUT seconds
  HALF_OPEN → probing after cooldown
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

log = logging.getLogger('kapitalya.rates.fetcher')

# Timeout HTTP por defecto (segundos)
DEFAULT_TIMEOUT = 10   # máximo 10s por request como especificado

# Circuit Breaker config
CB_FAILURE_THRESHOLD = 5       # fallos consecutivos para abrir el circuito
CB_OPEN_TIMEOUT      = 300     # segundos en OPEN antes de pasar a HALF_OPEN (5 min)
CB_REDIS_PREFIX      = 'cb:fetcher:'

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


# ── Circuit Breaker helpers ────────────────────────────────────────────────────

def _cb_key(source_name: str, field: str) -> str:
    return f"{CB_REDIS_PREFIX}{source_name}:{field}"


def cb_get_state(source_name: str) -> str:
    """Devuelve 'CLOSED', 'OPEN', o 'HALF_OPEN'. Nunca lanza."""
    try:
        from django.core.cache import cache
        state     = cache.get(_cb_key(source_name, 'state'), 'CLOSED')
        opened_at = cache.get(_cb_key(source_name, 'opened_at'))
        if state == 'OPEN' and opened_at:
            if time.time() - float(opened_at) >= CB_OPEN_TIMEOUT:
                cache.set(_cb_key(source_name, 'state'), 'HALF_OPEN', timeout=CB_OPEN_TIMEOUT * 2)
                return 'HALF_OPEN'
        return state
    except Exception:
        return 'CLOSED'


def cb_record_success(source_name: str) -> None:
    """Registra éxito: resetea contadores, cierra el circuito."""
    try:
        from django.core.cache import cache
        cache.set(_cb_key(source_name, 'state'),    'CLOSED', timeout=None)
        cache.set(_cb_key(source_name, 'failures'), 0,        timeout=None)
        cache.delete(_cb_key(source_name, 'opened_at'))
    except Exception:
        pass


def cb_record_failure(source_name: str) -> None:
    """Registra fallo: si supera el umbral, abre el circuito."""
    try:
        from django.core.cache import cache
        failures_key = _cb_key(source_name, 'failures')
        failures     = int(cache.get(failures_key) or 0) + 1
        cache.set(failures_key, failures, timeout=CB_OPEN_TIMEOUT * 4)
        if failures >= CB_FAILURE_THRESHOLD:
            cache.set(_cb_key(source_name, 'state'),     'OPEN',       timeout=CB_OPEN_TIMEOUT * 4)
            cache.set(_cb_key(source_name, 'opened_at'), str(time.time()), timeout=CB_OPEN_TIMEOUT * 4)
            log.warning(
                "CIRCUIT_BREAKER_OPEN source=%s failures=%d — pausing for %ds",
                source_name, failures, CB_OPEN_TIMEOUT,
            )
    except Exception:
        pass


def cb_get_all_states() -> dict:
    """Retorna estado de todos los circuit breakers registrados (para health check)."""
    try:
        from django.core.cache import cache
        from django.conf import settings
        import redis as redis_lib
        redis_url = getattr(settings, 'CACHES', {}).get('default', {}).get('LOCATION', '')
        if not redis_url:
            return {}
        r = redis_lib.from_url(redis_url, decode_responses=True)
        keys = r.keys(f"{CB_REDIS_PREFIX}*:state")
        result = {}
        for key in keys:
            source = key.replace(CB_REDIS_PREFIX, '').replace(':state', '')
            result[source] = cb_get_state(source)
        return result
    except Exception:
        return {}


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
        """Validación básica de sanidad numérica.

        Además de positividad y buy<=sell, descarta spreads imposibles
        (sell > 2×buy): un spread de FX real es de pocos %; un valor así indica
        un error de parseo (p. ej. el scraper mezcló dos números distintos).
        """
        try:
            return (
                self.buy_rate > 0
                and self.sell_rate > 0
                and self.official_rate > 0
                and self.buy_rate <= self.sell_rate
                and self.sell_rate <= self.buy_rate * Decimal('2')
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


_SPREAD_PLACES = Decimal('0.0001')


def apply_min_spread(
    mid: Decimal,
    spread_pct: Decimal = Decimal('0.002'),
) -> tuple[Decimal, Decimal]:
    """
    Devuelve (buy, sell) garantizando buy < sell.
    spread_pct=0.002 → 0.20% total (±0.10% cada lado).
    Usar cuando la fuente solo provee un único precio de referencia.
    """
    half = spread_pct / Decimal('2')
    buy  = (mid * (Decimal('1') - half)).quantize(_SPREAD_PLACES)
    sell = (mid * (Decimal('1') + half)).quantize(_SPREAD_PLACES)
    return buy, sell


class BaseFetcher:
    """
    Clase base para fetchers de tipos de cambio.
    Implementa Circuit Breaker (Redis), manejo de errores y logging.
    """
    source_name: str = 'unknown'
    market_type: str = 'parallel'

    def fetch(self) -> list[FetchResult]:
        """
        Punto de entrada principal con Circuit Breaker.
        Nunca lanza excepciones. Retorna [] si el circuito está OPEN
        o si la fuente falla.
        """
        state = cb_get_state(self.source_name)

        if state == 'OPEN':
            log.debug("CIRCUIT_BREAKER skip source=%s state=OPEN", self.source_name)
            return []

        try:
            results = self._fetch()
            valid   = [r for r in (results or []) if r.is_valid()]
            if valid:
                cb_record_success(self.source_name)
                log.info(
                    "FETCH_SUCCESS source=%s results=%d",
                    self.source_name, len(valid),
                )
            else:
                cb_record_failure(self.source_name)
                log.debug("FETCH_EMPTY source=%s — no valid rates returned", self.source_name)
            return valid
        except Exception as exc:
            cb_record_failure(self.source_name)
            log.error(
                "FETCH_ERROR source=%s error=%s",
                self.source_name, exc, exc_info=True,
            )
            return []

    def _fetch(self) -> list[FetchResult]:
        """Implementar en subclases."""
        raise NotImplementedError

    def _get_session(self):
        """Sesión requests con headers y timeout POR DEFECTO en cada request.

        `requests` IGNORA `Session.timeout`; el timeout solo aplica si se pasa por
        request. Usamos una subclase que inyecta DEFAULT_TIMEOUT en cada llamada,
        evitando cuelgues indefinidos que el circuit breaker no puede detectar
        (un cuelgue nunca "falla", solo bloquea el worker).
        """
        import requests

        class _TimeoutSession(requests.Session):
            def request(self, *args, **kwargs):
                kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
                return super().request(*args, **kwargs)

        s = _TimeoutSession()
        s.headers.update(DEFAULT_HEADERS)
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
