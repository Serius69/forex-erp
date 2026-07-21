from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging
from .models import GeneratedReport

logger = logging.getLogger(__name__)


# NOTA: la tarea legacy `generate_daily_report` (clase ReportGenerator) y su
# helper `send_report_email` fueron eliminados: revenaban con ImportError (el
# modelo `Report` no existe), enviaban a destinatarios hardcodeados
# (@casadecambio.com) e iteraban todas las sucursales de todas las empresas sin
# aislamiento multi-tenant. El camino productivo vivo es
# `core.tasks.generate_daily_report` -> `reports.services.ReportService`.
# `generate_scheduled_reports` también se eliminó: era un stub permanente sin
# modelo ReportSchedule ni cableado en beat/urls.


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
