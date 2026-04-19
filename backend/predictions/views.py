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
        
        # Si no hay predicciones, generarlas
        if not predictions.exists():
            from .ml_service import ForexPredictionService
            service = ForexPredictionService()
            service.predict_rates(currency_pair, horizon=24)
            
            # Re-consultar
            predictions = self.get_queryset().filter(
                currency_pair=currency_pair,
                prediction_date__gte=timezone.now(),
                prediction_date__lte=timezone.now() + timedelta(hours=24)
            ).order_by('prediction_date')
        
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
