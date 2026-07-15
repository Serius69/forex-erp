"""Tareas Celery del módulo macro."""
import logging

from celery import shared_task

log = logging.getLogger('kapitalya.macro.tasks')


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='macro.fetch_daily_indicators',
    soft_time_limit=120,
)
def fetch_daily_indicators(self):
    """USD internacional (er-api) + brecha oficial↔paralelo del día."""
    from .fetchers import (compute_brecha_oficial, fetch_usd_internacional,
                           persist_points, snapshot_oficial_diario)

    log.info('TASK_START macro.fetch_daily_indicators')
    try:
        points = (fetch_usd_internacional() + compute_brecha_oficial()
                  + snapshot_oficial_diario())
        saved = persist_points(points)
        log.info('TASK_DONE macro.fetch_daily_indicators saved=%d', saved)
        return {'saved': saved}
    except Exception as exc:
        log.error('TASK_ERROR macro.fetch_daily_indicators error=%s', exc)
        raise self.retry(exc=exc, countdown=300)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='macro.fetch_world_bank_indicators',
    soft_time_limit=300,
)
def fetch_world_bank_indicators(self):
    """Series anuales del World Bank (histórico completo, upsert idempotente)."""
    from .fetchers import fetch_world_bank, persist_points

    log.info('TASK_START macro.fetch_world_bank_indicators')
    try:
        saved = persist_points(fetch_world_bank())
        log.info('TASK_DONE macro.fetch_world_bank_indicators saved=%d', saved)
        return {'saved': saved}
    except Exception as exc:
        log.error('TASK_ERROR macro.fetch_world_bank_indicators error=%s', exc)
        raise self.retry(exc=exc, countdown=600)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='macro.fetch_news',
    soft_time_limit=180,
)
def fetch_news_task(self):
    """Cada 4 h — noticias del mercado cambiario + índice de sentimiento."""
    from .news import fetch_news

    log.info('TASK_START macro.fetch_news')
    try:
        result = fetch_news()
        log.info('TASK_DONE macro.fetch_news %s', result)
        return result
    except Exception as exc:
        log.error('TASK_ERROR macro.fetch_news error=%s', exc)
        raise self.retry(exc=exc, countdown=600)
