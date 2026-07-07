"""
Motor de consenso ponderado para calcular tasas de referencia
a partir de múltiples fuentes.

Algoritmo:
  1. Tomar todos los ExchangeRateRaw de los últimos WINDOW_MINUTES por par
  2. Aplicar Winsorización (recortar outliers al percentil 10-90)
  3. Ponderar por prioridad de fuente (ExchangeRateSource.priority)
  4. Calcular media ponderada
  5. Crear ExchangeRateConsensus y marcar vigente=True (único por par)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from django.utils import timezone

log = logging.getLogger('kapitalya.integrations.consensus')

WINDOW_MINUTES    = 10
WINSOR_LOWER_PCT  = 10
WINSOR_UPPER_PCT  = 90
MIN_SOURCES       = 2     # mínimo de fuentes para calcular consenso
_D = Decimal


def calculate_consensus(
    pairs: Optional[list[tuple[str, str]]] = None,
) -> dict[str, dict]:
    """
    Calcula y persiste el consenso para todos los pares (o los indicados).

    Returns:
        {
          "USD/BOB": {
            "consenso": "9.8200",
            "compra":   "9.7800",
            "venta":    "9.8600",
            "fuentes":  3,
            "confianza": 88,
            "tendencia": "ALCISTA",
            "cambio_pct_24h": "0.51",
          },
          ...
        }
    """
    from rates.models import ExchangeRateRaw, ExchangeRateConsensus, ExchangeRateSource

    now    = timezone.now()
    cutoff = now - __import__('datetime').timedelta(minutes=WINDOW_MINUTES)

    # Obtener todos los raw recientes y válidos
    raw_qs = (
        ExchangeRateRaw.objects
        .filter(timestamp_captura__gte=cutoff, es_valido=True)
        .values('moneda_base', 'moneda_cotizada', 'id_fuente_str',
                'precio_compra', 'precio_venta', 'precio_promedio')
    )

    if pairs:
        pair_filter = __import__('django.db.models', fromlist=['Q']).Q()
        Q = __import__('django.db.models', fromlist=['Q']).Q
        for base, cotiz in pairs:
            pair_filter |= Q(moneda_base=base, moneda_cotizada=cotiz)
        raw_qs = raw_qs.filter(pair_filter)

    # Agrupar por par
    from collections import defaultdict
    by_pair: dict[tuple, list[dict]] = defaultdict(list)
    for row in raw_qs:
        key = (row['moneda_base'], row['moneda_cotizada'])
        by_pair[key].append(row)

    # Pesos de fuente (id_fuente → priority)
    source_weights: dict[str, int] = {
        s.id_fuente: s.priority
        for s in ExchangeRateSource.objects.filter(id_fuente__isnull=False)
    }

    result: dict[str, dict] = {}

    for (base, cotiz), rows in by_pair.items():
        if len(rows) < MIN_SOURCES:
            log.debug('CONSENSUS_SKIP par=%s/%s sources=%d (< %d)',
                      base, cotiz, len(rows), MIN_SOURCES)
            continue

        par = f'{base}/{cotiz}'

        # Extraer precios de compra y venta
        compras  = [_D(str(r['precio_compra']))  for r in rows if r['precio_compra']]
        ventas   = [_D(str(r['precio_venta']))   for r in rows if r['precio_venta']]
        promedios = [_D(str(r['precio_promedio'])) for r in rows if r['precio_promedio']]

        ref_prices = promedios if promedios else compras
        if not ref_prices:
            continue

        # Winsorización
        ws = _winsorize(ref_prices)
        if not ws:
            continue

        # Pesos por fuente
        weighted_sum   = _D('0')
        total_weight   = _D('0')
        fuentes_usadas = []

        for row in rows:
            id_f  = row['id_fuente_str']
            peso  = _D(str(source_weights.get(id_f, 1)))
            precio = _D(str(row['precio_promedio'] or row['precio_compra']))
            if precio in ws:
                weighted_sum += precio * peso
                total_weight += peso
                fuentes_usadas.append({
                    'id_fuente':    id_f,
                    'peso':         float(peso),
                    'precio_compra': float(row['precio_compra'] or 0),
                    'precio_venta':  float(row['precio_venta'] or 0),
                })

        if total_weight == 0:
            consensus_price = sum(ws) / _D(str(len(ws)))
        else:
            consensus_price = weighted_sum / total_weight

        consensus_price = consensus_price.quantize(_D('0.00000001'))

        # Compra / Venta del consenso
        compra_cons = (_winsorize_mean(compras) if compras else None)
        venta_cons  = (_winsorize_mean(ventas)  if ventas  else None)

        # Confianza: basada en número de fuentes y dispersión
        confianza = _calc_confianza(len(rows), ws)

        # Tendencia vs 24h anterior
        cambio_pct, tendencia = _calc_tendencia(par, consensus_price)

        # Marcar vigente=False al anterior
        ExchangeRateConsensus.objects.filter(par=par, vigente=True).update(vigente=False)

        # Crear nuevo consenso
        ExchangeRateConsensus.objects.create(
            par              = par,
            moneda_base      = base,
            moneda_cotizada  = cotiz,
            precio_consenso  = consensus_price,
            precio_compra    = compra_cons,
            precio_venta     = venta_cons,
            fuentes_usadas   = fuentes_usadas,
            fuentes_count    = len(set(r['id_fuente_str'] for r in rows)),
            confianza_pct    = confianza,
            metodo_calculo   = 'WINSORIZED_MEAN',
            vigente          = True,
            cambio_pct_24h   = cambio_pct,
            tendencia        = tendencia,
        )

        result[par] = {
            'consenso':      str(consensus_price),
            'compra':        str(compra_cons) if compra_cons else None,
            'venta':         str(venta_cons)  if venta_cons  else None,
            'fuentes':       len(fuentes_usadas),
            'confianza':     confianza,
            'tendencia':     tendencia,
            'cambio_pct_24h': str(cambio_pct) if cambio_pct else None,
        }
        log.info('CONSENSUS par=%s price=%s sources=%d conf=%d%%',
                 par, consensus_price, len(fuentes_usadas), confianza)

    return result


# ── Helpers privados ──────────────────────────────────────────────────────────

def _winsorize(prices: list[Decimal]) -> list[Decimal]:
    """Recorta outliers al percentil 10-90 y retorna la lista filtrada."""
    if len(prices) < 3:
        return prices
    import statistics
    sorted_p = sorted(prices)
    lo_idx   = max(0, int(len(sorted_p) * WINSOR_LOWER_PCT / 100))
    hi_idx   = min(len(sorted_p) - 1, int(len(sorted_p) * WINSOR_UPPER_PCT / 100))
    return sorted_p[lo_idx:hi_idx + 1]


def _winsorize_mean(prices: list[Decimal]) -> Optional[Decimal]:
    if not prices:
        return None
    ws = _winsorize(prices)
    if not ws:
        return None
    return (sum(ws) / _D(str(len(ws)))).quantize(_D('0.00000001'))


def _calc_confianza(n_sources: int, winsorized: list[Decimal]) -> int:
    """Confianza 0-100 basada en N fuentes y dispersión relativa."""
    if not winsorized:
        return 0
    base = min(50 + n_sources * 10, 90)  # +10 por cada fuente, máx 90
    if len(winsorized) >= 2:
        mean = sum(winsorized) / _D(str(len(winsorized)))
        if mean > 0:
            cv = (max(winsorized) - min(winsorized)) / mean * 100
            if cv > 5:
                base = max(base - int(float(cv)), 40)
    return min(base, 99)


def _calc_tendencia(par: str, precio_actual: Decimal) -> tuple[Optional[Decimal], str]:
    """Calcula cambio % vs el consenso de hace 24h."""
    try:
        from rates.models import ExchangeRateConsensus
        import datetime
        hace_24h = timezone.now() - datetime.timedelta(hours=24)
        prev = (
            ExchangeRateConsensus.objects
            .filter(par=par, timestamp_calculo__lte=hace_24h)
            .order_by('-timestamp_calculo')
            .first()
        )
        if not prev or prev.precio_consenso == 0:
            return None, 'NEUTRAL'
        cambio = (precio_actual - prev.precio_consenso) / prev.precio_consenso * 100
        cambio = cambio.quantize(_D('0.0001'))
        if cambio > _D('0.1'):
            return cambio, 'ALCISTA'
        if cambio < _D('-0.1'):
            return cambio, 'BAJISTA'
        return cambio, 'NEUTRAL'
    except Exception:
        return None, 'NEUTRAL'
