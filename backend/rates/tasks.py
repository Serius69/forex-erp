from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
import logging
from .services import RateService

logger = logging.getLogger(__name__)

@shared_task
def update_exchange_rates():
    """Tarea para actualizar tasas de cambio automáticamente"""
    service = RateService()
    
    try:
        # Intentar BCB primero
        rates = service.fetch_official_rates('BCB')
        
        if not rates:
            # Intentar fuente alternativa
            rates = service.fetch_official_rates('BCP')
        
        logger.info(f"Tasas actualizadas: {rates}")
        
        # Notificar si hay cambios significativos
        check_significant_changes(rates)
        
        return {'success': True, 'rates': rates}
        
    except Exception as e:
        logger.error(f"Error actualizando tasas: {str(e)}")
        
        # Notificar al administrador
        send_mail(
            'Error actualizando tasas de cambio',
            f'Se produjo un error al actualizar las tasas: {str(e)}',
            settings.DEFAULT_FROM_EMAIL,
            ['admin@casadecambio.com'],
            fail_silently=True,
        )
        
        return {'success': False, 'error': str(e)}

@shared_task
def check_significant_changes(new_rates):
    """Verifica cambios significativos en las tasas"""
    from .models import ExchangeRate, Currency
    from decimal import Decimal
    
    threshold = Decimal('0.02')  # 2% de cambio
    alerts = []
    
    for currency_code, new_rate in new_rates.items():
        try:
            currency = Currency.objects.get(code=currency_code)
            
            # Obtener tasa anterior
            previous_rate = ExchangeRate.objects.filter(
                currency_from=currency,
                currency_to__code='BOB'
            ).exclude(valid_until__isnull=False).first()
            
            if previous_rate:
                change = abs(new_rate - previous_rate.official_rate)
                change_percentage = (change / previous_rate.official_rate) * 100
                
                if change_percentage > threshold:
                    alerts.append({
                        'currency': currency_code,
                        'previous': float(previous_rate.official_rate),
                        'new': float(new_rate),
                        'change_percentage': float(change_percentage)
                    })
        except:
            pass
    
    if alerts:
        # Enviar notificación
        send_rate_change_alert(alerts)
    
    return alerts

def send_rate_change_alert(alerts):
    """Envía alerta de cambios significativos"""
    message = "Se detectaron cambios significativos en las tasas:\n\n"
    
    for alert in alerts:
        message += f"{alert['currency']}: {alert['previous']} → {alert['new']} "
        message += f"({alert['change_percentage']:.2f}% cambio)\n"
    
    send_mail(
        'Alerta: Cambios significativos en tasas de cambio',
        message,
        settings.DEFAULT_FROM_EMAIL,
        ['gerencia@casadecambio.com'],
        fail_silently=True,
    )