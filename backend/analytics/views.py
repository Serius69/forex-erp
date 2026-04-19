# analytics/views.py
import logging
from decimal import Decimal, InvalidOperation

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import date, timedelta

from .services import (
    ProfitEngine, PnLService, ExposureService, SpreadService, DecisionEngine,
)
from .models import TransactionProfitLedger, PnLDailySnapshot, DecisionLog

log = logging.getLogger('analytics.decision')

# ── Decision cache TTL (seconds) — override via DECISION_CACHE_TTL in settings
_DECISION_TTL: int = getattr(settings, 'DECISION_CACHE_TTL', 45)


def _branch(request):
    """Devuelve la sucursal del usuario, o None si es ADMIN sin filtro."""
    user = request.user
    if hasattr(user, 'branch') and user.branch:
        if user.role not in ('ADMIN',) or not request.query_params.get('all_branches'):
            return user.branch
    return None


def _parse_dates(request, default_days: int = 30):
    """Parsea date_from / date_to de query params."""
    date_to   = parse_date(request.query_params.get('date_to', '')) or date.today()
    date_from = parse_date(request.query_params.get('date_from', '')) or (
        date_to - timedelta(days=default_days)
    )
    return date_from, date_to


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/pnl/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_pnl(request):
    """
    P&L histórico con serie temporal y resumen del período.

    Query params:
      date_from  (default: 30 días atrás)
      date_to    (default: hoy)
      currency   (opcional: filtrar ledger por divisa)
      all_branches (ADMIN: ver todas las sucursales)

    Response:
      {
        resumen: { ganancia_neta, margen_neto_pct, ... },
        series:  [{ fecha, ganancia_bruta_bob, ganancia_neta_bob, ... }],
        top_divisas: [{ currency_code, ganancia_bob, ops }],
      }
    """
    branch      = _branch(request)
    date_from, date_to = _parse_dates(request)
    currency    = request.query_params.get('currency')

    resumen = PnLService.resumen_periodo(branch, date_from, date_to) if branch else {}
    series  = PnLService.series_pnl(branch, date_from, date_to) if branch else []

    # Top divisas por ganancia
    ledger_qs = TransactionProfitLedger.objects.filter(
        transaction_type='SELL',
        fecha__gte=date_from,
        fecha__lte=date_to,
    )
    if branch:
        ledger_qs = ledger_qs.filter(branch=branch)
    if currency:
        ledger_qs = ledger_qs.filter(currency_code=currency)

    from django.db.models import Sum, Count
    top_divisas = list(
        ledger_qs
        .values('currency_code')
        .annotate(ganancia_bob=Sum('profit_bob'), ops=Count('id'),
                  spread_prom=Sum('spread_bob'))
        .order_by('-ganancia_bob')
    )

    # Convertir Decimals a str para JSON
    for d in top_divisas:
        for k in ('ganancia_bob', 'spread_prom'):
            if d.get(k) is not None:
                d[k] = str(d[k])

    for row in series:
        row['fecha'] = str(row['fecha'])
        for k in ('ingreso_ventas_bob', 'costo_ventas_bob', 'ganancia_bruta_bob',
                  'gastos_operativos_bob', 'ganancia_neta_bob', 'margen_neto_pct'):
            if row.get(k) is not None:
                row[k] = str(row[k])

    return Response({
        'resumen':     resumen,
        'series':      series,
        'top_divisas': top_divisas,
        'periodo':     {'desde': str(date_from), 'hasta': str(date_to)},
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/exposure/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_exposure(request):
    """
    Exposición al riesgo de mercado actual + serie histórica.

    Query params:
      currency    (opcional: serie para divisa específica, últimos `days` días)
      days        (default: 30)

    Response actual (sin ?currency):
      { divisas, total_exposure_bob, alertas, calculado_en }

    Response histórico (con ?currency=USD&days=30):
      { currency, series: [{ timestamp, exposure_bob, pct_of_capital, ... }] }
    """
    branch   = _branch(request)
    currency = request.query_params.get('currency')
    days     = int(request.query_params.get('days', 30))

    if currency and branch:
        series = ExposureService.series_exposure(currency, branch, days)
        for row in series:
            row['timestamp'] = row['timestamp'].isoformat()
            for k in ('exposure_bob', 'pct_of_capital', 'sell_rate_unit', 'unrealized_pnl_bob'):
                if row.get(k) is not None:
                    row[k] = str(row[k])
        return Response({'currency': currency, 'series': series})

    resultado = ExposureService.calcular_exposicion(branch=branch)
    return Response(resultado)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/spread/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_spread(request):
    """
    Spreads actuales de todas las divisas + serie histórica opcional.

    Query params:
      currency    (opcional: serie histórica para esta divisa)
      market_type (default: paralelo_fisico_empresa)
      days        (default: 30)
      save        (POST: guardar snapshot ahora — requiere ADMIN)
    """
    currency    = request.query_params.get('currency')
    market_type = request.query_params.get('market_type', 'paralelo_fisico_empresa')
    days        = int(request.query_params.get('days', 30))

    if currency:
        series = SpreadService.series_spread(currency, market_type, days)
        for row in series:
            row['timestamp'] = row['timestamp'].isoformat()
            for k in ('buy_rate', 'sell_rate', 'spread_bob', 'spread_pct', 'prima_oficial_pct'):
                if row.get(k) is not None:
                    row[k] = str(row[k])
        return Response({'currency': currency, 'market_type': market_type, 'series': series})

    spreads = SpreadService.calcular_spreads(branch=_branch(request))
    return Response({'spreads': spreads, 'calculado_en': timezone.now().isoformat()})


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/history/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_history(request):
    """
    Historial de ledger de ganancias por transacción.

    Query params:
      date_from, date_to, currency, transaction_type (SELL/BUY/REVERSAL)
      page, page_size
    """
    branch      = _branch(request)
    date_from, date_to = _parse_dates(request, default_days=7)
    currency    = request.query_params.get('currency')
    tx_type     = request.query_params.get('transaction_type')
    page        = int(request.query_params.get('page', 1))
    page_size   = min(int(request.query_params.get('page_size', 50)), 200)

    qs = TransactionProfitLedger.objects.filter(
        fecha__gte=date_from, fecha__lte=date_to,
    ).select_related('transaction', 'branch').order_by('-created_at')

    if branch:
        qs = qs.filter(branch=branch)
    if currency:
        qs = qs.filter(currency_code=currency)
    if tx_type:
        qs = qs.filter(transaction_type=tx_type)

    total  = qs.count()
    offset = (page - 1) * page_size
    page_qs = qs[offset: offset + page_size]

    results = []
    for l in page_qs:
        results.append({
            'id':                    l.id,
            'transaction_number':    l.transaction.transaction_number,
            'transaction_type':      l.transaction_type,
            'currency_code':         l.currency_code,
            'fecha':                 str(l.fecha),
            'amount_foreign':        str(l.amount_foreign),
            'exchange_rate':         str(l.exchange_rate),
            'amount_bob':            str(l.amount_bob),
            'wac_at_transaction':    str(l.wac_at_transaction),
            'cost_bob':              str(l.cost_bob),
            'profit_bob':            str(l.profit_bob),
            'profit_pct':            str(l.profit_pct),
            'spread_bob':            str(l.spread_bob),
            'branch':                l.branch.name,
        })

    return Response({
        'count':   total,
        'page':    page,
        'results': results,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/decision/           — motor de decisión inteligente
# GET /api/analytics/decision/history/   — historial con outcome real
# ─────────────────────────────────────────────────────────────────────────────

# ── Helpers de outcome ────────────────────────────────────────────────────────

# Horas que deben pasar antes de evaluar si la decisión fue correcta
_OUTCOME_EVAL_HOURS: int = getattr(settings, 'DECISION_OUTCOME_HOURS', 4)

# Threshold de movimiento para clasificar como "correcto"
_CORRECT_MOVE_PCT = Decimal('0.1')    # >0.1% = movimiento real
_HOLD_TOLERANCE   = Decimal('1.0')   # ±1% = "rango ESPERAR"


def _try_evaluate_outcome(entry: DecisionLog) -> None:
    """
    Intenta rellenar los campos outcome_* de un DecisionLog.
    Se llama lazily al servir el historial.
    Nunca propaga excepciones — silencia errores de datos.
    """
    if entry.outcome_evaluated_at:
        return
    if entry.decision == 'SIN_DATOS':
        return
    age_h = (timezone.now() - entry.timestamp).total_seconds() / 3600
    if age_h < _OUTCOME_EVAL_HOURS:
        return

    try:
        from rates.models import ExchangeRate
        tasa = (
            ExchangeRate.objects
            .filter(currency_from__code=entry.currency, valid_until__isnull=True)
            .select_related('currency_from')
            .first()
        )
        if not tasa:
            return

        scale   = Decimal(str(tasa.currency_from.scale_factor or 1))
        current = Decimal(str(tasa.sell_rate)) / scale

        original = Decimal(str(
            entry.input_snapshot.get('tasa_venta', 0) or 0
        ))
        if original <= 0:
            return

        delta_pct = (current - original) / original * 100

        if entry.decision == 'COMPRAR':
            correct = delta_pct > _CORRECT_MOVE_PCT
        elif entry.decision == 'VENDER':
            correct = delta_pct < -_CORRECT_MOVE_PCT
        else:  # ESPERAR
            correct = abs(delta_pct) <= _HOLD_TOLERANCE

        entry.outcome_rate         = current
        entry.outcome_delta_pct    = delta_pct.quantize(Decimal('0.0001'))
        entry.decision_was_correct = correct
        entry.outcome_evaluated_at = timezone.now()
        entry.save(update_fields=[
            'outcome_rate', 'outcome_delta_pct',
            'decision_was_correct', 'outcome_evaluated_at',
        ])
    except Exception as exc:
        log.debug('OUTCOME_EVAL_FAIL id=%s err=%s', entry.id, exc)


# ── Persistir decisión (fire-and-forget) ─────────────────────────────────────

def _persist_decision(result: dict, branch, user, from_cache: bool) -> int | None:
    """
    Inserta un DecisionLog con el resultado de evaluar().
    Retorna el id generado, o None si falló.
    No propaga excepciones.
    """
    try:
        def _d(val):
            try:
                return Decimal(str(val or 0))
            except (InvalidOperation, TypeError):
                return Decimal('0')

        datos = result.get('datos', {})
        entry = DecisionLog(
            currency      = result['currency'],
            branch        = branch,
            requested_by  = user,
            from_cache    = from_cache,
            decision      = result['decision'],
            confianza     = int(result.get('confianza', 0)),
            riesgo        = result.get('riesgo', 'N/A'),
            precio_compra = _d(result.get('precio_recomendado_compra', 0)),
            precio_venta  = _d(result.get('precio_recomendado_venta',  0)),
            motivo        = result.get('motivo', ''),
            score_total   = _d(result.get('score_total', 0)),
            input_snapshot = {
                'tasa_compra':       datos.get('tasa_compra'),
                'tasa_venta':        datos.get('tasa_venta'),
                'spread_pct':        datos.get('spread_pct'),
                'tendencia_24h_pct': datos.get('tendencia_24h_pct'),
                'tendencia_7d_pct':  datos.get('tendencia_7d_pct'),
                'volatilidad_pct':   datos.get('volatilidad_pct'),
                'stock_actual':      datos.get('stock_actual'),
                'wac':               datos.get('wac'),
                'tasa_digital':      datos.get('tasa_digital'),
                'tasa_bcb':          datos.get('tasa_bcb'),
                'tasa_competencia':  datos.get('tasa_competencia'),
                'volumen_tx_24h':    datos.get('volumen_tx_24h'),
            },
            full_result = result,
        )
        entry.save()
        return entry.id
    except Exception as exc:
        log.error('DECISION_PERSIST_FAIL currency=%s err=%s', result.get('currency'), exc, exc_info=True)
        return None


# ── Endpoint principal ────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_decision(request):
    """
    Motor de decisión inteligente.

    GET /api/analytics/decision/?currency=USD[&branch_id=1]

    Parámetros
    ----------
    currency  : (requerido) código de divisa — USD, EUR, ARS, BRL …
    branch_id : (solo ADMIN) sucursal específica; sin él usa contexto global

    Respuesta
    ---------
    {
      "currency":       "USD",
      "decision":       "COMPRAR",          // COMPRAR | VENDER | ESPERAR | SIN_DATOS
      "confianza":      87,                  // 0–100
      "precio_compra":  "6.9200",
      "precio_venta":   "6.9800",
      "riesgo":         "MEDIO",             // BAJO | MEDIO | ALTO | N/A
      "motivo":         "Tendencia alcista …",
      "score_total":    72.5,
      "scores_detalle": { tendencia, spread, competencia, binance, liquidez },
      "señales":        [...],
      "alertas":        [...],
      "datos":          { tasas, spreads, stock, tendencias, … },
      "calculado_en":   "ISO-8601",
      "cached":         false,
      "log_id":         42
    }

    Errores
    -------
    400 — currency ausente
    """
    currency = request.query_params.get('currency', '').strip().upper()
    if not currency:
        return Response(
            {'error': 'Parámetro currency requerido (e.g. ?currency=USD)'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── Branch — ADMIN puede operar sin sucursal ──────────────────────────────
    user   = request.user
    branch = None
    if user.role != 'ADMIN':
        branch = getattr(user, 'branch', None)
    else:
        branch_id = request.query_params.get('branch_id')
        if branch_id:
            from users.models import Branch
            try:
                branch = Branch.objects.get(pk=branch_id)
            except Branch.DoesNotExist:
                return Response({'error': 'Sucursal no encontrada'}, status=status.HTTP_404_NOT_FOUND)

    branch_key = branch.id if branch else 'global'
    cache_key  = f'decision:v2:{currency}:{branch_key}'

    log.info(
        'DECISION_REQUEST currency=%s branch=%s user=%s',
        currency, branch_key, user.username,
    )

    # ── Cache lookup ──────────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached:
        log.info(
            'DECISION_CACHE_HIT currency=%s branch=%s decision=%s confianza=%s',
            currency, branch_key, cached.get('decision'), cached.get('confianza'),
        )
        # Persist a lightweight log entry even for cache hits
        _persist_decision(cached, branch, user, from_cache=True)
        return Response({**cached, 'cached': True})

    # ── Evaluate ──────────────────────────────────────────────────────────────
    try:
        result = DecisionEngine.evaluar(currency, branch)
    except Exception as exc:
        log.exception('DECISION_ENGINE_FAILED currency=%s branch=%s err=%s', currency, branch_key, exc)
        return Response(
            {
                'currency':    currency,
                'decision':    'SIN_DATOS',
                'confianza':   0,
                'riesgo':      'N/A',
                'motivo':      f'Motor de decisión no disponible temporalmente: {exc}',
                'score_total': 0,
                'scores_detalle': {},
                'señales':     [],
                'alertas':     [],
                'datos':       {},
                'cached':      False,
                'log_id':      None,
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    log.info(
        'DECISION_RESULT currency=%s branch=%s decision=%s confianza=%s '
        'riesgo=%s score=%.2f motivo="%s"',
        currency, branch_key,
        result.get('decision'), result.get('confianza'),
        result.get('riesgo'),   result.get('score_total', 0),
        result.get('motivo', '')[:80],
    )
    log.debug(
        'DECISION_INPUT currency=%s branch=%s datos=%s',
        currency, branch_key, result.get('datos'),
    )

    # ── Build response aligned to spec ───────────────────────────────────────
    response_data = {
        'currency':       result['currency'],
        'decision':       result['decision'],
        'confianza':      result.get('confianza', 0),
        'precio_compra':  result.get('precio_recomendado_compra', '0'),
        'precio_venta':   result.get('precio_recomendado_venta',  '0'),
        'riesgo':         result.get('riesgo', 'N/A'),
        'motivo':         result.get('motivo', ''),
        'score_total':    result.get('score_total', 0),
        'scores_detalle': result.get('scores_detalle', {}),
        'señales':        result.get('señales', []),
        'alertas':        result.get('alertas', []),
        'datos':          result.get('datos', {}),
        'calculado_en':   result.get('calculado_en'),
    }

    # ── Cache store ───────────────────────────────────────────────────────────
    cache.set(cache_key, response_data, timeout=_DECISION_TTL)

    # ── Persist to log ────────────────────────────────────────────────────────
    log_id = _persist_decision(result, branch, user, from_cache=False)

    return Response({**response_data, 'cached': False, 'log_id': log_id})


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/evaluar/ — Motor de decisión inteligente (formato completo)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_evaluar(request):
    """
    Motor de decisión inteligente — scoring ponderado completo.

    Query params:
      currency  (requerido) — código de divisa (USD, EUR, ARS, …)

    Devuelve:
      decision, confianza, precio_recomendado_compra/venta, motivo, riesgo,
      score_total, scores_detalle {tendencia, spread, competencia, binance, liquidez},
      señales, alertas, heuristicas_aplicadas, datos, calculado_en
    """
    currency = request.query_params.get('currency')
    if not currency:
        return Response(
            {'error': 'Parámetro currency requerido'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    branch = _branch(request)
    return Response(DecisionEngine.evaluar(currency.upper(), branch))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/decision/history/ — Decisiones pasadas vs resultados reales
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_decision_history(request):
    """
    Historial de decisiones del motor con comparación vs resultado real.

    GET /api/analytics/decision/history/

    Parámetros de filtro
    --------------------
    currency        : código de divisa (USD, EUR …)
    decision        : COMPRAR | VENDER | ESPERAR | SIN_DATOS
    date_from       : YYYY-MM-DD (default: 7 días atrás)
    date_to         : YYYY-MM-DD (default: hoy)
    correct_only    : true — mostrar solo decisiones acertadas
    incorrect_only  : true — mostrar solo decisiones fallidas
    pending_outcome : true — mostrar solo sin outcome evaluado todavía
    page            : número de página (default: 1)
    page_size       : registros por página (default: 50, max: 200)

    Respuesta
    ---------
    {
      "count":          int,
      "page":           int,
      "page_size":      int,
      "accuracy_pct":   "72.50",   // % de decisiones correctas en el período
      "stats": {
        "total": int,
        "correctas": int,
        "incorrectas": int,
        "pendientes": int,
        "por_decision": { "COMPRAR": int, "VENDER": int, "ESPERAR": int },
      },
      "results": [
        {
          "id":           int,
          "timestamp":    "ISO-8601",
          "currency":     "USD",
          "decision":     "COMPRAR",
          "confianza":    87,
          "riesgo":       "MEDIO",
          "precio_compra_recomendado": "6.9200",
          "precio_venta_recomendado":  "6.9800",
          "score_total":  72.5,
          "motivo":       "...",
          "branch":       "CENTRAL" | null,
          "from_cache":   false,

          "outcome": {
            "tasa_al_decidir":   "6.9500",
            "tasa_posterior":    "6.9800",   // null si aún no evaluado
            "delta_pct":         "+0.4317",  // null si pendiente
            "decision_correcta": true,       // null si pendiente
            "evaluado_en":       "ISO-8601"  // null si pendiente
          }
        },
        ...
      ]
    }
    """
    user       = request.user
    params     = request.query_params

    # ── Filtros de fecha ──────────────────────────────────────────────────────
    date_to   = parse_date(params.get('date_to',   '')) or date.today()
    date_from = parse_date(params.get('date_from', '')) or (date_to - timedelta(days=7))

    # ── Construir queryset ────────────────────────────────────────────────────
    qs = (DecisionLog.objects
          .select_related('branch', 'requested_by')
          .filter(timestamp__date__gte=date_from, timestamp__date__lte=date_to))

    # Branch scoping
    if user.role != 'ADMIN':
        branch = getattr(user, 'branch', None)
        if branch:
            qs = qs.filter(branch=branch)
    else:
        branch_id = params.get('branch_id')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

    # Optional filters
    if currency_f := params.get('currency', '').strip().upper():
        qs = qs.filter(currency=currency_f)
    if decision_f := params.get('decision', '').strip().upper():
        qs = qs.filter(decision=decision_f)
    if params.get('correct_only') == 'true':
        qs = qs.filter(decision_was_correct=True)
    if params.get('incorrect_only') == 'true':
        qs = qs.filter(decision_was_correct=False)
    if params.get('pending_outcome') == 'true':
        qs = qs.filter(outcome_evaluated_at__isnull=True)

    # ── Pagination ────────────────────────────────────────────────────────────
    page      = max(1, int(params.get('page', 1)))
    page_size = min(int(params.get('page_size', 50)), 200)
    total     = qs.count()
    offset    = (page - 1) * page_size
    page_qs   = list(qs[offset: offset + page_size])

    # ── Lazy outcome evaluation ───────────────────────────────────────────────
    for entry in page_qs:
        _try_evaluate_outcome(entry)

    # ── Stats (on full filtered queryset, before pagination) ──────────────────
    from django.db.models import Count, Q as DQ
    agg = qs.aggregate(
        correctas   = Count('id', filter=DQ(decision_was_correct=True)),
        incorrectas = Count('id', filter=DQ(decision_was_correct=False)),
        pendientes  = Count('id', filter=DQ(outcome_evaluated_at__isnull=True)),
    )
    correctas   = agg['correctas']   or 0
    incorrectas = agg['incorrectas'] or 0
    evaluadas   = correctas + incorrectas
    accuracy    = f'{correctas / evaluadas * 100:.2f}' if evaluadas > 0 else None

    from django.db.models import Count as DCount
    por_decision = dict(
        qs.values('decision').annotate(n=DCount('id')).values_list('decision', 'n')
    )

    # ── Build results ─────────────────────────────────────────────────────────
    results = []
    for entry in page_qs:
        tasa_decidir = entry.input_snapshot.get('tasa_venta')
        results.append({
            'id':        entry.id,
            'timestamp': entry.timestamp.isoformat(),
            'currency':  entry.currency,
            'decision':  entry.decision,
            'confianza': entry.confianza,
            'riesgo':    entry.riesgo,
            'precio_compra_recomendado': str(entry.precio_compra),
            'precio_venta_recomendado':  str(entry.precio_venta),
            'score_total':               str(entry.score_total),
            'motivo':    entry.motivo,
            'branch':    entry.branch.code if entry.branch_id else None,
            'from_cache': entry.from_cache,
            'outcome': {
                'tasa_al_decidir':   tasa_decidir,
                'tasa_posterior':    str(entry.outcome_rate)    if entry.outcome_rate    is not None else None,
                'delta_pct':         str(entry.outcome_delta_pct) if entry.outcome_delta_pct is not None else None,
                'decision_correcta': entry.decision_was_correct,
                'evaluado_en':       entry.outcome_evaluated_at.isoformat() if entry.outcome_evaluated_at else None,
            },
        })

    return Response({
        'count':        total,
        'page':         page,
        'page_size':    page_size,
        'accuracy_pct': accuracy,
        'stats': {
            'total':       total,
            'correctas':   correctas,
            'incorrectas': incorrectas,
            'pendientes':  agg['pendientes'] or 0,
            'por_decision': por_decision,
        },
        'periodo': {'desde': str(date_from), 'hasta': str(date_to)},
        'results': results,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/analytics/snapshot/ — Guardar snapshots manualmente (ADMIN)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analytics_snapshot(request):
    """
    Guarda manualmente snapshots de exposición y spread.
    Solo ADMIN/SUPERVISOR.
    """
    if request.user.role not in ('ADMIN', 'SUPERVISOR'):
        return Response({'error': 'Permisos insuficientes'}, status=status.HTTP_403_FORBIDDEN)

    branch = _branch(request)
    if not branch:
        return Response({'error': 'branch requerido'}, status=status.HTTP_400_BAD_REQUEST)

    ExposureService.guardar_snapshot(branch)
    SpreadService.guardar_snapshot(branch)
    PnLService.recalcular_snapshot_hoy(branch)

    return Response({'status': 'ok', 'message': 'Snapshots guardados correctamente'})
