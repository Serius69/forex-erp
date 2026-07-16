import statistics
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Avg, Min, Max, Sum, Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta
from .models import PredictionModel, Prediction
from .serializers import PredictionModelSerializer, PredictionSerializer
from .tasks import train_prediction_models, generate_predictions

VALID_HORIZONS = {'1h', '4h', '24h', '7d'}

_HORIZON_HOURS = {'1h': 1, '4h': 4, '24h': 24, '7d': 168}


def _forecast_fallback(currency_pair: str, horizon: str) -> dict | None:
    """
    Builds a flat-rate inference forecast using the current parallel market rate.
    Used when no trained ML model exists for the pair.
    """
    pair_norm = currency_pair.replace('-', '/')
    parts = pair_norm.split('/')
    if len(parts) != 2:
        return None
    from_code, to_code = parts
    try:
        from rates.models import ExchangeRate
        rate = (
            ExchangeRate.objects
            .filter(
                currency_from__code=from_code,
                currency_to__code=to_code,
                valid_until__isnull=True,
            )
            .order_by('-confidence', '-valid_from')
            .first()
        )
        if not rate:
            return None

        mid = float((rate.buy_rate + rate.sell_rate) / 2)
        horizon_h = _HORIZON_HOURS.get(horizon, 24)
        now = timezone.now()
        step = max(1, horizon_h // 24) if horizon_h > 24 else 1
        points = min(horizon_h, 48)

        predictions = [
            {
                'datetime': (now + timedelta(hours=(i + 1) * step)).isoformat(),
                'rate':  mid,
                'lower': round(mid * 0.98, 4),
                'upper': round(mid * 1.02, 4),
            }
            for i in range(points)
        ]

        return {
            'currency_pair':       pair_norm,
            'horizon':             horizon,
            'horizon_hours':       horizon_h,
            'predicted_rate':      mid,
            'confidence_interval': {'lower': round(mid * 0.97, 4), 'upper': round(mid * 1.03, 4), 'level': 0.80},
            'model_weights':       {'inference': 1.0},
            'backtesting_metrics': None,
            'data_freshness':      'INFERENCE',
            'predictions':         predictions,
            'generated_at':        now.isoformat(),
            'is_inference':        True,
        }
    except Exception:
        return None

class PredictionModelViewSet(viewsets.ModelViewSet):
    queryset = PredictionModel.objects.all()
    serializer_class = PredictionModelSerializer
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['POST'], url_path='train-all')
    def train_all(self, request):
        """Entrena todos los modelos"""
        if request.user.role != 'ADMIN':
            return Response(
                {'error': 'Solo administradores pueden entrenar modelos'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Ejecutar tarea asíncrona
        task = train_prediction_models.delay()
        
        return Response({
            'task_id': task.id,
            'status': 'Training started'
        })
    
    @action(detail=True, methods=['POST'])
    def activate(self, request, pk=None):
        """Activa/desactiva un modelo"""
        model = self.get_object()
        model.is_active = request.data.get('is_active', True)
        model.save()
        
        return Response({'success': True})
    
    @action(detail=False, methods=['GET'], url_path='performance')
    def performance(self, request):
        """Obtiene métricas de rendimiento de todos los modelos"""
        models = self.get_queryset()
        
        performance_data = []
        
        for model in models:
            recent_predictions = Prediction.objects.filter(
                model=model,
                actual_rate__isnull=False,
                created_at__gte=timezone.now() - timedelta(days=7)
            )
            
            if recent_predictions.exists():
                agg = recent_predictions.aggregate(
                    avg_error=Avg('error_percentage'),
                    min_error=Min('error_percentage'),
                    max_error=Max('error_percentage'),
                )
                performance_data.append({
                    'model':             model.name,
                    'type':              model.model_type,
                    'currency_pair':     model.currency_pair,
                    'average_error':     round(agg['avg_error'] or 0, 4),
                    'min_error':         round(agg['min_error'] or 0, 4),
                    'max_error':         round(agg['max_error'] or 0, 4),
                    'predictions_count': recent_predictions.count(),
                    'metrics':           model.metrics,
                })
        
        return Response(performance_data)

class PredictionViewSet(viewsets.ModelViewSet):
    queryset = Prediction.objects.all()
    serializer_class = PredictionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros
        currency_pair = self.request.query_params.get('currency_pair')
        model_type = self.request.query_params.get('model_type')
        date_from = self.request.query_params.get('date_from')
        
        if currency_pair:
            queryset = queryset.filter(currency_pair=currency_pair)
        if model_type:
            queryset = queryset.filter(model__model_type=model_type)
        if date_from:
            queryset = queryset.filter(prediction_date__gte=date_from)
        
        return queryset.select_related('model').order_by('prediction_date')
    
    @action(detail=False, methods=['GET'], url_path='current')
    def current(self, request):
        """Obtiene predicciones actuales (próximas 24 horas)"""
        currency_pair = request.query_params.get('currency_pair', 'USD/BOB')
        
        # Obtener predicciones más recientes
        predictions = self.get_queryset().filter(
            currency_pair=currency_pair,
            prediction_date__gte=timezone.now(),
            prediction_date__lte=timezone.now() + timedelta(hours=24)
        ).order_by('prediction_date')
        
        # Arranque en frío (sin predicciones cacheadas en BD): NO computar el
        # forecast síncronamente aquí — el build de features (3 años) + inferencia
        # de 4 modelos bloquea el worker gunicorn varios segundos y agota el pool
        # bajo carga. Se encola el pre-warm en background (con debounce por cache)
        # y se devuelve el fallback naive de inmediato. La tarea horaria
        # normalmente ya dejó las predicciones reales en BD, así que este camino
        # solo se toma tras un deploy / flush de caché.
        if not predictions.exists():
            from django.core.cache import cache as _cache
            from .ml_service import ForexPredictionService
            if not _cache.get('forecast_prewarm_enqueued'):
                try:
                    from .tasks import cache_forecast_hourly
                    cache_forecast_hourly.delay()
                    _cache.set('forecast_prewarm_enqueued', 1, 120)  # debounce 2 min
                except Exception as exc:
                    import logging as _log
                    _log.getLogger('predictions').warning(
                        'forecast prewarm enqueue failed for %s: %s', currency_pair, exc
                    )
            service = ForexPredictionService()
            naive = service._predict_naive_fallback(24, currency_pair)
            return Response({
                'currency_pair': currency_pair,
                'model_status':  'FALLBACK',
                'data_freshness': 'INFERENCE',
                'predictions': {
                    'NAIVE_FALLBACK': [
                        {
                            'date':             p['prediction_date'],
                            'rate':             str(round(p['rate'], 4)),
                            'buy_rate':         str(round(p['lower'], 4)),
                            'sell_rate':        str(round(p['upper'], 4)),
                            'confidence_lower': str(round(p['lower'], 4)),
                            'confidence_upper': str(round(p['upper'], 4)),
                            'confidence_score': p['confidence'],
                        }
                        for p in naive
                    ]
                },
                'generated_at': timezone.now(),
            })
        
        # Agrupar por modelo
        predictions_by_model = {}
        
        for pred in predictions:
            model_type = pred.model.model_type
            if model_type not in predictions_by_model:
                predictions_by_model[model_type] = []
            
            predictions_by_model[model_type].append({
                'date':              pred.prediction_date,
                'rate':              str(pred.predicted_rate),
                'buy_rate':          str(pred.predicted_buy_rate),
                'sell_rate':         str(pred.predicted_sell_rate),
                'confidence_lower':  str(pred.confidence_lower),
                'confidence_upper':  str(pred.confidence_upper),
                'confidence_score':  pred.confidence_score,
            })
        
        return Response({
            'currency_pair': currency_pair,
            'predictions': predictions_by_model,
            # LIVE = predicciones reales de modelos entrenados (vs 'FALLBACK'
            # naive del arranque en frío). El frontend lo usa para distinguir
            # visualmente un pronóstico estimado de uno real.
            'model_status': 'LIVE',
            'data_freshness': 'LIVE',
            'generated_at': timezone.now()
        })
    
    @action(detail=False, methods=['POST'], url_path='generate')
    def generate(self, request):
        """Genera nuevas predicciones"""
        currency_pair = request.data.get('currency_pair')
        horizon = request.data.get('horizon', 24)
        
        if not currency_pair:
            return Response(
                {'error': 'currency_pair es requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from .ml_service import ForexPredictionService
            service = ForexPredictionService()
            predictions = service.predict_rates(currency_pair, horizon)
            
            return Response({
                'success': True,
                'predictions_generated': len(predictions)
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['GET'], url_path='accuracy-report')
    def accuracy_report(self, request):
        """Reporte de precisión de predicciones"""
        days = int(request.query_params.get('days', 7))
        
        # Obtener predicciones con valores reales
        evaluated_predictions = Prediction.objects.filter(
            actual_rate__isnull=False,
            created_at__gte=timezone.now() - timedelta(days=days)
        )
        
        # Agrupar por modelo y calcular métricas
        report = {}
        
        for model_type in ['PROPHET', 'LSTM', 'ENSEMBLE']:
            model_predictions = evaluated_predictions.filter(
                model__model_type=model_type
            )
            
            if model_predictions.exists():
                errors = []
                within_confidence = 0
                
                for pred in model_predictions:
                    errors.append(pred.error_percentage)
                    
                    if pred.confidence_lower <= pred.actual_rate <= pred.confidence_upper:
                        within_confidence += 1
                
                report[model_type] = {
                    'total_predictions': len(errors),
                    'average_error': sum(errors) / len(errors) if errors else 0,
                    'max_error': max(errors) if errors else 0,
                    'min_error': min(errors) if errors else 0,
                    'within_confidence_interval': within_confidence,
                    'confidence_accuracy': (within_confidence / len(errors) * 100) if errors else 0
                }
        
        return Response(report)

class PredictionsDashboardView(APIView):
    """
    Endpoint simple de predicciones basado en promedios móviles.
    No requiere modelos ML entrenados; funciona con datos históricos de Transaction.
    GET /api/predictions/dashboard/
    """
    permission_classes = [IsAuthenticated]

    WINDOW = 7   # días para moving average
    HORIZON = 7  # días a predecir
    Z_THRESHOLD = 2.0

    def get(self, request):
        from transactions.models import Transaction

        today = timezone.now().date()
        days_90_ago = today - timedelta(days=90)

        try:
            rows = list(
                Transaction.objects
                .filter(status='COMPLETED', created_at__date__gte=days_90_ago)
                .annotate(day=TruncDate('created_at'))
                .values('day')
                .annotate(count=Count('id'), volume=Sum('amount_to'))
                .order_by('day')
            )
        except Exception:
            return self._empty()

        if len(rows) < 3:
            return self._empty()

        counts  = [int(r['count'])           for r in rows]
        volumes = [int(r['volume'] or 0)     for r in rows]

        # ── Moving averages ─────────────────────────────────────────────
        w = min(self.WINDOW, len(counts))
        def ma(series, idx):
            start = max(0, idx - w + 1)
            chunk = series[start: idx + 1]
            return sum(chunk) / len(chunk)

        last_count_ma  = ma(counts,  len(counts)  - 1)
        last_volume_ma = ma(volumes, len(volumes) - 1)

        # ── Trend ───────────────────────────────────────────────────────
        trend = 'stable'
        if len(counts) >= 14:
            recent = sum(counts[-7:]) / 7
            prev   = sum(counts[-14:-7]) / 7
            if prev > 0:
                change = (recent - prev) / prev
                if change > 0.05:
                    trend = 'up'
                elif change < -0.05:
                    trend = 'down'

        # ── Forecast next N days ────────────────────────────────────────
        forecast = []
        for i in range(1, self.HORIZON + 1):
            forecast.append({
                'date':                    str(today + timedelta(days=i)),
                'predicted_transactions':  round(last_count_ma),
                'predicted_volume':        round(last_volume_ma),
            })

        # ── Anomaly detection (z-score) ─────────────────────────────────
        anomalies = []
        if len(counts) >= 10:
            try:
                mean = statistics.mean(counts)
                std  = statistics.stdev(counts)
                if std > 0:
                    for i, r in enumerate(rows):
                        z = (counts[i] - mean) / std
                        if abs(z) >= self.Z_THRESHOLD:
                            anomalies.append({
                                'date':     str(r['day']),
                                'value':    counts[i],
                                'expected': round(mean, 1),
                                'z_score':  round(z, 2),
                                'type':     'high' if z > 0 else 'low',
                            })
            except statistics.StatisticsError:
                pass

        return Response({
            'forecast_next_days': forecast,
            'trend':              trend,
            'anomalies':          anomalies[-10:],
        })

    @staticmethod
    def _empty():
        return Response({
            'forecast_next_days': [],
            'trend':              'stable',
            'anomalies':          [],
        })


class ForecastView(APIView):
    """
    GET /api/predictions/forecast/{currency_pair}/
    Query params:
      horizon      — 1h | 4h | 24h (default) | 7d
      ci           — true | false  (incluir intervalos de confianza)
      refresh      — true           (forzar regeneración, ignorar caché)
    Response:
      predicted_rate, confidence_interval, model_weights,
      feature_importance, backtesting_metrics, data_freshness, predictions[]
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, currency_pair):
        horizon = request.query_params.get('horizon', '24h')
        if horizon not in VALID_HORIZONS:
            return Response(
                {'error': f'horizon debe ser uno de: {", ".join(VALID_HORIZONS)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from predictions.market_keys import VALID_MARKETS
        pair_norm = currency_pair.replace('-', '/')
        # Mercado por defecto POR DIVISA: para USD la serie profunda y operativa
        # es 'web' (paralelo digital / dólar blue); para las demás divisas el
        # mercado real donde opera la casa es 'competencia' (físico, ~1.300 días).
        # La serie web de esas divisas es delgada/derivada del internacional y
        # daba pronósticos bajos con modelos huérfanos. El usuario puede forzar
        # otro mercado con ?market=.
        default_market = 'web' if pair_norm == 'USD/BOB' else 'competencia'
        market = request.query_params.get('market', default_market).lower()
        if market not in VALID_MARKETS:
            return Response(
                {'error': f'market debe ser uno de: {", ".join(VALID_MARKETS)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        use_cache = request.query_params.get('refresh', 'false').lower() != 'true'
        show_ci   = request.query_params.get('ci', 'true').lower() != 'false'

        # Arranque en frio: si la cache esta vacia, NO computar el forecast pesado
        # (build de features de 3 anios + inferencia de 4 modelos + backtesting)
        # dentro del request -> bloquea el worker gunicorn (la web llama con timeout
        # de 90 s). Se encola el pre-warm en background (mismo debounce que /current/)
        # y se sirve el fallback naive de inmediato. La clave de cache es identica a la
        # de ForexMLEngine.predict (ml_engine.py). refresh=true (use_cache False) respeta
        # la regeneracion sincrona explicita (opt-in).

        # ── Cadena de mercados a intentar ────────────────────────────────────
        # Se sirve el primer mercado con forecast real y se anota cuál se usó
        # (market / market_fallback). El respaldo prioriza competencia (físico
        # real) sobre web para las divisas ≠USD; para USD, web primero.
        _rest = (['web', 'competencia', 'empresa'] if pair_norm == 'USD/BOB'
                 else ['competencia', 'empresa', 'web'])
        market_chain = [market] + [m for m in _rest if m != market]

        from django.core.cache import cache as _cache

        def _finish(res: dict) -> Response:
            if not show_ci:
                res.pop('confidence_interval', None)
                for p in res.get('predictions', []):
                    p.pop('lower', None)
                    p.pop('upper', None)
            return Response(res)

        if use_cache:
            # 1) Servir desde caché el primer mercado que tenga forecast real
            for mkt in market_chain:
                cached = _cache.get(f'ml_forecast:{pair_norm}:{mkt}:{horizon}')
                if isinstance(cached, dict):
                    cached.setdefault('market', mkt)
                    cached['market_fallback'] = (mkt != market)
                    return _finish(cached)

            # 2) Caché frío en TODOS los mercados: encolar prewarm y servir
            #    fallback plano (inference) sin bloquear el worker.
            fallback = _forecast_fallback(currency_pair, horizon)
            if fallback:
                if not _cache.get('forecast_prewarm_enqueued'):
                    try:
                        from predictions.tasks import cache_forecast_hourly
                        cache_forecast_hourly.delay()
                        _cache.set('forecast_prewarm_enqueued', 1, 120)  # debounce 2 min
                    except Exception as exc:
                        import logging as _log
                        _log.getLogger('predictions').warning(
                            'forecast prewarm enqueue failed for %s: %s', currency_pair, exc
                        )
                return Response(fallback)
            # Sin fallback disponible (sin tasa actual): cae al camino normal.

        result = None
        last_value_error = None
        try:
            from predictions.ml_engine import ForexMLEngine
            engine = ForexMLEngine()
            for mkt in market_chain:
                try:
                    result = engine.predict(
                        currency_pair=pair_norm,
                        horizon_key=horizon,
                        use_cache=use_cache,
                        market=mkt,
                    )
                    result['market'] = mkt
                    result['market_fallback'] = (mkt != market)
                    break
                except ValueError as exc:   # sin modelo/datos en este mercado
                    last_value_error = exc
                    continue
        except RuntimeError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response(
                {'error': 'Error generando pronóstico', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if result is None:
            # Ningún mercado tiene modelo — fallback plano de la tasa actual
            fallback = _forecast_fallback(currency_pair, horizon)
            if fallback:
                return Response(fallback)
            return Response({'error': str(last_value_error or 'sin modelo entrenado')},
                            status=status.HTTP_404_NOT_FOUND)

        if not show_ci:
            result.pop('confidence_interval', None)
            for p in result.get('predictions', []):
                p.pop('lower', None)
                p.pop('upper', None)

        return Response(result)


class ModelHealthView(APIView):
    """
    GET /api/predictions/health/
    Retorna estado de salud de cada modelo: última vez entrenado, MAPE reciente,
    drift detectado, frescura de datos.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            from predictions.monitoring import ModelMonitor
            monitor = ModelMonitor()
            report  = monitor.health_report()
            return Response(report)
        except Exception as exc:
            return Response(
                {'error': 'No se pudo obtener estado de salud', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SimulationView(APIView):
    """
    GET /api/predictions/simulate/{currency_pair}/

    Monte Carlo calibrado con la serie diaria REAL (TrainingData) del par/mercado.

    Query params:
      market       — web (default) | competencia | empresa
      horizon_days — 1..365 (default 30)
      n_paths      — 100..10000 (default 2000)
      method       — bootstrap (default, re-muestrea retornos reales) | gbm
      shock_pct    — estrés inicial ±% (default 0; ej. 15 = devaluación 15%)
      var          — true para incluir VaR/ES de la posición real de inventario
      confidence   — nivel VaR (default 0.95)
      seed         — reproducibilidad (opcional)

    Response: bands (percentiles por día), final_distribution, calibration,
    y position_risk si var=true.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, currency_pair):
        from predictions.market_keys import VALID_MARKETS
        from predictions.simulation import (
            SimulationError, inventory_position, load_series,
            position_var, simulate_paths,
        )

        pair = currency_pair.replace('-', '/')
        market = request.query_params.get('market', 'web').lower()
        if market not in VALID_MARKETS:
            return Response(
                {'error': f'market debe ser uno de: {", ".join(VALID_MARKETS)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            horizon = int(request.query_params.get('horizon_days', 30))
            n_paths = int(request.query_params.get('n_paths', 2000))
            shock   = float(request.query_params.get('shock_pct', 0))
            conf    = float(request.query_params.get('confidence', 0.95))
            seed_q  = request.query_params.get('seed')
            seed    = int(seed_q) if seed_q else None
        except (TypeError, ValueError):
            return Response({'error': 'parámetros numéricos inválidos'},
                            status=status.HTTP_400_BAD_REQUEST)
        method = request.query_params.get('method', 'bootstrap').lower()
        if not (0.5 <= conf <= 0.999):
            return Response({'error': 'confidence fuera de rango [0.5, 0.999]'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            series = load_series(pair, market=market)
            result = simulate_paths(series, horizon_days=horizon,
                                    n_paths=n_paths, method=method,
                                    shock_pct=shock, seed=seed)
        except SimulationError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'error': 'simulación fallida', 'detail': str(exc)},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # VaR de la posición REAL de inventario (opcional)
        if request.query_params.get('var', 'false').lower() == 'true':
            try:
                code = pair.split('/')[0]
                amount = inventory_position(code)
                result['position_risk'] = (
                    position_var(result, amount, confidence=conf)
                    if amount > 0 else
                    {'position_amount': 0,
                     'note': f'sin posición de {code} en inventario'}
                )
            except Exception as exc:
                result['position_risk'] = {'error': str(exc)}

        result.pop('_finals', None)   # distribución cruda: solo uso interno
        return Response(result)


class AdvisorChatView(APIView):
    """
    POST /api/predictions/advisor/   {"message": "¿compro dólares hoy?"}

    Asesor de compra/venta de divisas: compone el pronóstico ML, la brecha
    oficial BCB↔paralelo, el sentimiento de noticias (RSS), Monte Carlo sobre
    retornos reales, la posición de inventario y el motor AI de pricing en una
    recomendación COMPRAR/ESPERAR/VENDER con razones (determinista, sin LLM).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        message = (request.data.get('message') or '').strip()
        if not message:
            return Response({'error': 'message requerido'},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(message) > 500:
            return Response({'error': 'message demasiado largo (máx 500)'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            from predictions.advisor import advise
            return Response(advise(message))
        except Exception as exc:
            return Response(
                {'error': 'asesor no disponible', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
