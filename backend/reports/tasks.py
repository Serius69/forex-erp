from celery import shared_task
from django.utils import timezone
from datetime import datetime, timedelta
from django.core.mail import EmailMessage
from django.conf import settings
import logging
from .generators import ReportGenerator
from .models import GeneratedReport

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
    """Genera reportes programados (ReportSchedule pendiente de implementar)."""
    logger.info("generate_scheduled_reports: ReportSchedule model not yet implemented, skipping.")
    return {'status': 'skipped', 'reason': 'ReportSchedule model not available'}


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
    """Limpia GeneratedReport con más de 90 días (excluye tipos regulatorios)."""
    cutoff_date = timezone.now() - timedelta(days=90)
    KEEP_TYPES = {'RTE_MONTHLY', 'ROUE_REPORT', 'PEP_LIST', 'DAILY_LOG'}

    old_reports = GeneratedReport.objects.filter(
        generated_at__lt=cutoff_date
    ).exclude(report_type__in=KEEP_TYPES)

    count = old_reports.count()
    old_reports.delete()

    logger.info(f"Eliminados {count} reportes antiguos")
    return {'deleted': count}