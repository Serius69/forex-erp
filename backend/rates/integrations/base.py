"""
Clase base abstracta para todos los fetchers de la capa integrations/.

Contrato:
  - fetch()      → list[NormalizedRate]  — puede lanzar
  - fetch_safe() → list[NormalizedRate]  — NUNCA lanza, loggea y retorna []
  - validate()   → bool                 — rango por par de monedas

Diferencia con fetchers/base.py (legacy BaseFetcher):
  BaseFetcher retorna FetchResult y escribe directamente en ExchangeRate.
  AbstractRateFetcher retorna NormalizedRate y delega la persistencia al task.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional

from rates.schemas import NormalizedRate

log = logging.getLogger('kapitalya.integrations')

DEFAULT_TIMEOUT = 15

DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept':          'text/html,application/xhtml+xml,application/json,*/*;q=0.9',
    'Accept-Language': 'es-BO,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control':   'no-cache',
    'Pragma':          'no-cache',
}

# Rangos de validación BOB por par (compra mínima, venta máxima)
VALID_RANGES: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
    ('USD', 'BOB'): (Decimal('7.0'),   Decimal('15.0')),
    ('EUR', 'BOB'): (Decimal('8.0'),   Decimal('18.0')),
    ('BRL', 'BOB'): (Decimal('0.5'),   Decimal('5.0')),
    ('ARS', 'BOB'): (Decimal('0.001'), Decimal('0.20')),
    ('PEN', 'BOB'): (Decimal('1.0'),   Decimal('5.0')),
    ('CLP', 'BOB'): (Decimal('0.005'), Decimal('0.05')),
    ('CNY', 'BOB'): (Decimal('0.5'),   Decimal('5.0')),
    ('GBP', 'BOB'): (Decimal('9.0'),   Decimal('22.0')),
    ('USDT', 'BOB'): (Decimal('7.0'),  Decimal('15.0')),
}


class AbstractRateFetcher(ABC):
    id_fuente:       str  = ''           # slug único, definir en subclase
    tipo_fuente:     str  = 'P2P'        # P2P | AGREGADOR | EXCHANGE | WALLET
    pares_soportados: list = []          # [("USD","BOB"), ...]
    timeout:         int  = DEFAULT_TIMEOUT

    # ── Interfaz pública ──────────────────────────────────────────────────────

    @abstractmethod
    def fetch(self) -> list[NormalizedRate]:
        """Consulta la fuente y retorna lista de NormalizedRate. Puede lanzar."""

    def fetch_safe(self) -> list[NormalizedRate]:
        """Llama fetch() con try/except. Nunca lanza excepción al caller."""
        try:
            results = self.fetch()
            valid, invalid = [], []
            for r in results:
                if self.validate(r):
                    valid.append(r)
                else:
                    r.es_valido = False
                    r.notas     = (r.notas + ' [RANGO_INVALIDO]').strip()
                    invalid.append(r)
            all_results = valid + invalid
            log.info(
                'FETCH_SAFE id=%s valid=%d invalid=%d',
                self.id_fuente, len(valid), len(invalid),
            )
            return all_results
        except Exception as exc:
            log.error('FETCH_SAFE_ERROR id=%s error=%s', self.id_fuente, exc, exc_info=True)
            self._mark_needs_revision()
            return []

    def validate(self, rate: NormalizedRate) -> bool:
        """Valida que el precio esté dentro del rango esperado para el par."""
        key = (rate.moneda_base, rate.moneda_cotizada)
        rng = VALID_RANGES.get(key)
        if rng is None:
            return True  # par desconocido: aceptar y dejar que el analista revise
        lo, hi = rng
        precio = rate.precio_compra or rate.precio
        return lo <= precio <= hi

    # ── Session helper ────────────────────────────────────────────────────────

    def _get_session(self):
        import requests
        s = requests.Session()
        s.headers.update(DEFAULT_HEADERS)
        return s

    @staticmethod
    def _to_decimal(value, default: Decimal = Decimal('0')) -> Decimal:
        if value is None:
            return default
        try:
            cleaned = str(value).strip().replace(',', '.').replace(' ', '')
            return Decimal(cleaned)
        except Exception:
            return default

    def _mark_needs_revision(self) -> None:
        try:
            from rates.models import ExchangeRateSource
            ExchangeRateSource.objects.filter(id_fuente=self.id_fuente).update(
                necesita_revision=True)
        except Exception:
            pass
