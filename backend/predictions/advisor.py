"""
Asesor de compra/venta de divisas — compone TODAS las señales reales del
sistema en una recomendación explicable (sin LLM: determinista y auditable).

Señales (cada una con peso y dirección):
  1. Pronóstico ML 24h/7d (ensemble, cadena de mercados) vs tasa actual
  2. Brecha oficial BCB ↔ paralelo (serie 'official' + macro)
  3. Sentimiento de noticias (índice RSS [-1,1], media-vida 24 h)
  4. Probabilidad de subida por simulación Monte Carlo (bootstrap real)
  5. Posición actual de inventario (¿ya estás cargado de esa divisa?)
  6. Última recomendación del motor AI de pricing

Salida: COMPRAR / ESPERAR / VENDER + score compuesto + razones en español.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger('kapitalya.predictions.advisor')

KNOWN = ('USD', 'EUR', 'BRL', 'PEN', 'CLP', 'ARS')

_ALIASES = {
    'dolar': 'USD', 'dólar': 'USD', 'dolares': 'USD', 'dólares': 'USD',
    'verdes': 'USD', 'euro': 'EUR', 'euros': 'EUR',
    'real': 'BRL', 'reales': 'BRL', 'sol': 'PEN', 'soles': 'PEN',
    'peso chileno': 'CLP', 'pesos chilenos': 'CLP',
    'peso argentino': 'ARS', 'pesos argentinos': 'ARS',
}

# Pesos del score compuesto (suman 1.0)
W_FORECAST = 0.35
W_SENT     = 0.20
W_MC       = 0.20
W_BRECHA   = 0.15
W_AI       = 0.10

# Umbral de decisión sobre el score ∈ [-1, 1]
TH = 0.15


def parse_message(message: str) -> dict:
    """Detecta divisa e intención en la pregunta del usuario."""
    t = (message or '').lower()
    currency = 'USD'
    for code in KNOWN:
        if re.search(rf'\b{code.lower()}\b', t):
            currency = code
            break
    else:
        for alias, code in _ALIASES.items():
            if alias in t:
                currency = code
                break

    if any(w in t for w in ('vender', 'vendo', 'venta', 'me deshago', 'suelto')):
        intent = 'vender'
    elif any(w in t for w in ('comprar', 'compro', 'compra', 'acumular', 'meter')):
        intent = 'comprar'
    else:
        intent = 'general'
    return {'currency': currency, 'intent': intent}


# ── Recolección de señales ─────────────────────────────────────────────────────

def _signal_forecast(pair: str) -> dict | None:
    """
    Dirección esperada 24h según el ensemble (caché → cadena de mercados).

    OJO: el delta se calcula contra la tasa actual DEL MISMO mercado del
    pronóstico — comparar un forecast de competencia (serie física) contra la
    tasa digital vigente fabricaba deltas gigantes ficticios.
    """
    from django.core.cache import cache

    for mkt in ('web', 'competencia', 'empresa'):
        data = cache.get(f'ml_forecast:{pair}:{mkt}:24h')
        if isinstance(data, dict) and not data.get('is_inference'):
            cur = _mid_actual(pair.split('/')[0], market=mkt)
            pred = data.get('predicted_rate')
            if not cur or not pred:
                continue
            delta_pct = (float(pred) / float(cur) - 1) * 100
            if abs(delta_pct) > 8:      # cruce de series/datos viejos — no fiable
                log.info('advisor forecast skip %s/%s delta=%s%%', pair, mkt,
                         round(delta_pct, 1))
                continue
            return {
                'market': mkt,
                'predicted_rate': round(float(pred), 4),
                'current_rate': round(float(cur), 4),
                'delta_pct': round(delta_pct, 2),
                # normalizar: ±1% en 24h ya es señal fuerte
                'score': max(-1.0, min(1.0, delta_pct / 1.0)),
            }
    return None


# market del forecast → market_types de ExchangeRate (mismo mapa que el ML)
_MKT_TYPES = {
    'web':         ('paralelo_digital', 'parallel', 'digital'),
    'competencia': ('paralelo_fisico_competencia',),
    'empresa':     ('paralelo_fisico_empresa',),
}


def _mid_actual(code: str, market: str = 'web'):
    from rates.models import ExchangeRate
    base = ExchangeRate.objects.filter(
        currency_from__code=code, currency_to__code='BOB',
        market_type__in=_MKT_TYPES.get(market, _MKT_TYPES['web']),
    ).exclude(source='ESTIMADO_LOCF').exclude(source_method='INFERENCE')
    r = (base.filter(valid_until__isnull=True).order_by('-valid_from').first()
         or base.order_by('-valid_from').first())   # series sin vigente (física)
    return (float(r.buy_rate) + float(r.sell_rate)) / 2 if r else None


def _signal_sentiment() -> dict | None:
    from macro.models import MacroIndicator, NewsItem
    idx = MacroIndicator.latest('sentimiento_dolar')
    if idx is None:
        return None
    top = (NewsItem.objects.exclude(sentiment=0)
           .order_by('-published_at').first())
    return {
        'index': float(idx.value),
        'date': str(idx.date),
        'headline': top.title[:120] if top else None,
        'score': max(-1.0, min(1.0, float(idx.value))),
    }


def _signal_brecha() -> dict | None:
    from macro.models import MacroIndicator
    rows = list(MacroIndicator.objects.filter(series='brecha_oficial_pct')
                .order_by('-date')[:7])
    if not rows:
        return None
    actual = float(rows[0].value)
    prev = float(rows[-1].value) if len(rows) > 1 else actual
    tendencia = actual - prev
    # brecha alta y creciendo → presión alcista sobre el paralelo
    score = max(-1.0, min(1.0, actual / 10 + tendencia / 5))
    return {'brecha_pct': round(actual, 2), 'tendencia_pp': round(tendencia, 2),
            'score': round(score, 3)}


def _signal_montecarlo(pair: str) -> dict | None:
    try:
        from predictions.simulation import load_series, simulate_paths
        series = load_series(pair, market='web' if pair == 'USD/BOB' else 'competencia')
        sim = simulate_paths(series, horizon_days=7, n_paths=500,
                             method='bootstrap', seed=None)
        p_up = sim['final_distribution']['prob_above_last']
        return {
            'prob_sube_7d': round(p_up, 3),
            'sigma_anual_pct': sim['params']['sigma_annual_pct'],
            'score': max(-1.0, min(1.0, (p_up - 0.5) * 4)),   # 0.75→+1
        }
    except Exception as exc:
        log.info('advisor MC skip %s: %s', pair, exc)
        return None


def _signal_posicion(code: str) -> dict | None:
    try:
        from django.db.models import F, Sum
        from inventory.models import CurrencyInventory
        agg = (CurrencyInventory.objects.filter(currency__code=code)
               .aggregate(stock=Sum(F('physical_balance') + F('digital_balance')),
                          maximo=Sum('maximum_stock')))
        stock = float(agg['stock'] or 0)
        maximo = float(agg['maximo'] or 0)
        pct = (stock / maximo * 100) if maximo else None
        return {'stock': stock, 'stock_pct_max': round(pct, 1) if pct else None}
    except Exception:
        return None


def _signal_ai(code: str) -> dict | None:
    from rates.models import ExchangeRateDecisionLog
    d = (ExchangeRateDecisionLog.objects.filter(currency_code=code)
         .order_by('-created_at').first())
    if d is None:
        return None
    rec = (d.recommendation or '').lower()
    score = 0.3 if 'demanda alta' in rec or 'subir' in rec else \
            -0.3 if 'demanda baja' in rec or 'reduc' in rec else 0.0
    return {'recomendacion': d.recommendation, 'score': score}


# ── Composición ────────────────────────────────────────────────────────────────

def advise(message: str) -> dict:
    parsed = parse_message(message)
    code = parsed['currency']
    pair = f'{code}/BOB'

    forecast = _signal_forecast(pair)
    sent     = _signal_sentiment()
    brecha   = _signal_brecha() if code == 'USD' else None
    mc       = _signal_montecarlo(pair)
    posicion = _signal_posicion(code)
    ai       = _signal_ai(code)

    score, peso_total = 0.0, 0.0
    for sig, w in ((forecast, W_FORECAST), (sent, W_SENT), (mc, W_MC),
                   (brecha, W_BRECHA), (ai, W_AI)):
        if sig is not None and 'score' in sig:
            score += sig['score'] * w
            peso_total += w
    score = round(score / peso_total, 3) if peso_total else 0.0

    if score > TH:
        decision, verbo = 'COMPRAR', 'comprar'
    elif score < -TH:
        decision, verbo = 'VENDER', 'vender (o no comprar)'
    else:
        decision, verbo = 'ESPERAR', 'esperar'

    confianza = min(0.95, 0.5 + abs(score))

    # ── Razones en español ────────────────────────────────────────────────────
    razones = []
    if forecast:
        dir_txt = 'subida' if forecast['delta_pct'] >= 0 else 'bajada'
        razones.append(
            f"El ensemble ML proyecta {dir_txt} de {abs(forecast['delta_pct']):.2f}% "
            f"en 24h ({forecast['current_rate']} → {forecast['predicted_rate']}, "
            f"serie {forecast['market']}).")
    if mc:
        razones.append(
            f"Monte Carlo (retornos reales): {mc['prob_sube_7d']*100:.0f}% de "
            f"probabilidad de que suba en 7 días (σ anual {mc['sigma_anual_pct']}%).")
    if sent:
        lbl = 'alcista' if sent['index'] > 0.15 else 'bajista' if sent['index'] < -0.15 else 'neutral'
        razones.append(
            f"Sentimiento de noticias {lbl} ({sent['index']:+.2f})"
            + (f': "{sent["headline"]}"' if sent.get('headline') else '.'))
    if brecha:
        razones.append(
            f"Brecha oficial BCB↔paralelo: {brecha['brecha_pct']}% "
            f"({'ampliándose' if brecha['tendencia_pp'] > 0.2 else 'cerrándose' if brecha['tendencia_pp'] < -0.2 else 'estable'} "
            f"{brecha['tendencia_pp']:+.2f}pp en 7 días).")
    if ai and ai.get('recomendacion'):
        razones.append(f"Motor AI de pricing: {ai['recomendacion']}.")
    if posicion and posicion.get('stock'):
        extra = ''
        if posicion.get('stock_pct_max') and posicion['stock_pct_max'] > 80:
            extra = ' — inventario cerca del máximo: cuidado con sobre-exponerte'
            if decision == 'COMPRAR':
                decision, verbo = 'ESPERAR', 'esperar'
                razones.append('Ajuste: la señal era de compra pero tu inventario '
                               'ya está cerca del máximo configurado.')
        razones.append(
            f"Posición actual: {posicion['stock']:,.0f} {code} en inventario"
            + (f" ({posicion['stock_pct_max']}% del máximo)" if posicion.get('stock_pct_max') else '')
            + extra + '.')

    if not razones:
        razones.append('Sin señales suficientes en este momento — el sistema '
                       'necesita datos frescos de mercado para opinar.')
        decision, verbo, confianza = 'ESPERAR', 'esperar', 0.3

    intro = {
        'comprar': f'Sobre comprar {code}:',
        'vender':  f'Sobre vender {code}:',
        'general': f'Mi lectura del {code} ahora mismo:',
    }[parsed['intent']]

    reply = (f"{intro} mi recomendación es **{decision}** "
             f"(confianza {confianza*100:.0f}%, score {score:+.2f}).\n\n"
             + '\n'.join(f'• {r}' for r in razones)
             + '\n\n_Esto es una lectura estadística de señales reales del '
               'sistema, no asesoría financiera definitiva._')

    return {
        'currency': code,
        'intent': parsed['intent'],
        'decision': decision,
        'score': score,
        'confidence': round(confianza, 2),
        'reply': reply,
        'signals': {
            'forecast': forecast, 'sentimiento': sent, 'brecha': brecha,
            'montecarlo': mc, 'posicion': posicion, 'ai_pricing': ai,
        },
    }
