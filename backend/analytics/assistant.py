"""
Analista — chat de inteligencia de negocio anclado en datos REALES.

Responde en lenguaje natural preguntas sobre:
  · cómo va el negocio (ventas, volumen, ganancia, capital)
  · qué divisa conviene / cuál dio más ganancia (ranking)
  · tasas de cambio actuales
  · qué pasará con una divisa (pronóstico ML + señales del Asesor)
  · comprar/vender (delega en predictions.advisor)
  · contexto macro (inflación, reservas, brecha oficial, noticias)
  · inventario / posición

Es DETERMINISTA (sin LLM): clasifica intención + entidades por léxico español y
despacha a generadores que consultan la BD. "Aprende de los datos" en el sentido
de que cada respuesta se calcula sobre los datos vivos y los modelos ML que se
reentrenan cada noche — no repite respuestas cacheadas ni inventa cifras.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from decimal import Decimal

log = logging.getLogger('kapitalya.analytics.assistant')

# Reusar la detección de divisa/intención del Asesor de divisas
from predictions.advisor import KNOWN, _ALIASES, advise, parse_message


# ── Clasificación de intención ─────────────────────────────────────────────────

_INTENT_PATTERNS = [
    ('saludo',      r'\b(hola|buenas|buenos dias|buen dia|que tal|hey|saludos)\b'),
    ('ayuda',       r'\b(ayuda|que puedes|que sabes|opciones|como funciona|que haces)\b'),
    ('compra_venta', r'\b(compr|vend|convien.*compr|convien.*vend|me deshago|acumul)\w*'),
    ('pronostico',  r'\b(pasar|pasara|futuro|ma[nñ]ana|subir|bajar|va a|proyec|pron[oó]stic|'
                    r'predic|tendencia|expectativ|que esperar)\w*'),
    ('ganancia',    r'\b(ganancia|rentab|util|margen|cual.*convien|que divisa|mejor divisa|'
                    r'mas gan|ranking|cual deja)\w*'),
    ('negocio',     r'\b(negocio|va el|c[oó]mo va|ventas|ingres|volumen|resumen|resultado|'
                    r'facturaci|movimiento|operaci|desempe|balance|c[oó]mo estuvo|como vamos)\w*'),
    ('inventario',  r'\b(inventario|stock|posici[oó]n|cu[aá]nto.*teng|cu[aá]nto.*hay|'
                    r'cu[aá]nto.*divisa|caja|efectivo|tenemos)\w*'),
    ('macro',       r'\b(econom[ií]a|inflaci|reserv|brecha|oficial|bcb|noticia|contexto|'
                    r'macro|pa[ií]s|situaci[oó]n)\w*'),
    ('tasas',       r'\b(tasa|cotiz|precio|a cu[aá]nto|cu[aá]nto est|valor|cambio)\w*'),
]


def _norm(t: str) -> str:
    t = (t or '').lower()
    for a, b in (('á', 'a'), ('é', 'e'), ('í', 'i'), ('ó', 'o'), ('ú', 'u')):
        t = t.replace(a, b)
    return t


def classify(message: str) -> str:
    t = _norm(message)
    for intent, pat in _INTENT_PATTERNS:
        if re.search(pat, t):
            return intent
    return 'desconocido'


_PERIODS = [
    ('hoy',     r'\bhoy\b',                          0),
    ('ayer',    r'\bayer\b',                         1),
    ('semana',  r'\b(semana|7 dias|ultimos dias)\b', 7),
    ('mes',     r'\b(mes|mensual|30 dias)\b',        30),
    ('anio',    r'\b(a[nñ]o|anual|gestion)\b',       365),
]


def _period(message: str, default='hoy'):
    t = _norm(message)
    for name, pat, days in _PERIODS:
        if re.search(pat, t):
            return name, days
    return default, dict((p[0], p[2]) for p in _PERIODS)[default]


def _has_currency(message: str) -> bool:
    t = _norm(message)
    return (any(re.search(rf'\b{c.lower()}\b', t) for c in KNOWN)
            or any(a in t for a in _ALIASES))


# ── Utilidades de fecha/formato ────────────────────────────────────────────────

def _bs(v) -> str:
    try:
        return f'Bs {float(v):,.0f}'.replace(',', '.')
    except Exception:
        return 'Bs 0'


def _date_range(days: int, name: str):
    from django.utils import timezone
    today = timezone.localdate()
    if name == 'hoy':
        return today, today
    if name == 'ayer':
        y = today - timedelta(days=1)
        return y, y
    if name == 'mes':
        return today.replace(day=1), today
    return today - timedelta(days=days), today


# ── Generadores por intención (todos consultan datos reales) ───────────────────

def _r_negocio(message: str) -> dict:
    from django.db.models import Count, Sum
    from transactions.models import Transaction
    from capital.models import CapitalSnapshot
    from capital.services import GananciaService

    name, days = _period(message, default='hoy')
    d_from, d_to = _date_range(days, name)

    tx = Transaction.objects.filter(created_at__date__gte=d_from,
                                    created_at__date__lte=d_to)
    agg = tx.aggregate(n=Count('id'), vol=Sum('amount_to'))
    # Ganancia por WAC real (GananciaService) — el ledger no cubre las tx
    # cargadas por bulk (Sheet), pero el cálculo por inventario sí.
    try:
        filas = GananciaService.ganancia_por_divisa(d_from, d_to)
        profit = sum(Decimal(str(f.get('ganancia_bob', 0))) for f in filas)
    except Exception:
        profit = Decimal('0')
    snap = CapitalSnapshot.objects.order_by('-fecha', '-created_at').first()

    n = agg['n'] or 0
    lbl = {'hoy': 'hoy', 'ayer': 'ayer', 'semana': 'esta semana',
           'mes': 'este mes', 'anio': 'este año'}[name]

    if n == 0:
        reply = f'{lbl.capitalize()} todavía no hay operaciones registradas.'
        if snap:
            reply += f' El capital actual es {_bs(snap.total_bob)}.'
        return {'intent': 'negocio', 'reply': reply, 'data': {'transacciones': 0}}

    partes = [
        f'**{lbl.capitalize()}** el negocio registra **{n} operaciones** '
        f'por **{_bs(agg["vol"])}** de volumen.',
        f'Ganancia estimada: **{_bs(profit)}**.',
    ]
    if snap:
        partes.append(f'Capital actual: **{_bs(snap.total_bob)}** '
                      f'(al {snap.fecha}).')
    return {
        'intent': 'negocio',
        'reply': ' '.join(partes),
        'data': {'periodo': name, 'transacciones': n,
                 'volumen_bob': float(agg['vol'] or 0), 'ganancia_bob': float(profit),
                 'capital_bob': float(snap.total_bob) if snap else None},
    }


def _r_ganancia(message: str) -> dict:
    from capital.services import GananciaService

    name, days = _period(message, default='mes')
    d_from, d_to = _date_range(days, name)
    filas = GananciaService.ganancia_por_divisa(d_from, d_to)
    filas = [f for f in filas if float(f.get('ganancia_bob', 0)) != 0]
    filas.sort(key=lambda f: -float(f['ganancia_bob']))

    if not filas:
        return {'intent': 'ganancia',
                'reply': 'Aún no hay ganancias registradas en ese período.',
                'data': {}}

    top = filas[0]
    lbl = {'hoy': 'hoy', 'ayer': 'ayer', 'semana': 'esta semana',
           'mes': 'este mes', 'anio': 'este año'}[name]
    lineas = [f"**{lbl.capitalize()}** la divisa más rentable es "
              f"**{top['divisa']}** con {_bs(top['ganancia_bob'])}."]
    ranking = []
    for f in filas[:5]:
        lineas.append(f"• {f['divisa']}: {_bs(f['ganancia_bob'])}")
        ranking.append({'divisa': f['divisa'], 'ganancia_bob': float(f['ganancia_bob'])})
    return {'intent': 'ganancia', 'reply': '\n'.join(lineas),
            'data': {'periodo': name, 'ranking': ranking}}


def _r_tasas(message: str) -> dict:
    from rates.models import ExchangeRate

    _MKT_PRIO = {'paralelo_digital': 5, 'parallel': 4, 'digital': 3,
                 'paralelo_fisico_empresa': 2, 'paralelo_fisico_competencia': 1,
                 'official': 0}
    parsed = parse_message(message)
    only = parsed['currency'] if _has_currency(message) else None

    qs = (ExchangeRate.objects.filter(currency_to__code='BOB', valid_until__isnull=True)
          .select_related('currency_from')
          .exclude(source='ESTIMADO_LOCF').exclude(source_method='INFERENCE'))
    best = {}
    for r in qs:
        code = r.currency_from.code
        if only and code != only:
            continue
        prio = _MKT_PRIO.get(r.market_type, 0) + (10 if r.is_primary else 0)
        if prio >= best.get(code, (-1, None))[0]:
            best[code] = (prio, r)

    if not best:
        return {'intent': 'tasas', 'reply': 'No tengo tasas vigentes para eso ahora.',
                'data': {}}

    # oficial USD para contexto de brecha
    oficial = (ExchangeRate.objects.filter(currency_from__code='USD',
               currency_to__code='BOB', market_type='official', valid_until__isnull=True)
               .order_by('-valid_from').first())

    lineas, data = [], {}
    orden = ['USD', 'EUR', 'BRL', 'PEN', 'CLP', 'ARS']
    for code in (orden if not only else [only]):
        if code not in best:
            continue
        r = best[code][1]
        lineas.append(f"**{code}**: compra {r.buy_rate} / venta {r.sell_rate} Bs")
        data[code] = {'compra': float(r.buy_rate), 'venta': float(r.sell_rate)}
    if only and only == 'USD' and oficial:
        mid_par = (float(best['USD'][1].buy_rate) + float(best['USD'][1].sell_rate)) / 2
        mid_of = (float(oficial.buy_rate) + float(oficial.sell_rate)) / 2
        brecha = (mid_par / mid_of - 1) * 100 if mid_of else 0
        lineas.append(f"Oficial BCB ~{mid_of:.2f} Bs · brecha paralelo **{brecha:+.1f}%**.")
    encabezado = ('Cotizaciones vigentes (mercado principal):'
                  if not only else f'Cotización de {only}:')
    return {'intent': 'tasas', 'reply': encabezado + '\n' + '\n'.join(lineas),
            'data': data}


def _r_pronostico(message: str) -> dict:
    """Qué pasará con una divisa — reusa las señales del Asesor y lo narra."""
    res = advise(message)   # advise ya compone forecast+MC+sentimiento+brecha
    code = res['currency']
    f = res['signals'].get('forecast')
    mc = res['signals'].get('montecarlo')
    sent = res['signals'].get('sentimiento')

    intro = f'Perspectiva del **{code}**:'
    lineas = [intro]
    if f:
        dir_txt = 'subir' if f['delta_pct'] >= 0 else 'bajar'
        lineas.append(f"El modelo proyecta {dir_txt} ~{abs(f['delta_pct']):.2f}% en 24h "
                      f"({f['current_rate']} → {f['predicted_rate']}, serie {f['market']}).")
    if mc:
        lineas.append(f"Simulación: {mc['prob_sube_7d']*100:.0f}% de probabilidad de "
                      f"que suba en 7 días (volatilidad anual {mc['sigma_anual_pct']}%).")
    if sent:
        lbl = 'al alza' if sent['index'] > 0.15 else 'a la baja' if sent['index'] < -0.15 else 'neutral'
        lineas.append(f"Las noticias apuntan {lbl} ({sent['index']:+.2f}).")
    lineas.append(f"En síntesis, la señal compuesta es **{res['decision']}** "
                  f"(confianza {res['confidence']*100:.0f}%).")
    if not f and not mc:
        lineas = [intro, 'Aún no tengo señales suficientes de mercado para proyectarlo.']
    return {'intent': 'pronostico', 'reply': '\n'.join(lineas),
            'data': {'decision': res['decision'], 'score': res['score'],
                     'signals': res['signals']}}


def _r_macro(message: str) -> dict:
    from macro.models import MacroIndicator, NewsItem

    def latest(s):
        row = MacroIndicator.latest(s)
        return float(row.value) if row else None

    infl = latest('inflacion_yoy')
    brecha = latest('brecha_oficial_pct')
    oficial = latest('tc_oficial_diario')
    sent = latest('sentimiento_dolar')
    reservas = latest('reservas_usd')

    lineas = ['**Contexto macro de Bolivia:**']
    if oficial is not None:
        lineas.append(f"• Dólar oficial BCB: {oficial:.2f} Bs")
    if brecha is not None:
        lineas.append(f"• Brecha oficial↔paralelo: {brecha:+.1f}%")
    if infl is not None:
        lineas.append(f"• Inflación anual: {infl:.1f}%")
    if reservas is not None:
        lineas.append(f"• Reservas internacionales: US$ {reservas/1e6:.0f}M")
    if sent is not None:
        lbl = 'alcista' if sent > 0.15 else 'bajista' if sent < -0.15 else 'neutral'
        top = NewsItem.objects.exclude(sentiment=0).order_by('-published_at').first()
        lineas.append(f"• Sentimiento de noticias: {lbl} ({sent:+.2f})"
                      + (f' — "{top.title[:80]}"' if top else ''))
    if len(lineas) == 1:
        lineas.append('Todavía no tengo indicadores macro cargados.')
    return {'intent': 'macro', 'reply': '\n'.join(lineas),
            'data': {'inflacion': infl, 'brecha': brecha, 'oficial': oficial,
                     'sentimiento': sent, 'reservas': reservas}}


def _r_inventario(message: str) -> dict:
    from django.db.models import F, Sum
    from inventory.models import CurrencyInventory

    parsed = parse_message(message)
    only = parsed['currency'] if _has_currency(message) else None

    qs = CurrencyInventory.objects.select_related('currency')
    if only:
        qs = qs.filter(currency__code=only)
    filas = (qs.values('currency__code')
             .annotate(stock=Sum(F('physical_balance') + F('digital_balance')))
             .order_by('-stock'))
    filas = [f for f in filas if (f['stock'] or 0) > 0]
    if not filas:
        return {'intent': 'inventario',
                'reply': 'No hay inventario de divisas registrado' + (f' de {only}.' if only else '.'),
                'data': {}}
    lineas = ['**Posición de inventario:**' if not only else f'Inventario de {only}:']
    data = {}
    for f in filas[:8]:
        code = f['currency__code']
        lineas.append(f"• {code}: {float(f['stock']):,.0f}".replace(',', '.'))
        data[code] = float(f['stock'])
    return {'intent': 'inventario', 'reply': '\n'.join(lineas), 'data': data}


_HELP = (
    'Soy el analista de Kapitalya. Puedo responderte sobre datos reales del negocio. '
    'Prueba a preguntarme:\n'
    '• ¿Cómo va el negocio hoy? / ¿cuánto ganamos este mes?\n'
    '• ¿Qué divisa dio más ganancia?\n'
    '• ¿A cuánto está el dólar? / ¿cómo están las tasas?\n'
    '• ¿Qué pasará con el dólar? / ¿subirá el euro?\n'
    '• ¿Cómo está la economía? / ¿la brecha? / noticias\n'
    '• ¿Cuánto USD tenemos en inventario?'
)


_DISPATCH = {
    'negocio':     _r_negocio,
    'ganancia':    _r_ganancia,
    'tasas':       _r_tasas,
    'pronostico':  _r_pronostico,
    'macro':       _r_macro,
    'inventario':  _r_inventario,
}


def answer(message: str) -> dict:
    intent = classify(message)

    if intent == 'saludo':
        return {'intent': 'saludo', 'reply': '¡Hola! ' + _HELP, 'data': {}}
    if intent in ('ayuda', 'desconocido'):
        # Si menciona una divisa sin verbo claro, asumir que pregunta por su tasa
        if intent == 'desconocido' and _has_currency(message):
            return _tagged(_r_tasas(message))
        return {'intent': 'ayuda', 'reply': _HELP, 'data': {}}
    if intent == 'compra_venta':
        res = advise(message)   # delega en el Asesor de divisas
        return {'intent': 'compra_venta', 'reply': res['reply'],
                'data': {'decision': res['decision'], 'signals': res['signals']}}

    fn = _DISPATCH.get(intent)
    return _tagged(fn(message)) if fn else {'intent': intent, 'reply': _HELP, 'data': {}}


def _tagged(res: dict) -> dict:
    res.setdefault('data', {})
    return res
