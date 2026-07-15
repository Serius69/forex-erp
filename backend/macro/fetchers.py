"""
Extractores de indicadores macro de Bolivia — SOLO fuentes reales verificadas.

Cada fetcher devuelve una lista de tuplas (series, date, value, unit, source)
y NUNCA lanza: ante error registra y devuelve []. La persistencia (upsert
idempotente) vive en `persist_points`.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

import requests

log = logging.getLogger('kapitalya.macro.fetchers')

_UA = {'User-Agent': 'Mozilla/5.0 (compatible; KapitalyaMacro/1.0)'}
_TIMEOUT = 20

# World Bank: indicador → (serie local, unidad)
WORLD_BANK_INDICATORS = {
    'FP.CPI.TOTL.ZG':   ('inflacion_yoy',       '%'),
    'FI.RES.TOTL.CD':   ('reservas_usd',        'US$'),
    'NY.GDP.MKTP.KD.ZG': ('pib_crecimiento',    '%'),
    'DT.DOD.DECT.CD':   ('deuda_externa_usd',   'US$'),
    'FR.INR.LEND':      ('tasa_interes_activa', '%'),
    'PA.NUS.FCRF':      ('tc_oficial_promedio', 'BOB/USD'),
}

WB_URL = ('https://api.worldbank.org/v2/country/BOL/indicator/{code}'
          '?format=json&per_page=100&date=2000:2030')

ER_API_URL = 'https://open.er-api.com/v6/latest/USD'


def fetch_world_bank() -> list[tuple]:
    """Series anuales del World Bank para Bolivia (histórico 2000→)."""
    points = []
    for code, (series, unit) in WORLD_BANK_INDICATORS.items():
        try:
            resp = requests.get(WB_URL.format(code=code), timeout=_TIMEOUT, headers=_UA)
            resp.raise_for_status()
            payload = resp.json()
            rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
            n = 0
            for row in rows or []:
                val, year = row.get('value'), row.get('date')
                if val is None or not year:
                    continue
                try:
                    # el dato anual se ancla al 31/12 de su año
                    points.append((series, date_cls(int(year), 12, 31),
                                   Decimal(str(val)), unit, f'WorldBank:{code}'))
                    n += 1
                except (ValueError, InvalidOperation):
                    continue
            log.info('MACRO_WB series=%s puntos=%d', series, n)
        except Exception as exc:
            log.warning('MACRO_WB_FAIL code=%s error=%s', code, exc)
    return points


def fetch_usd_internacional() -> list[tuple]:
    """USD/BOB según open.er-api.com (dato del día, agregador internacional)."""
    try:
        resp = requests.get(ER_API_URL, timeout=_TIMEOUT, headers=_UA)
        resp.raise_for_status()
        data = resp.json()
        bob = (data.get('rates') or {}).get('BOB')
        if not bob or float(bob) <= 0:
            log.warning('MACRO_ERAPI_EMPTY — sin BOB en la respuesta')
            return []
        from django.utils import timezone
        today = timezone.localdate()
        return [('usd_internacional', today, Decimal(str(bob)), 'BOB/USD', 'open.er-api.com')]
    except Exception as exc:
        log.warning('MACRO_ERAPI_FAIL error=%s', exc)
        return []


def compute_brecha_oficial() -> list[tuple]:
    """
    Brecha oficial↔paralelo % del día: (paralelo_mid / oficial_mid − 1) × 100.
    Usa las tasas USD vigentes en BD (ambas series reales del propio sistema).
    """
    try:
        from django.utils import timezone

        from rates.models import ExchangeRate

        def _mid(market_type):
            row = (ExchangeRate.objects
                   .filter(currency_from__code='USD', currency_to__code='BOB',
                           market_type=market_type, valid_until__isnull=True)
                   .order_by('-valid_from')
                   .first())
            if row is None or not row.buy_rate or not row.sell_rate:
                return None
            return (Decimal(row.buy_rate) + Decimal(row.sell_rate)) / 2

        oficial  = _mid('official')
        paralelo = _mid('paralelo_digital')
        if oficial is None or paralelo is None or oficial <= 0:
            log.info('MACRO_BRECHA_SKIP oficial=%s paralelo=%s', oficial, paralelo)
            return []

        brecha = (paralelo / oficial - 1) * 100
        today = timezone.localdate()
        return [('brecha_oficial_pct', today, brecha.quantize(Decimal('0.0001')),
                 '%', 'interna:ExchangeRate')]
    except Exception as exc:
        log.warning('MACRO_BRECHA_FAIL error=%s', exc)
        return []


def persist_points(points: list[tuple]) -> int:
    """Upsert idempotente de puntos (series, date, value, unit, source)."""
    from .models import MacroIndicator

    saved = 0
    for series, dt, value, unit, source in points:
        try:
            _, created = MacroIndicator.objects.update_or_create(
                series=series, date=dt,
                defaults={'value': value, 'unit': unit, 'source': source},
            )
            saved += 1
        except Exception as exc:
            log.error('MACRO_PERSIST_FAIL series=%s date=%s error=%s', series, dt, exc)
    return saved


# ── Histórico del TC oficial (espejo currency-api, sin API key) ───────────────
# Verificado: BOB = 6.91–6.92 durante toda la era del peg (= oficial BCB) y
# sigue el oficial post-devaluación. Fuente: CDN jsdelivr con fallback pages.dev.
CURRENCY_API_URLS = (
    'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{d}/v1/currencies/usd.min.json',
    'https://{d}.currency-api.pages.dev/v1/currencies/usd.min.json',
)


def fetch_usd_oficial_hist(start_date, end_date=None, session=None) -> list[tuple]:
    """
    Serie diaria del TC oficial USD/BOB entre start_date y end_date (incl.).
    Un request por día al CDN; errores individuales se saltan.
    """
    from datetime import timedelta as _td

    from django.utils import timezone

    sess = session or requests.Session()
    end_date = end_date or timezone.localdate()
    points, day, fails = [], start_date, 0
    while day <= end_date:
        d = day.isoformat()
        val = None
        for tpl in CURRENCY_API_URLS:
            try:
                r = sess.get(tpl.format(d=d), timeout=10, headers=_UA)
                if r.status_code == 200:
                    val = (r.json().get('usd') or {}).get('bob')
                    break
            except Exception:
                continue
        if val and float(val) > 0:
            points.append(('tc_oficial_diario', day, Decimal(str(round(float(val), 6))),
                           'BOB/USD', 'currency-api(fawazahmed0)'))
            fails = 0
        else:
            fails += 1
            if fails >= 15:      # tramo sin datos → abortar limpio
                log.warning('OFICIAL_HIST muchos fallos seguidos, corto en %s', d)
                break
        day += _td(days=1)
    log.info('OFICIAL_HIST puntos=%d (%s → %s)', len(points), start_date, end_date)
    return points


def backfill_brecha_hist() -> int:
    """
    Reconstruye la brecha oficial↔paralelo HISTÓRICA cruzando
    'tc_oficial_diario' con la serie paralela diaria de TrainingData
    (USD/BOB web). Solo días con ambos datos. Idempotente.
    """
    from predictions.models import TrainingData

    from .models import MacroIndicator

    oficial = {r.date: float(r.value)
               for r in MacroIndicator.objects.filter(series='tc_oficial_diario')}
    if not oficial:
        return 0

    # mid paralelo por día (la serie web puede ser horaria — promediar)
    from django.db.models import Avg
    from django.db.models.functions import TruncDate
    paralelo = {r['d']: float(r['avg'])
                for r in (TrainingData.objects
                          .filter(currency_pair='USD/BOB', market='web')
                          .annotate(d=TruncDate('date')).values('d')
                          .annotate(avg=Avg('rate')))}

    points = []
    for day, off in oficial.items():
        par = paralelo.get(day)
        if par and off > 0:
            brecha = (par / off - 1) * 100
            points.append(('brecha_oficial_pct', day,
                           Decimal(str(round(brecha, 4))), '%',
                           'interna:hist(paralelo/oficial)'))
    return persist_points(points)


def snapshot_oficial_diario() -> list[tuple]:
    """El oficial del día desde NUESTRA serie ExchangeRate 'official' (dolarapi→BCB)."""
    try:
        from django.utils import timezone

        from rates.models import ExchangeRate
        r = (ExchangeRate.objects
             .filter(currency_from__code='USD', currency_to__code='BOB',
                     market_type='official', valid_until__isnull=True)
             .order_by('-valid_from').first())
        if r is None:
            return []
        mid = (Decimal(r.buy_rate) + Decimal(r.sell_rate)) / 2
        return [('tc_oficial_diario', timezone.localdate(),
                 mid.quantize(Decimal('0.000001')), 'BOB/USD', 'interna:official')]
    except Exception as exc:
        log.warning('OFICIAL_SNAPSHOT_FAIL error=%s', exc)
        return []
