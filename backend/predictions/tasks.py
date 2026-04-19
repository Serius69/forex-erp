from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging
from .models import PredictionModel, Prediction, TrainingData
from rates.models import ExchangeRate

logger = logging.getLogger(__name__)

@shared_task
def train_prediction_models():
    """Tarea para entrenar todos los modelos de predicción"""
    from .ml_service import ForexPredictionService
    service = ForexPredictionService()
    currencies = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'ARS/BOB']
    
    results = {}
    
    for currency_pair in currencies:
        try:
            logger.info(f"Entrenando modelos para {currency_pair}")
            
            # Actualizar datos de entrenamiento
            update_training_data(currency_pair)
            
            # Entrenar Prophet
            prophet_model, prophet_metrics = service.train_prophet_model(currency_pair)
            results[f'{currency_pair}_prophet'] = prophet_metrics
            
            # Entrenar LSTM
            lstm_model, lstm_metrics = service.train_lstm_model(currency_pair)
            results[f'{currency_pair}_lstm'] = lstm_metrics
            
            # Entrenar Ensemble
            ensemble_model = service.train_ensemble_model(currency_pair)
            results[f'{currency_pair}_ensemble'] = 'success'
            
        except Exception as e:
            logger.error(f"Error entrenando modelos para {currency_pair}: {str(e)}")
            results[f'{currency_pair}_error'] = str(e)
    
    return results

@shared_task
def generate_predictions():
    """Genera predicciones para las próximas 24 horas"""
    from .ml_service import ForexPredictionService
    service = ForexPredictionService()
    currencies = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'ARS/BOB']
    
    total_predictions = 0
    
    for currency_pair in currencies:
        try:
            predictions = service.predict_rates(currency_pair, horizon=24)
            total_predictions += len(predictions)
            
            logger.info(f"Generadas {len(predictions)} predicciones para {currency_pair}")
            
        except Exception as e:
            logger.error(f"Error generando predicciones para {currency_pair}: {str(e)}")
    
    # Limpiar predicciones antiguas (más de 7 días)
    old_predictions = Prediction.objects.filter(
        created_at__lt=timezone.now() - timedelta(days=7)
    )
    deleted_count = old_predictions.count()
    old_predictions.delete()
    
    logger.info(f"Eliminadas {deleted_count} predicciones antiguas")
    
    return {
        'predictions_generated': total_predictions,
        'old_predictions_deleted': deleted_count
    }

@shared_task
def update_training_data(currency_pair):
    """Actualiza datos de entrenamiento desde tasas históricas"""
    # Obtener últimas tasas
    currency_from_code, currency_to_code = currency_pair.split('/')
    
    rates = ExchangeRate.objects.filter(
        currency_from__code=currency_from_code,
        currency_to__code=currency_to_code
    ).order_by('-valid_from')[:1000]  # Últimas 1000 tasas
    
    for rate in rates:
        TrainingData.objects.update_or_create(
            currency_pair=currency_pair,
            date=rate.valid_from,
            defaults={
                'rate': rate.official_rate,
                'source': rate.source
            }
        )
    
    logger.info(f"Actualizados datos de entrenamiento para {currency_pair}")

@shared_task
def evaluate_predictions():
    """Evalúa la precisión de las predicciones comparando con valores reales"""
    # Obtener predicciones de hace 24 horas
    evaluation_time = timezone.now() - timedelta(hours=24)
    
    predictions = Prediction.objects.filter(
        created_at__gte=evaluation_time - timedelta(hours=1),
        created_at__lt=evaluation_time + timedelta(hours=1),
        actual_rate__isnull=True
    )
    
    evaluated_count = 0
    
    for prediction in predictions:
        # Buscar tasa real para ese momento
        currency_from_code, currency_to_code = prediction.currency_pair.split('/')
        
        actual_rate = ExchangeRate.objects.filter(
            currency_from__code=currency_from_code,
            currency_to__code=currency_to_code,
            valid_from__lte=prediction.prediction_date,
            valid_until__gte=prediction.prediction_date
        ).first()
        
        if actual_rate:
            prediction.actual_rate = actual_rate.official_rate
            prediction.calculate_error()
            evaluated_count += 1
    
    # Actualizar métricas de modelos
    update_model_metrics()
    
    return {
        'predictions_evaluated': evaluated_count
    }

@shared_task(name='predictions.generate_daily_forecast')
def generate_daily_forecast():
    """
    Genera predicciones de TC para los próximos 14 días.
    Programado diariamente a la 01:00 por Celery Beat.
    Extiende generate_predictions() con un horizonte mayor para el frontend.
    """
    from .ml_service import ForexPredictionService
    service = ForexPredictionService()
    currencies = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'ARS/BOB', 'PEN/BOB']
    total = 0

    for currency_pair in currencies:
        try:
            predictions = service.predict_rates(currency_pair, horizon=14 * 24)  # 14 días en horas
            total += len(predictions)
            logger.info('generate_daily_forecast %s: %d predicciones', currency_pair, len(predictions))
        except Exception as exc:
            logger.warning('generate_daily_forecast SKIP %s: %s', currency_pair, exc)

    return {'generated': total, 'currencies': len(currencies)}


def update_model_metrics():
    """Actualiza métricas de rendimiento de los modelos"""
    models = PredictionModel.objects.filter(is_active=True)
    
    for model in models:
        # Obtener predicciones recientes con valores reales
        recent_predictions = Prediction.objects.filter(
            model=model,
            actual_rate__isnull=False,
            created_at__gte=timezone.now() - timedelta(days=30)
        )
        
        if recent_predictions.count() > 0:
            # Calcular métricas
            errors = []
            for pred in recent_predictions:
                if pred.actual_rate and pred.predicted_rate:
                    error = abs(pred.actual_rate - pred.predicted_rate)
                    error_pct = (error / pred.actual_rate) * 100
                    errors.append(error_pct)
            
            if errors:
                model.metrics['recent_mape'] = sum(errors) / len(errors)
                model.metrics['recent_predictions'] = len(errors)
                model.metrics['last_evaluation'] = timezone.now().isoformat()
                model.save()