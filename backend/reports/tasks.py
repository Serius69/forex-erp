from celery import shared_task
from django.utils import timezone
from datetime import datetime, timedelta
from django.core.mail import EmailMessage
from django.conf import settings
import logging
from .generators import ReportGenerator
from .models import Report, ReportSchedule

logger = logging.getLogger(__name__)

@shared_task
def generate_daily_report():
    """Genera reporte diario automáticamente"""
    from users.models import User
    
    # Usar fecha de ayer (los reportes diarios se generan al día siguiente)
    report_date = (timezone.now() - timedelta(days=1)).date()
    
    logger.info(f"Generando reporte diario para {report_date}")
    
    # Obtener usuario del sistema
    system_user = User.objects.filter(username='system').first()
    if not system_user:
        system_user = User.objects.filter(is_superuser=True).first()
    
    # Generar reporte para cada sucursal
    from users.models import Branch
    
    for branch in Branch.objects.filter(is_active=True):
        try:
            generator = ReportGenerator(
                start_date=report_date,
                end_date=report_date,
                branch=branch,
                user=system_user
            )
            
            report = generator.generate_daily_report()
            
            # Enviar por email
            send_report_email(report, [
                'gerencia@casadecambio.com',
                f'{branch.code}@casadecambio.com'
            ])
            
            logger.info(f"Reporte diario generado para {branch.name}")
            
        except Exception as e:
            logger.error(f"Error generando reporte para {branch.name}: {str(e)}")
    
    # Generar reporte consolidado
    try:
        generator = ReportGenerator(
            start_date=report_date,
            end_date=report_date,
            branch=None,  # Todas las sucursales
            user=system_user
        )
        
        consolidated_report = generator.generate_daily_report()
        consolidated_report.title = f"Reporte Consolidado - {report_date}"
        consolidated_report.save()
        
        # Enviar a dirección
        send_report_email(consolidated_report, ['direccion@casadecambio.com'])
        
    except Exception as e:
        logger.error(f"Error generando reporte consolidado: {str(e)}")
    
    return {'date': str(report_date), 'status': 'completed'}

@shared_task
def generate_scheduled_reports():
    """Genera reportes programados"""
    schedules = ReportSchedule.objects.filter(is_active=True)
    
    for schedule in schedules:
        try:
            # Verificar si debe ejecutarse
            if should_run_schedule(schedule):
                generate_scheduled_report(schedule)
                
                # Actualizar próxima ejecución
                schedule.last_run = timezone.now()
                schedule.next_run = calculate_next_run(schedule)
                schedule.save()
                
        except Exception as e:
            logger.error(f"Error en reporte programado {schedule.name}: {str(e)}")

def should_run_schedule(schedule):
    """Determina si un reporte programado debe ejecutarse"""
    now = timezone.now()
    
    # Si nunca se ha ejecutado
    if not schedule.last_run:
        return True
    
    # Si ya pasó la próxima ejecución
    if schedule.next_run and now >= schedule.next_run:
        return True
    
    # Verificar según frecuencia
    if schedule.frequency == 'DAILY':
        return (now - schedule.last_run).days >= 1
    elif schedule.frequency == 'WEEKLY':
        return (now - schedule.last_run).days >= 7
    elif schedule.frequency == 'MONTHLY':
        return (now - schedule.last_run).days >= 30
    
    return False

def calculate_next_run(schedule):
    """Calcula la próxima ejecución de un reporte"""
    now = timezone.now()
    
    if schedule.frequency == 'DAILY':
        # Mañana a las 6 AM
        next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
    
    elif schedule.frequency == 'WEEKLY':
        # Próximo lunes a las 6 AM
        days_ahead = 0 - now.weekday()  # 0 es lunes
        if days_ahead <= 0:
            days_ahead += 7
        next_run = now + timedelta(days=days_ahead)
        next_run = next_run.replace(hour=6, minute=0, second=0, microsecond=0)
    
    elif schedule.frequency == 'MONTHLY':
        # Primer día del próximo mes a las 6 AM
        if now.month == 12:
            next_run = now.replace(year=now.year + 1, month=1, day=1,
                                 hour=6, minute=0, second=0, microsecond=0)
        else:
            next_run = now.replace(month=now.month + 1, day=1,
                                 hour=6, minute=0, second=0, microsecond=0)
    
    return next_run

def generate_scheduled_report(schedule):
    """Genera un reporte según la programación"""
    from users.models import User
    
    # Determinar período
    end_date = timezone.now().date()
    
    if schedule.frequency == 'DAILY':
        start_date = end_date - timedelta(days=1)
    elif schedule.frequency == 'WEEKLY':
        start_date = end_date - timedelta(days=7)
    elif schedule.frequency == 'MONTHLY':
        start_date = end_date - timedelta(days=30)
    else:
        start_date = end_date
    
    # Generar reporte
    generator = ReportGenerator(
        start_date=start_date,
        end_date=end_date,
        branch=schedule.parameters.get('branch'),
        user=schedule.created_by
    )
    
    # Generar según tipo
    if schedule.report_type == 'DAILY':
        report = generator.generate_daily_report()
    elif schedule.report_type == 'REGULATORY':
        report = generator.generate_regulatory_report()
    else:
        # Implementar otros tipos según necesidad
        report = generator.generate_daily_report()
    
    # Actualizar título
    report.title = f"{schedule.name} - {start_date} a {end_date}"
    report.save()
    
    # Enviar por email si está configurado
    if schedule.send_email and schedule.email_recipients:
        send_report_email(report, schedule.email_recipients)
    
    logger.info(f"Reporte programado '{schedule.name}' generado exitosamente")

def send_report_email(report, recipients):
    """Envía reporte por email"""
    if not recipients:
        return
    
    subject = f"[Casa de Cambio] {report.title}"
    message = f"""
    Estimado usuario,
    
    Se ha generado el siguiente reporte:
    
    {report.title}
    Período: {report.start_date} - {report.end_date}
    
    Los archivos del reporte se encuentran adjuntos a este correo.
    
    Saludos cordiales,
    Sistema ERP Casa de Cambio
    """
    
    email = EmailMessage(
        subject=subject,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    
    # Adjuntar archivos
    if report.pdf_file:
        email.attach_file(report.pdf_file.path)
    if report.excel_file:
        email.attach_file(report.excel_file.path)
    
    try:
        email.send()
        logger.info(f"Reporte {report.id} enviado a {', '.join(recipients)}")
    except Exception as e:
        logger.error(f"Error enviando reporte {report.id}: {str(e)}")

@shared_task
def cleanup_old_reports():
    """Limpia reportes antiguos (más de 90 días)"""
    cutoff_date = timezone.now() - timedelta(days=90)
    
    old_reports = Report.objects.filter(
        generated_at__lt=cutoff_date
    ).exclude(
        report_type__in=['REGULATORY', 'TAX']  # Mantener reportes regulatorios
    )
    
    count = 0
    for report in old_reports:
        # Eliminar archivos
        if report.pdf_file:
            report.pdf_file.delete()
        if report.excel_file:
            report.excel_file.delete()
        
        report.delete()
        count += 1
    
    logger.info(f"Eliminados {count} reportes antiguos")
    
    return {'deleted': count}