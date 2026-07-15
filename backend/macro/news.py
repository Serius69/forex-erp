"""
Noticias del mercado cambiario boliviano — RSS de Google News + sentimiento.

Por qué RSS y no scraping de portales: los feeds RSS son estables (XML
estándar), agregan decenas de medios a la vez y no se rompen con cada
rediseño de un sitio. Verificado accesible desde el contenedor (IPv4-only).

Sentimiento: scoring determinista por keywords en español, calibrado al
contexto boliviano. Positivo = presión ALCISTA sobre el dólar paralelo.
El índice agregado (media ponderada por recencia de las últimas 48 h) se
persiste como MacroIndicator 'sentimiento_dolar' y alimenta al Asesor.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import timedelta
from email.utils import parsedate_to_datetime

import requests

log = logging.getLogger('kapitalya.macro.news')

_UA = {'User-Agent': 'Mozilla/5.0 (compatible; KapitalyaNews/1.0)'}
_TIMEOUT = 20

# Consultas al agregador (cada una devuelve ~100 ítems de decenas de medios)
QUERIES = [
    'dolar bolivia',
    'tipo de cambio bolivia',
    'BCB reservas bolivia',
    'economia bolivia inflacion',
]

RSS_URL = ('https://news.google.com/rss/search?q={q}'
           '&hl=es-419&gl=BO&ceid=BO:es')

# ── Léxico de sentimiento (contexto: presión sobre el dólar PARALELO) ─────────
# peso > 0 → presión alcista (dólar sube); < 0 → bajista (dólar baja/estabiliza)
LEXICON = {
    # Alcistas fuertes
    'devaluaci':        +1.0,   # devaluación/devaluar
    'escasez de dolar': +1.0,
    'escasez de divisa': +1.0,
    'crisis cambiaria': +1.0,
    'corrida':          +0.9,
    'default':          +0.9,
    'sin dolares':      +0.9,
    'record del dolar': +0.8,
    'dolar se dispara': +0.8,
    'mercado negro':    +0.6,
    # Alcistas moderadas
    'escasez':          +0.5,
    'dolar sube':       +0.6,
    'sube el dolar':    +0.6,
    'alza del dolar':   +0.6,
    'inflacion':        +0.4,
    'caida de reservas': +0.7,
    'reservas caen':    +0.7,
    'deficit':          +0.4,
    'riesgo pais':      +0.4,
    'incertidumbre':    +0.3,
    'protesta':         +0.3,
    'bloqueo':          +0.3,
    'combustible':      +0.3,   # crisis de combustibles presiona divisas
    # Negaciones (más largas → matchean ANTES y consumen el texto, evitando
    # que "sin acuerdo con el FMI" puntúe como si hubiera acuerdo)
    'sin acuerdo con el fmi': +0.5,
    'no hay acuerdo con el fmi': +0.5,
    'sin desembolso':   +0.4,
    'no se estabiliza': +0.5,
    # Bajistas
    'dolar baja':       -0.6,
    'baja el dolar':    -0.6,
    'dolar retrocede':  -0.6,
    'se estabiliza':    -0.5,
    'estabilidad cambiaria': -0.5,
    'desembolso':       -0.6,   # créditos externos → más divisas
    'credito del fmi':  -0.6,
    'acuerdo con el fmi': -0.6,
    'reservas suben':   -0.7,
    'aumento de reservas': -0.7,
    'ingreso de divisas': -0.6,
    'exportaciones crecen': -0.4,
    'superavit':        -0.4,
    'inversion extranjera': -0.3,
}

_TAG_RE = re.compile(r'<[^>]+>')


def _norm(text: str) -> str:
    """minúsculas sin tildes para matchear el léxico."""
    t = (text or '').lower()
    for a, b in (('á', 'a'), ('é', 'e'), ('í', 'i'), ('ó', 'o'),
                 ('ú', 'u'), ('ñ', 'n')):
        t = t.replace(a, b)
    return t


def score_text(text: str) -> tuple[float, list[str]]:
    """
    Devuelve (sentimiento ∈ [-1,1], keywords que dispararon).

    Matching por frase MÁS LARGA primero, consumiendo el texto matcheado:
    así "sin acuerdo con el fmi" (+) no dispara además "acuerdo con el fmi" (−).
    """
    t = _norm(text)
    total, hits = 0.0, []
    for kw, w in sorted(LEXICON.items(), key=lambda kv: -len(kv[0])):
        if kw in t:
            total += w
            hits.append(kw)
            t = t.replace(kw, ' ')   # consumir para no re-matchear submatches
    # saturación suave: 1 keyword fuerte ya marca; varias no explotan la escala
    score = max(-1.0, min(1.0, total / 1.5))
    return round(score, 3), hits


def fetch_news(max_per_query: int = 50) -> dict:
    """Descarga los feeds, puntúa y persiste NewsItem nuevos (por URL)."""
    from django.utils import timezone

    from .models import NewsItem

    created, seen_urls = 0, set(
        NewsItem.objects.values_list('url', flat=True))

    for q in QUERIES:
        try:
            resp = requests.get(RSS_URL.format(q=q.replace(' ', '%20')),
                                timeout=_TIMEOUT, headers=_UA)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as exc:
            log.warning('NEWS_FETCH_FAIL q=%r err=%s', q, exc)
            continue

        for item in root.iter('item'):
            if max_per_query <= 0:
                break
            title = (item.findtext('title') or '').strip()
            url = (item.findtext('link') or '').strip()
            if not title or not url or url in seen_urls:
                continue
            source = (item.findtext('source') or '').strip()
            desc = _TAG_RE.sub(' ', item.findtext('description') or '')
            try:
                pub = parsedate_to_datetime(item.findtext('pubDate') or '')
                if timezone.is_naive(pub):
                    pub = timezone.make_aware(pub)
            except Exception:
                pub = timezone.now()

            sentiment, hits = score_text(f'{title} {desc}')
            try:
                NewsItem.objects.create(
                    title=title[:400], url=url[:600], source=source[:120],
                    published_at=pub, sentiment=sentiment,
                    keywords=hits, query=q,
                )
                seen_urls.add(url)
                created += 1
            except Exception:
                continue   # carrera por unique(url) — ignorar

    idx = update_sentiment_index()
    log.info('NEWS_FETCH done created=%d index=%s', created, idx)
    return {'created': created, 'sentiment_index': idx}


def update_sentiment_index(window_hours: int = 48):
    """
    Índice diario de sentimiento: media ponderada por recencia (半vida 24 h)
    de las noticias CON señal de las últimas `window_hours`. Persiste en
    MacroIndicator('sentimiento_dolar', hoy).
    """
    import math
    from decimal import Decimal

    from django.utils import timezone

    from .models import MacroIndicator, NewsItem

    now = timezone.now()
    items = list(
        NewsItem.objects
        .filter(published_at__gte=now - timedelta(hours=window_hours))
        .exclude(sentiment=0)
        .values_list('sentiment', 'published_at')
    )
    if not items:
        return None

    num = den = 0.0
    for s, pub in items:
        age_h = max((now - pub).total_seconds() / 3600, 0)
        w = math.pow(0.5, age_h / 24)          # media-vida 24 h
        num += s * w
        den += w
    idx = round(num / den, 4) if den else 0.0

    MacroIndicator.objects.update_or_create(
        series='sentimiento_dolar', date=now.date(),
        defaults={'value': Decimal(str(idx)), 'unit': '[-1,1]',
                  'source': f'GoogleNewsRSS:{len(items)} noticias/{window_hours}h'},
    )
    return idx
