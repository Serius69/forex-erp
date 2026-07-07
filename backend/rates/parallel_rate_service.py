# rates/parallel_rate_service.py
"""
Servicio de tasa paralela consolidada.

Agrega múltiples fuentes con pesos de confiabilidad usando una media
Winsorizada ponderada para eliminar outliers.  El resultado se publica
en Redis con TTL configurable (default 60 s).

La degradación elegante garantiza que siempre haya un valor disponible,
aun si varias fuentes fallan, usando la tasa histórica más reciente.

Webhook: cuando la tasa cambia más de WEBHOOK_THRESHOLD_PCT, llama a
todos los handlers registrados en PARALLEL_RATE_WEBHOOK_HANDLERS.
"""
import logging
import statistics
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger('rates.parallel')

# ── Constantes ─────────────────────────────────────────────────────────────────

_CACHE_KEY_TEMPLATE  = 'parallel_rate:{currency}'
_DEFAULT_TTL         = 60      # segundos
_WINSOR_PCT          = 0.10    # recorta 10% superior e inferior
_WEBHOOK_THRESHOLD   = Decimal('0.005')   # 0.5% cambio → webhook


@dataclass
class ParallelRateResult:
    currency:       str
    consensus_rate: Decimal          # tasa Winsorizada ponderada
    buy_rate:       Decimal
    sell_rate:      Decimal
    sources:        list[dict]       # [{name, rate, weight, timestamp}]
    source_count:   int
    confidence:     Decimal          # 0–1 según fuentes disponibles
    is_degraded:    bool             # True si se usó fallback histórico
    computed_at:    str


class ParallelRateService:
    """
    Agrega fuentes de tasa paralela y calcula la tasa de consenso.

    Uso:
        svc = ParallelRateService()
        result = svc.get_rate('USD')
        print(result.consensus_rate)
    """

    # ── Carga de fuentes desde DB ─────────────────────────────────────────────

    def _load_active_sources(self, currency: str) -> list[dict]:
        """
        Retorna las tasas paralelas activas de las fuentes para `currency`.
        Formato: [{name, rate, weight, source_type}]
        """
        from rates.models import ExchangeRate
        try:
            qs = (
                ExchangeRate.objects
                .select_related('rate_source', 'currency_from')
                .filter(
                    currency_from__code=currency,
                    currency_to__is_base_currency=True,
                    valid_until__isnull=True,
                    market_type__in=('paralelo_digital', 'paralelo_fisico_empresa',
                                     'paralelo_fisico_competencia', 'parallel', 'digital'),
                )
                .order_by('-valid_from')[:20]
            )
            sources = []
            for er in qs:
                weight = Decimal('1.00')
                if er.rate_source:
                    weight = er.rate_source.weight or Decimal('1.00')
                sources.append({
                    'name':       er.rate_source.name if er.rate_source else er.source,
                    'rate':       er.avg_rate or (er.buy_rate + er.sell_rate) / 2,
                    'buy_rate':   er.buy_rate,
                    'sell_rate':  er.sell_rate,
                    'weight':     weight,
                    'confidence': er.confidence,
                    'source_type': er.market_type,
                    'timestamp':  er.valid_from.isoformat() if er.valid_from else None,
                })
            return sources
        except Exception as exc:
            log.warning('PARALLEL_SOURCES_FAIL currency=%s err=%s', currency, exc)
            return []

    # ── Winsorización ponderada ───────────────────────────────────────────────

    @staticmethod
    def _winsorized_weighted_mean(
        sources: list[dict], winsor_pct: float = _WINSOR_PCT
    ) -> Decimal:
        """
        Media Winsorizada ponderada:
        1. Ordena las tasas.
        2. Descarta el winsor_pct superior e inferior.
        3. Calcula la media aritmética ponderada del rango central.
        """
        if not sources:
            raise ValueError('No hay fuentes disponibles')

        rates_weights = [(float(s['rate']), float(s['weight'])) for s in sources]
        rates_weights.sort(key=lambda x: x[0])

        n = len(rates_weights)
        cut = max(1, int(n * winsor_pct))
        trimmed = rates_weights[cut: n - cut] if n > 2 * cut else rates_weights

        total_weight = sum(w for _, w in trimmed)
        if total_weight == 0:
            total_weight = len(trimmed)
            weighted_sum = sum(r for r, _ in trimmed)
        else:
            weighted_sum = sum(r * w for r, w in trimmed)

        mean = weighted_sum / total_weight
        return Decimal(str(mean)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

    # ── Spread típico por moneda ──────────────────────────────────────────────

    @staticmethod
    def _typical_spread(currency: str) -> Decimal:
        """Spread típico (buy/sell) en unidades absolutas de BOB."""
        spreads = {
            'USD': Decimal('0.10'),
            'EUR': Decimal('0.12'),
            'BRL': Decimal('0.05'),
            'ARS': Decimal('0.02'),
            'CLP': Decimal('0.05'),
        }
        return spreads.get(currency, Decimal('0.10'))

    # ── Fallback histórico ────────────────────────────────────────────────────

    def _get_historical_fallback(self, currency: str) -> Optional[Decimal]:
        """Última tasa paralela registrada en DB como fallback."""
        try:
            from rates.models import ExchangeRate
            er = (
                ExchangeRate.objects
                .filter(
                    currency_from__code=currency,
                    currency_to__is_base_currency=True,
                    market_type__in=('paralelo_digital', 'paralelo_fisico_empresa', 'parallel'),
                )
                .order_by('-valid_from')
                .first()
            )
            if er:
                return er.avg_rate or (er.buy_rate + er.sell_rate) / 2
        except Exception:
            pass
        return None

    # ── API pública ───────────────────────────────────────────────────────────

    def get_rate(self, currency: str = 'USD', force_refresh: bool = False) -> ParallelRateResult:
        """
        Retorna la tasa paralela de consenso para `currency`.
        Usa caché Redis; force_refresh=True salta la caché.
        """
        cache_key = _CACHE_KEY_TEMPLATE.format(currency=currency)
        ttl = getattr(settings, 'PARALLEL_RATE_CACHE_TTL', _DEFAULT_TTL)

        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                return ParallelRateResult(**cached)

        sources = self._load_active_sources(currency)
        is_degraded = False
        confidence = Decimal('1.00')

        if not sources:
            fallback = self._get_historical_fallback(currency)
            if fallback:
                is_degraded = True
                confidence  = Decimal('0.40')
                sources = [{'name': 'historical_fallback', 'rate': fallback, 'weight': Decimal('1'), 'confidence': confidence}]
            else:
                # Sin datos en absoluto — retornar resultado vacío
                log.error('PARALLEL_RATE_NO_DATA currency=%s', currency)
                return ParallelRateResult(
                    currency=currency,
                    consensus_rate=Decimal('0'),
                    buy_rate=Decimal('0'),
                    sell_rate=Decimal('0'),
                    sources=[],
                    source_count=0,
                    confidence=Decimal('0'),
                    is_degraded=True,
                    computed_at=timezone.now().isoformat(),
                )
        else:
            # Confianza basada en fuentes disponibles (max esperado: 5)
            confidence = min(Decimal(str(len(sources) / 5)), Decimal('1.00'))

        consensus = self._winsorized_weighted_mean(sources)
        spread    = self._typical_spread(currency)
        buy_rate  = (consensus - spread / 2).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        sell_rate = (consensus + spread / 2).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

        result = ParallelRateResult(
            currency=currency,
            consensus_rate=consensus,
            buy_rate=buy_rate,
            sell_rate=sell_rate,
            sources=sources,
            source_count=len(sources),
            confidence=confidence,
            is_degraded=is_degraded,
            computed_at=timezone.now().isoformat(),
        )

        # Publicar en Redis
        try:
            prev_cached = cache.get(cache_key)
            result_dict = result.__dict__.copy()
            # Decimal no es serializable por defecto en algunos backends
            for k, v in result_dict.items():
                if isinstance(v, Decimal):
                    result_dict[k] = str(v)
            cache.set(cache_key, result_dict, ttl)

            # Webhook si cambio supera umbral
            if prev_cached:
                prev_rate = Decimal(str(prev_cached.get('consensus_rate', 0)))
                if prev_rate and abs(consensus - prev_rate) / prev_rate > _WEBHOOK_THRESHOLD:
                    self._fire_webhooks(currency, prev_rate, consensus)
        except Exception as exc:
            log.warning('PARALLEL_RATE_CACHE_FAIL err=%s', exc)

        return result

    def get_cached_rate(self, currency: str = 'USD') -> Optional[Decimal]:
        """Retorna solo el valor numérico desde caché (None si no hay datos)."""
        cache_key = _CACHE_KEY_TEMPLATE.format(currency=currency)
        cached = cache.get(cache_key)
        if cached:
            return Decimal(str(cached.get('consensus_rate', 0)))
        result = self.get_rate(currency)
        return result.consensus_rate if result.consensus_rate else None

    def invalidate(self, currency: str = 'USD') -> None:
        """Fuerza recarga en próximo acceso."""
        cache.delete(_CACHE_KEY_TEMPLATE.format(currency=currency))

    # ── Webhook interno ───────────────────────────────────────────────────────

    def _fire_webhooks(self, currency: str, prev_rate: Decimal, new_rate: Decimal) -> None:
        """Notifica a handlers registrados cuando la tasa cambia > umbral."""
        try:
            handlers = getattr(settings, 'PARALLEL_RATE_WEBHOOK_HANDLERS', [])
            change_pct = float((new_rate - prev_rate) / prev_rate * 100)
            payload = {
                'currency':   currency,
                'prev_rate':  str(prev_rate),
                'new_rate':   str(new_rate),
                'change_pct': round(change_pct, 4),
                'timestamp':  timezone.now().isoformat(),
            }
            for handler_path in handlers:
                try:
                    module_path, func_name = handler_path.rsplit('.', 1)
                    import importlib
                    mod  = importlib.import_module(module_path)
                    func = getattr(mod, func_name)
                    func(payload)
                except Exception as exc:
                    log.warning('PARALLEL_WEBHOOK_FAIL handler=%s err=%s', handler_path, exc)
        except Exception as exc:
            log.warning('PARALLEL_WEBHOOK_ERR err=%s', exc)
