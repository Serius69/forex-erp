"""
Tareas Celery del módulo de predicciones.

Schedule (ver core/celery.py):
  02:00 diario  — train_all_prediction_models   (reentrenar todo)
  */4h          — refresh_ensemble_weights       (recalcular pesos dinámicos)
  horario       — cache_forecast_hourly          (pre-calentar caché Redis)
  domingo 03:00 — weekly_backtest_report         (backtesting + alertas)
  evaluación    — evaluate_predictions           (rellenar actual_rate)
"""
import logging
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone
from datetime import timedelta

from .models import PredictionModel, Prediction, TrainingData

logger = logging.getLogger(__name__)

CURRENCY_PAIRS = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'ARS/BOB', 'PEN/BOB', 'CLP/BOB']

# ── Compatibilidad con imports existentes en views.py ─────────────────────────
# views.py importa estas dos funciones directamente


@shared_task(name='predictions.train_prediction_models')
def train_prediction_models():
    """Tarea legacy — delega al nuevo engine + mantiene Prophet/LSTM del servicio original."""
    return train_all_prediction_models.apply().get()


@shared_task(name='predictions.generate_predictions')
def generate_predictions():
    """Tarea legacy — delega al engine para cache pre-calentado."""
    return cache_forecast_hourly.apply().get()


# ── Tarea 1: Reentrenamiento diario completo ──────────────────────────────────

@shared_task(
    name='predictions.train_pair_prediction_models',
    bind=True,
    max_retries=1,
    # OJO acks_late=False A PROPÓSITO: esta tarea es PESADA (3 mercados × 3
    # modelos, BiLSTM incluido). Con acks_late el hard time_limit mata el worker
    # (SIGKILL, no atrapa SoftTimeLimitExceeded) y el mensaje se RE-ENTREGA →
    # loop infinito de muerte (bug real 2026-07-16: una misma tarea llevaba 8h
    # reciclándose cada 70 min). Ackear al recibir evita el poison-loop: si un
    # par excede su límite muere solo, y el reentreno diario lo recupera mañana.
    acks_late=False,
    soft_time_limit=1500,   # 25 min por PAR (antes 60 min para los 6 → timeout)
    time_limit=1800,        # 30 min hard
)
def train_pair_prediction_models(self, pair):
    """
    Reentrena UN par (las 3 series web/competencia/empresa × xgboost/arima/bilstm).
    Sub-tarea de train_all_prediction_models — acotada para no exceder límites.
    """
    logger.info("TASK_START name=train_pair_prediction_models pair=%s", pair)
    from predictions.ml_engine import ForexMLEngine
    engine = ForexMLEngine()

    # 1. Sincronizar datos ExchangeRate → TrainingData (las 3 series)
    try:
        update_training_data(pair)
    except Exception as exc:
        logger.warning("sync_data_failed pair=%s: %s", pair, exc)

    results = {}
    # 2. Entrenar las 3 series por separado; series sin datos degradan limpio.
    for market in MARKET_SOURCE_MAP:  # 'web', 'competencia', 'empresa'
        try:
            extended = engine.train_all(
                pair, include=['xgboost', 'arima', 'bilstm'], market=market)
            results[market] = {'new_models': extended}
        except SoftTimeLimitExceeded:
            logger.error("TASK_TIMEOUT train_pair pair=%s market=%s", pair, market)
            results[market] = {'new_models': {'error': 'timeout'}}
            break  # se acabó el tiempo del par; corta sin reciclar el mensaje
        except Exception as exc:
            logger.warning("train_extended pair=%s market=%s: %s", pair, market, exc)
            results[market] = {'new_models': {'error': str(exc)}}
    # Prophet: cadencia SEMANAL (weekly_hyperparameter_tuning), no aquí.

    ok = 'error' not in str(results).lower()
    logger.info("TASK_DONE name=train_pair_prediction_models pair=%s ok=%s", pair, ok)
    return {'status': 'ok' if ok else 'partial', 'pair': pair, 'results': results}


@shared_task(
    name='predictions.train_all_prediction_models',
    bind=True,
    acks_late=False,
    soft_time_limit=120,
    time_limit=180,
)
def train_all_prediction_models(self):
    """
    Diaria 02:00 — Orquesta el reentrenamiento haciendo FAN-OUT por par.

    Antes entrenaba los 6 pares en un solo task (54 entrenamientos secuenciales)
    que excedía el hard time_limit y, con acks_late, reciclaba el mensaje en un
    loop de muerte. Ahora despacha una sub-tarea acotada por par: cada una cabe
    holgada en su límite y un par lento no tumba al resto.
    """
    logger.info("TASK_START name=train_all_prediction_models (fan-out %d pares)",
                len(CURRENCY_PAIRS))
    dispatched = []
    for pair in CURRENCY_PAIRS:
        r = train_pair_prediction_models.delay(pair)
        dispatched.append({'pair': pair, 'task_id': r.id})
    logger.info("TASK_SUCCESS name=train_all_prediction_models dispatched=%d",
                len(dispatched))
    return {'status': 'dispatched', 'pairs': dispatched}


# ── Tarea 2: Recalcular pesos del ensemble cada 4 horas ───────────────────────

@shared_task(
    name='predictions.refresh_ensemble_weights',
    bind=True,
    max_retries=1,
    acks_late=True,
    soft_time_limit=120,
    time_limit=180,
)
def refresh_ensemble_weights(self):
    """
    Cada 4 horas — recalcula pesos basados en MAPE reciente e invalida caché.
    """
    logger.info("TASK_START name=refresh_ensemble_weights")
    try:
        from predictions.ml_engine import ForexMLEngine
        engine  = ForexMLEngine()
        results = {}
        for pair in CURRENCY_PAIRS:
            for market in MARKET_SOURCE_MAP:  # web / competencia / empresa
                key = f'{pair}[{market}]'
                try:
                    results[key] = engine.refresh_ensemble_weights(pair, market=market)
                except Exception as exc:
                    logger.warning("weights_refresh_failed pair=%s market=%s: %s", pair, market, exc)
                    results[key] = {'error': str(exc)}

        logger.info("TASK_SUCCESS name=refresh_ensemble_weights")
        return {'status': 'ok', 'weights': results}

    except Exception as exc:
        logger.error("TASK_FAILURE name=refresh_ensemble_weights error=%s", exc)
        return {'status': 'error', 'error': str(exc)}


# ── Tarea 3: Caché horario — pre-calcular y guardar en Redis ─────────────────

@shared_task(
    name='predictions.cache_forecast_hourly',
    bind=True,
    max_retries=2,
    acks_late=True,
    soft_time_limit=300,
    time_limit=360,
)
def cache_forecast_hourly(self):
    """
    Cada hora — genera pronósticos para todos los horizontes y pares, guarda en Redis.
    Garantiza latencia < 200ms en la API al servir desde caché.
    """
    logger.info("TASK_START name=cache_forecast_hourly")
    try:
        from predictions.ml_engine import ForexMLEngine
        engine = ForexMLEngine()
        cached = 0

        for pair in CURRENCY_PAIRS:
            for market in MARKET_SOURCE_MAP:  # web / competencia / empresa
                try:
                    engine.cache_all_horizons(pair, market=market)
                    cached += 1
                    # También guardar predicciones en BD para historial
                    _persist_ensemble_predictions(engine, pair, market)
                except Exception as exc:
                    logger.warning("cache_hourly_failed pair=%s market=%s: %s", pair, market, exc)

        logger.info("TASK_SUCCESS name=cache_forecast_hourly cached=%d", cached)
        return {'status': 'ok', 'cached_pairs': cached}

    except SoftTimeLimitExceeded:
        logger.error("TASK_TIMEOUT name=cache_forecast_hourly")
        raise


def _persist_ensemble_predictions(engine, pair: str, market: str = 'web'):
    """Guarda las predicciones de las próximas 24h en la BD (para auditoría).

    A2: además del ENSEMBLE, persiste UNA fila por cada modelo base
    (XGBOOST/ARIMA/BILSTM/PROPHET) con su ``model_type`` real, tomando el rate
    individual desde ``components``. Antes solo se guardaba el ENSEMBLE, así que
    ``evaluate_predictions`` nunca rellenaba ``actual_rate`` de los modelos base
    → ``EnsembleForecaster.compute_weights`` caía siempre al ``_fallback_weight``
    (pesos "dinámicos" inertes) y ``train_meta_learner`` no encontraba filas por
    ``model_type``. Las tasas buy/sell y los CIs de las filas base son derivados
    (rows de auditoría); lo que importa aguas abajo es ``predicted_rate`` vs
    ``actual_rate``.
    """
    try:
        from decimal import Decimal
        from predictions.models import PredictionModel, Prediction
        from rates.models import RateConfiguration

        pm = PredictionModel.objects.filter(
            model_type='ENSEMBLE', currency_pair=pair, market=market, is_active=True
        ).first()
        if not pm:
            return

        result  = engine.predict(pair, horizon_key='24h', use_cache=True, market=market)
        preds   = result.get('predictions', [])
        records = []
        rate_config = RateConfiguration.objects.filter(
            currency_from__code=pair.split('/')[0],
            currency_to__code=pair.split('/')[1],
            is_active=True,
        ).first()
        margin = Decimal('0.3')
        if rate_config:
            margin = rate_config.buy_margin_morning  # simplificado

        # Modelos base activos de ESTA serie, indexados por model_type.
        base_pms = {
            m.model_type: m
            for m in PredictionModel.objects.filter(
                model_type__in=['XGBOOST', 'ARIMA', 'BILSTM', 'PROPHET'],
                currency_pair=pair, market=market, is_active=True,
            )
        }

        for p in preds:
            rate = Decimal(str(p['rate']))
            buy  = rate * (Decimal('1') - margin / Decimal('100'))
            sell = rate * (Decimal('1') + margin / Decimal('100'))

            records.append(Prediction(
                model=pm,
                currency_pair=pair,
                prediction_date=p['datetime'],
                predicted_rate=rate,
                predicted_buy_rate=buy,
                predicted_sell_rate=sell,
                confidence_lower=Decimal(str(p['lower'])),
                confidence_upper=Decimal(str(p['upper'])),
                confidence_score=0.95,
                external_factors=p.get('components', {}),
            ))

            # Una fila por modelo base con su rate individual (de components).
            for mt, base_rate in (p.get('components') or {}).items():
                base_pm = base_pms.get(mt)
                if base_pm is None or base_rate is None:
                    continue
                brate = Decimal(str(base_rate))
                records.append(Prediction(
                    model=base_pm,
                    currency_pair=pair,
                    prediction_date=p['datetime'],
                    predicted_rate=brate,
                    predicted_buy_rate=brate * (Decimal('1') - margin / Decimal('100')),
                    predicted_sell_rate=brate * (Decimal('1') + margin / Decimal('100')),
                    confidence_lower=brate * Decimal('0.995'),
                    confidence_upper=brate * Decimal('1.005'),
                    confidence_score=0.90,
                    external_factors={'model': mt, 'persisted_as_base': True},
                ))

        Prediction.objects.bulk_create(records, batch_size=500, ignore_conflicts=True)
    except Exception as exc:
        logger.warning("persist_ensemble_failed pair=%s: %s", pair, exc)


# ── Tarea 4: Backtesting semanal ──────────────────────────────────────────────

@shared_task(
    name='predictions.weekly_backtest_report',
    bind=True,
    max_retries=1,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def weekly_backtest_report(self):
    """
    Domingos 03:00 — backtesting completo de 30 días.
    Alerta si MAPE supera umbrales configurados.
    """
    logger.info("TASK_START name=weekly_backtest_report")
    try:
        from predictions.ml_engine import ForexMLEngine
        engine  = ForexMLEngine()
        reports = {}

        for pair in CURRENCY_PAIRS:
            try:
                report = engine.run_weekly_backtest(pair)
                reports[pair] = report
                logger.info(
                    "backtest pair=%s mape=%.4f%% alerts=%d",
                    pair,
                    report['metrics'].get('mape_avg', 0),
                    len(report.get('alerts', [])),
                )
            except Exception as exc:
                logger.warning("backtest_failed pair=%s: %s", pair, exc)
                reports[pair] = {'error': str(exc)}

            # Meta-learner Ridge del ensemble (stacking): requiere historial de
            # predicciones con actual_rate. Antes NUNCA se entrenaba (código
            # muerto) y predict_with_meta caía siempre al promedio ponderado.
            try:
                import os
                from django.conf import settings
                from predictions.ensemble_forecaster import EnsembleForecaster
                from predictions.market_keys import VALID_MARKETS
                # A1: EnsembleForecaster.__init__ EXIGE models_path posicional; sin
                # él lanzaba TypeError (atrapado por el except) cada semana → el
                # .pkl del Ridge nunca se creaba. Se usa la MISMA ruta que
                # ml_engine/ml_service (MEDIA_ROOT/ml_models) para hallar/guardar
                # los artefactos meta_ridge_*.pkl junto al resto de modelos.
                models_path = os.path.join(settings.MEDIA_ROOT, 'ml_models')
                ens = EnsembleForecaster(models_path)
                meta = {}
                for market in VALID_MARKETS:
                    try:
                        meta[market] = ens.train_meta_learner(pair, market=market)
                    except ValueError:
                        meta[market] = 'sin datos suficientes'
                reports.setdefault(pair, {})
                if isinstance(reports[pair], dict):
                    reports[pair]['meta_learner'] = meta
                logger.info("meta_learner pair=%s %s", pair, meta)
            except Exception as exc:
                logger.warning("meta_learner_failed pair=%s: %s", pair, exc)

        logger.info("TASK_SUCCESS name=weekly_backtest_report")
        return {'status': 'ok', 'reports': reports}

    except Exception as exc:
        logger.error("TASK_FAILURE name=weekly_backtest_report error=%s", exc)
        return {'status': 'error', 'error': str(exc)}


# ── Tarea 5: Evaluar predicciones pasadas ─────────────────────────────────────

@shared_task(name='predictions.evaluate_predictions')
def evaluate_predictions():
    """
    Rellena actual_rate en TODAS las predicciones vencidas y recalcula
    error_percentage.

    Bug histórico: solo miraba predicciones CREADAS en una ventana de 2 h
    exactamente 24 h atrás — cualquier predicción más vieja (o si la tarea no
    corría ese día, que era siempre porque el beat estaba roto) quedaba sin
    actual_rate PARA SIEMPRE → la calibración conformal de los intervalos
    nunca se activaba. Ahora: toda vencida de los últimos 90 días, en lotes,
    comparando contra el mercado de SU propio modelo.
    """
    from decimal import Decimal
    from rates.models import ExchangeRate

    now = timezone.now()
    predictions = (Prediction.objects
                   .filter(actual_rate__isnull=True,
                           prediction_date__lt=now,
                           prediction_date__gte=now - timedelta(days=90))
                   .select_related('model')
                   .order_by('prediction_date')[:5000])
    to_update = []
    for prediction in predictions:
        currency_from, currency_to = prediction.currency_pair.split('/')
        market = getattr(prediction.model, 'market', 'web') or 'web'
        market_types = MARKET_SOURCE_MAP.get(market, MARKET_SOURCE_MAP['web'])
        base = ExchangeRate.objects.filter(
            currency_from__code=currency_from,
            currency_to__code=currency_to,
            market_type__in=market_types,
        )
        # 1) tasa cuyo intervalo cubre el instante predicho; 2) fallback: la
        #    última observada antes del instante (series con huecos)
        actual = (base.filter(valid_from__lte=prediction.prediction_date,
                              valid_until__gte=prediction.prediction_date).first()
                  or base.filter(valid_from__lte=prediction.prediction_date)
                         .order_by('-valid_from').first())
        if actual:
            # Usar tasa paralela (mid) como referencia real — BCB ya no es fuente activa
            prediction.actual_rate = (actual.buy_rate + actual.sell_rate) / 2
            # Recalcular error_percentage en memoria (equivalente a
            # Prediction.calculate_error, pero sin save() por fila — se persiste
            # todo en un único bulk_update al final para evitar el N+1 de escritura).
            if (prediction.actual_rate and prediction.predicted_rate
                    and prediction.actual_rate != 0):
                actual_dec    = Decimal(str(prediction.actual_rate))
                predicted_dec = Decimal(str(prediction.predicted_rate))
                error_pct = (abs(actual_dec - predicted_dec) / actual_dec * Decimal('100'))
                prediction.error_percentage = float(error_pct.quantize(Decimal('0.0001')))
            to_update.append(prediction)

    if to_update:
        Prediction.objects.bulk_update(to_update, ['actual_rate', 'error_percentage'])

    _update_model_metrics()
    evaluated = len(to_update)
    logger.info("evaluate_predictions evaluated=%d", evaluated)
    return {'predictions_evaluated': evaluated}


# ── Tarea 6: Sincronizar datos de entrenamiento ───────────────────────────────

# Cada serie de pronóstico ('market' de TrainingData) se alimenta de uno o más
# market_type de ExchangeRate. Se pronostican por separado (web vs competencia vs
# la tasa efectiva de la propia empresa).
MARKET_SOURCE_MAP = {
    'web':         ('paralelo_digital', 'parallel', 'digital'),
    'competencia': ('paralelo_fisico_competencia',),
    'empresa':     ('paralelo_fisico_empresa',),
}


@shared_task(name='predictions.update_training_data')
def update_training_data(currency_pair: str, market: str = None):
    """Sincroniza ExchangeRate → TrainingData (upsert) por serie de mercado.

    Con `market=None` (por defecto) sincroniza las TRES series
    (web / competencia / empresa); con un market concreto, solo esa.
    """
    import statistics
    from bisect import bisect_right
    from datetime import datetime
    from decimal import Decimal
    from django.db.models import Avg
    from django.db.models.functions import TruncDate, TruncHour
    from rates.models import ExchangeRate

    currency_from, currency_to = currency_pair.split('/')
    markets = [market] if market else list(MARKET_SOURCE_MAP.keys())
    q4 = Decimal('0.0001')
    q2 = Decimal('0.01')

    # ── Series macro reales (as-of por fecha) ────────────────────────────────
    # Antes estas columnas quedaban SIEMPRE NULL y los modelos entrenaban con
    # macro=0 constante. Ahora se rellenan desde macro.MacroIndicator con el
    # último valor conocido a cada fecha (sin mirar el futuro).
    macro_lookup = {}   # col -> (fechas_ordenadas, valores)
    try:
        from macro.models import MacroIndicator
        _MACRO_COLS = {
            'usd_internacional':   'international_rate',
            'tasa_interes_activa': 'interest_rate',
            'inflacion_yoy':       'inflation_rate',
        }
        for series, col in _MACRO_COLS.items():
            pts = list(MacroIndicator.objects.filter(series=series)
                       .order_by('date').values_list('date', 'value'))
            if pts:
                macro_lookup[col] = ([p[0] for p in pts], [p[1] for p in pts])
    except Exception as exc:   # app macro ausente/aún sin migrar → degradar limpio
        logger.warning("update_training_data macro_unavailable: %s", exc)

    def _macro_asof(col, day):
        dates, values = macro_lookup.get(col, ((), ()))
        i = bisect_right(dates, day) - 1
        return values[i] if i >= 0 else None

    total_updated = 0
    per_market = {}
    for mkt in markets:
        market_types = MARKET_SOURCE_MAP[mkt]
        # Granularidad por serie:
        #   · web → HORARIA (TruncHour): el fx_engine produce tasas intradía
        #     REALES cada pocos minutos; colapsarlas a 1 punto/día desechaba
        #     esa señal y las features horarias del pipeline eran artefactos
        #     de forward-fill. La historia vieja (1 cierre/día del CSV) queda
        #     idéntica: TruncHour de un punto diario = ese mismo punto.
        #   · competencia/empresa → DIARIA: son series de cierre diario.
        # Solo OBSERVACIONES reales: los rellenos sintéticos (ESTIMADO_LOCF —
        # colas planas que marchan el último dato durante meses — y las
        # estimaciones INFERENCE) NO entrenan modelos.
        trunc = TruncHour('valid_from') if mkt == 'web' else TruncDate('valid_from')
        daily = (ExchangeRate.objects
                 .filter(currency_from__code=currency_from,
                         currency_to__code=currency_to,
                         market_type__in=market_types)
                 .exclude(source='ESTIMADO_LOCF')
                 .exclude(source_method='INFERENCE')
                 .annotate(day=trunc)
                 .values('day')
                 .annotate(avg_buy=Avg('buy_rate'), avg_sell=Avg('sell_rate'))
                 .order_by('day'))

        updated = 0
        window = []   # últimos 30 mids (float) para ma_7/ma_30/volatility causales
        for row in daily:
            day = row['day']
            if day is None or row['avg_buy'] is None or row['avg_sell'] is None:
                continue
            mid_rate = ((row['avg_buy'] + row['avg_sell']) / 2).quantize(q4)

            # Técnicos causales (solo pasado — sin mirar el futuro)
            window.append(float(mid_rate))
            if len(window) > 30:
                window.pop(0)
            ma_7  = Decimal(str(statistics.fmean(window[-7:]))).quantize(q4)
            ma_30 = Decimal(str(statistics.fmean(window))).quantize(q4)
            vol   = round(statistics.pstdev(window), 6) if len(window) >= 5 else None

            # TruncHour devuelve datetime (preservar la hora); TruncDate, date.
            if isinstance(day, datetime):
                dt = day if timezone.is_aware(day) else timezone.make_aware(day)
                day_date = day.date()
            else:
                dt = timezone.make_aware(datetime(day.year, day.month, day.day))
                day_date = day

            defaults = {
                'rate': mid_rate, 'source': mkt,
                'ma_7': ma_7, 'ma_30': ma_30, 'volatility': vol,
            }
            # Precisión según el campo destino: (10,4) vs (5,2)
            _MACRO_QUANT = {'international_rate': q4,
                            'interest_rate': q2, 'inflation_rate': q2}
            for col, quant in _MACRO_QUANT.items():
                val = _macro_asof(col, day_date)
                if val is not None:
                    defaults[col] = Decimal(str(val)).quantize(quant)

            _, created = TrainingData.objects.update_or_create(
                currency_pair=currency_pair,
                market=mkt,
                date=dt,
                defaults=defaults,
            )
            if created:
                updated += 1
        per_market[mkt] = updated
        total_updated += updated

    logger.info("update_training_data pair=%s updated=%d detail=%s",
                currency_pair, total_updated, per_market)
    return {'pair': currency_pair, 'updated': total_updated, 'per_market': per_market}


# ── Tarea 7: Tuning semanal de hiperparámetros ────────────────────────────────

@shared_task(
    name='predictions.weekly_hyperparameter_tuning',
    bind=True,
    max_retries=0,
    acks_late=True,
    soft_time_limit=7200,   # 2h — tuning es costoso
    time_limit=7800,
)
def weekly_hyperparameter_tuning(self):
    """Sábados 04:00 — optimización bayesiana de XGBoost y Prophet con Optuna."""
    logger.info("TASK_START name=weekly_hyperparameter_tuning")
    try:
        from django.conf import settings
        from predictions.hyperparameter_tuning import run_weekly_tuning
        import os
        models_path = os.path.join(settings.MEDIA_ROOT, 'ml_models')
        results     = run_weekly_tuning(CURRENCY_PAIRS, models_path, n_trials=40)

        # Prophet: reentrenamiento SEMANAL (movido desde el diario — con MAPE
        # ~20% el ensemble lo subpondera a ~0.01; diario era CPU desperdiciada).
        prophet_results = {}
        try:
            from predictions.ml_service import ForexPredictionService
            svc = ForexPredictionService()
            for pair in CURRENCY_PAIRS:
                try:
                    _, pm = svc.train_prophet_model(pair, market='web')
                    prophet_results[pair] = pm
                except Exception as exc:
                    prophet_results[pair] = {'error': str(exc)}
        except Exception as exc:
            logger.warning("prophet_weekly_failed: %s", exc)
        results['prophet_weekly'] = prophet_results

        logger.info("TASK_SUCCESS name=weekly_hyperparameter_tuning")
        return {'status': 'ok', 'results': results}
    except SoftTimeLimitExceeded:
        logger.error("TASK_TIMEOUT name=weekly_hyperparameter_tuning")
        return {'status': 'timeout'}
    except Exception as exc:
        logger.error("TASK_FAILURE name=weekly_hyperparameter_tuning error=%s", exc)
        return {'status': 'error', 'error': str(exc)}


# ── Tarea manual: entrenamiento inicial ───────────────────────────────────────

@shared_task(name='predictions.train_initial_models')
def train_initial_models():
    """
    Entrena modelos solo si hay >= 100 snapshots por par.
    Ejecutar manualmente:
      python manage.py shell -c "from predictions.tasks import train_initial_models; train_initial_models()"
    """
    results = {}
    for pair in CURRENCY_PAIRS:
        count = TrainingData.objects.filter(currency_pair=pair).count()
        if count < 100:
            logger.info('train_initial_models skip pair=%s count=%d < 100', pair, count)
            results[pair] = {'skipped': True, 'reason': f'solo {count} snapshots (min 100)'}
            continue
        try:
            from predictions.ml_service import ForexPredictionService
            svc = ForexPredictionService()
            _, metrics = svc.train_prophet_model(pair)
            results[pair] = {'trained': True, 'metrics': metrics}
            logger.info('train_initial_models pair=%s ok mape=%.4f', pair, metrics.get('mape', 0))
        except Exception as exc:
            logger.error('train_initial_models pair=%s error=%s', pair, exc)
            results[pair] = {'trained': False, 'error': str(exc)}
    return results


# ── Helpers ────────────────────────────────────────────────────────────────────

def _update_model_metrics():
    """Actualiza recent_mape en cada PredictionModel activo."""
    from django.db.models import Avg, Count, F, ExpressionWrapper, FloatField
    from django.db.models.functions import Abs

    # MAPE = promedio de |actual - predicted| / actual * 100. Se calcula con un
    # aggregate(Avg(...)) en la base de datos en vez de iterar en Python (evita
    # traer todas las filas). Se excluyen actual/predicted en 0 igual que el guard
    # original de la comprensión de lista.
    mape_expr = ExpressionWrapper(
        Abs(F('actual_rate') - F('predicted_rate')) / F('actual_rate') * 100,
        output_field=FloatField(),
    )
    for model in PredictionModel.objects.filter(is_active=True):
        recent = (
            Prediction.objects
            .filter(
                model=model,
                actual_rate__isnull=False,
                created_at__gte=timezone.now() - timedelta(days=30),
            )
            .exclude(actual_rate=0)
            .exclude(predicted_rate=0)
        )
        agg = recent.aggregate(mape=Avg(mape_expr), n=Count('id'))
        if not agg['n']:
            continue
        model.metrics['recent_mape']        = round(agg['mape'], 4)
        model.metrics['recent_predictions'] = agg['n']
        model.metrics['last_evaluation']    = timezone.now().isoformat()
        model.save(update_fields=['metrics'])
