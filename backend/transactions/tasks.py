# transactions/tasks.py
import logging
from celery import shared_task

log = logging.getLogger('transactions.tasks')


@shared_task(
    bind=True,
    name='transactions.refresh_fraud_rules_cache',
    max_retries=2,
    acks_late=True,
)
def refresh_fraud_rules_cache(self):
    """
    Invalida el caché de reglas antifraude para que los workers
    recarguen desde DB en el próximo request.
    Ejecutar cada 5 minutos vía Celery Beat.
    """
    try:
        from django.core.cache import cache
        cache.delete('fraud_rules_active')
        log.debug('FRAUD_RULES_CACHE_INVALIDATED')
        return {'status': 'ok'}
    except Exception as exc:
        log.warning('FRAUD_RULES_CACHE_ERR err=%s', exc)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    name='transactions.check_rate_lock_expirations',
    max_retries=2,
    acks_late=True,
)
def check_rate_lock_expirations(self):
    """
    Verifica transacciones con rate_lock_expires_at vencido y recalcula
    la tasa paralela actual, marcándolas para re-aprobación si cambió.
    Ejecutar cada minuto en producción o cada 5 min en staging.
    """
    try:
        from django.utils import timezone
        from transactions.models import Transaction
        from rates.parallel_rate_service import ParallelRateService

        expired = Transaction.objects.filter(
            rate_lock_expires_at__lt=timezone.now(),
            status__in=('PENDING_RATE', 'PENDING', 'DRAFT'),
        ).select_related('currency_from', 'currency_to')

        svc     = ParallelRateService()
        updated = 0

        for tx in expired:
            currency = tx.currency_from.code if tx.currency_from.code != 'BOB' else tx.currency_to.code
            try:
                new_par = svc.get_cached_rate(currency)
                if new_par:
                    old_par = tx.parallel_rate_at_creation
                    if old_par and abs(new_par - old_par) / old_par > 0.005:  # >0.5% cambio
                        tx.status            = 'PENDING_RATE'
                        tx.approval_required = True
                        tx.save(update_fields=['status', 'approval_required', 'updated_at'])
                        log.info('RATE_LOCK_EXPIRED_RECALC tx=%s old=%s new=%s', tx.transaction_number, old_par, new_par)
                        updated += 1
            except Exception as exc:
                log.warning('RATE_LOCK_TX_ERR tx=%s err=%s', tx.transaction_number, exc)

        log.info('RATE_LOCK_CHECK_DONE expired=%d recalculated=%d', expired.count(), updated)
        return {'expired': expired.count(), 'recalculated': updated}
    except Exception as exc:
        log.error('RATE_LOCK_CHECK_FAIL err=%s', exc, exc_info=True)
        raise self.retry(exc=exc)
