# transactions/signals.py
"""
Señales Django para la aplicación de transacciones.

PROPÓSITO:
    Garantizar que los efectos de caja BOB se apliquen automáticamente
    para CUALQUIER ruta de creación de Transaction, no solo la vista REST.
    Esto incluye: panel de admin Django, management commands, importaciones,
    scripts de migración de datos o cualquier código que llame
    Transaction.objects.create() directamente.

DISEÑO (idempotencia):
    La señal verifica si ya existe un CashFlowLog para la transacción
    antes de actuar. Esto previene doble-aplicación cuando la vista ya
    llamó apply_transaction_effects() de forma explícita.

    Flujo normal (vista REST):
        1. Vista llama apply_transaction_effects(tx) → CashFlowLog creado
        2. post_save se dispara → CashFlowLog existe → señal hace nada

    Flujo admin / script:
        1. Transaction guardada directamente
        2. post_save se dispara → no hay CashFlowLog → señal aplica efectos

SEÑALES:
    · transaction_post_save   — aplica efectos BOB al crear (COMPLETED)
    · transaction_status_change — futuro hook para cambios de estado
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

log = logging.getLogger('transactions.signals')


def _telegram_large_tx(instance) -> None:
    """Fire-and-forget: envía alerta Telegram por transacción de alto monto."""
    try:
        from django.conf import settings
        from services.notifications.telegram import alert_large_transaction

        threshold = getattr(settings, 'LARGE_TX_THRESHOLD_BOB', 100_000)
        amount_bob = float(instance.amount_to or 0)
        if amount_bob < threshold:
            return

        try:
            currency = instance.currency_to.code
        except Exception:
            currency = 'BOB'

        alert_large_transaction(
            transaction_number=str(instance.transaction_number),
            transaction_type=instance.get_transaction_type_display(),
            amount=f'{amount_bob:,.2f}',
            currency=currency,
            user=str(getattr(instance, 'cashier', 'N/A')),
            dt=getattr(instance, 'created_at', None),
        )
    except Exception as exc:
        log.debug('TELEGRAM_LARGE_TX_FAIL tx=%s err=%s', getattr(instance, 'transaction_number', '?'), exc)


def _telegram_failed_tx(instance) -> None:
    """Fire-and-forget: envía alerta Telegram por transacción cancelada/revertida."""
    try:
        from services.notifications.telegram import alert_failed_transaction

        if instance.status not in ('CANCELLED', 'REVERSED'):
            return

        try:
            currency = instance.currency_from.code
        except Exception:
            currency = '?'

        alert_failed_transaction(
            transaction_number=str(instance.transaction_number),
            transaction_type=instance.get_transaction_type_display(),
            amount=f'{float(instance.amount_from or 0):,.2f}',
            currency=currency,
            status=instance.get_status_display(),
            user=str(getattr(instance, 'cashier', 'N/A')),
            dt=getattr(instance, 'updated_at', None),
        )
    except Exception as exc:
        log.debug('TELEGRAM_FAILED_TX_FAIL tx=%s err=%s', getattr(instance, 'transaction_number', '?'), exc)


@receiver(post_save, sender='transactions.Transaction')
def transaction_post_save(sender, instance, created, **kwargs):
    """
    Aplica efectos BOB (CapitalComposicion + CashFlowLog) cuando se crea
    una Transaction con status='COMPLETED', siempre que no se hayan
    aplicado ya (guarda idempotencia verificando CashFlowLog).

    Skips:
        · Actualizaciones (update_fields pasado → no es inserción nueva)
        · Transacciones no COMPLETED
        · Transacciones BOB↔BOB (no afectan caja de divisas)
        · Cuando apply_transaction_effects ya fue llamado (CashFlowLog existe)
    """
    # Solo actuar en creaciones, no en updates
    if not created:
        return

    if instance.status != 'COMPLETED':
        return

    # BOB↔BOB no produce movimiento de caja en divisas
    try:
        from_code = instance.currency_from.code
        to_code   = instance.currency_to.code
    except Exception:
        return   # FKs no cargados aún — skip silencioso

    if from_code == 'BOB' and to_code == 'BOB':
        return

    # Idempotencia: si la vista ya llamó apply_transaction_effects,
    # ya existe el CashFlowLog → no duplicar.
    try:
        from capital.models import CashFlowLog
        already_applied = CashFlowLog.objects.filter(
            transaction=instance
        ).exists()
        if already_applied:
            log.debug(
                'SIGNAL_SKIP tx=%s — CashFlowLog ya existe (aplicado por vista)',
                instance.transaction_number,
            )
            return
    except Exception as exc:
        log.warning('SIGNAL_CASHFLOWLOG_CHECK_FAIL tx=%s err=%s',
                    getattr(instance, 'transaction_number', instance.pk), exc)
        return

    # Aplicar efectos de caja BOB
    log.info(
        'SIGNAL_APPLY_CASH tx=%s type=%s method=%s amount_to=%s',
        instance.transaction_number, instance.transaction_type,
        instance.payment_method, instance.amount_to,
    )
    try:
        from .services import apply_transaction_effects
        apply_transaction_effects(instance)
    except Exception as exc:
        # La señal nunca debe romper el flujo que la disparó.
        # Si hay error (ej. saldo negativo) se registra en logs
        # y debe resolverse manualmente — no relanzar aquí.
        log.error(
            'SIGNAL_CASH_EFFECT_FAIL tx=%s err=%s',
            instance.transaction_number, exc,
            exc_info=True,
        )

    # Verificar anomalías en la transacción (monto alto, transacciones rápidas).
    # Fire-and-forget: errores en alerting no interrumpen el flujo principal.
    try:
        from alerts.services import GlobalAlertService

        amount_bob = float(instance.amount_to or 0)
        threshold  = 100_000  # Bs 100k — configurable vía LARGE_TX_THRESHOLD_BOB

        if amount_bob >= threshold:
            customer_str = str(instance.customer) if instance.customer else 'N/A'
            GlobalAlertService.emit(
                source     = 'TRANSACTION',
                alert_type = 'LARGE_TRANSACTION',
                severity   = 'MEDIUM',
                title      = f'Transacción de alto monto (N° {instance.transaction_number})',
                message    = (
                    f'{instance.get_transaction_type_display()} de Bs {amount_bob:,.2f} '
                    f'— cliente: {customer_str}, cajero: {instance.cashier}'
                ),
                data       = {
                    'transaction_id':     instance.id,
                    'transaction_number': instance.transaction_number,
                    'transaction_type':   instance.transaction_type,
                    'amount_bob':         str(amount_bob),
                    'payment_method':     instance.payment_method,
                },
                branch       = getattr(instance, 'branch', None),
                triggered_by = getattr(instance, 'cashier', None),
            )
            # Telegram: alerta de alto monto en tiempo real
            _telegram_large_tx(instance)
    except Exception as exc:
        log.debug('SIGNAL_ANOMALY_CHECK_FAIL tx=%s err=%s', instance.transaction_number, exc)

    # Motor de alertas inteligentes — evalúa precio, inventario, riesgo, oportunidad.
    # Se ejecuta después de on_commit para no bloquear la transacción principal.
    def _run_alert_generator():
        try:
            from alerts.services import AlertGenerator
            branch   = getattr(instance, 'branch', None)
            currency = getattr(instance.currency_from, 'code', None)
            if branch and currency and currency != 'BOB':
                AlertGenerator.generar_alertas(branch, currency=currency)
        except Exception as exc:
            log.debug('SIGNAL_ALERT_GEN_FAIL tx=%s err=%s', instance.transaction_number, exc)

    try:
        from django.db import transaction as db_tx
        db_tx.on_commit(_run_alert_generator)
    except Exception:
        pass


@receiver(post_save, sender='transactions.Transaction')
def transaction_status_change(sender, instance, created, **kwargs):
    """
    Envía alerta Telegram cuando una transacción pasa a CANCELLED o REVERSED.
    Solo actúa en actualizaciones (not created), y solo para esos estados.
    """
    if created:
        return
    if instance.status not in ('CANCELLED', 'REVERSED'):
        return
    _telegram_failed_tx(instance)


@receiver(post_save, sender='transactions.Transaction')
def broadcast_transaction_event(sender, instance, created, **kwargs):
    """Emite evento WebSocket al grupo de sucursal cuando se crea o cambia una TX."""
    try:
        from alerts.events import (
            broadcast_event,
            TRANSACTION_CREATED, TRANSACTION_STATUS_CHANGED,
        )
        event_type = TRANSACTION_CREATED if created else TRANSACTION_STATUS_CHANGED
        branch_id  = getattr(getattr(instance, 'branch', None), 'id', None)

        payload = {
            'transaction_id':     instance.pk,
            'transaction_number': str(instance.transaction_number),
            'transaction_type':   instance.transaction_type,
            'status':             instance.status,
            'amount_from':        float(instance.amount_from or 0),
            'amount_to':          float(instance.amount_to   or 0),
        }
        broadcast_event(event_type, payload, branch_id=branch_id)
    except Exception as exc:
        log.debug('TX_WS_BROADCAST_SKIP err=%s', exc)


@receiver(post_save, sender='transactions.Transaction')
def transaction_rte_check(sender, instance, created, **kwargs):
    """
    Evalúa si la transacción requiere RTE ASFI (efectivo >= USD 1,000 equiv.)
    y lo crea automáticamente con notificación push (AlertLog + WebSocket).

    Receiver separado del de efectos de caja: aquel hace early-return cuando
    la vista ya aplicó efectos (CashFlowLog existe) y el RTE debe evaluarse
    siempre. RTEService es idempotente (OneToOne transaction↔rte_report) y
    nunca propaga excepciones.
    """
    if not created:
        return
    try:
        from reports.services.rte_service import RTEService
        RTEService.evaluar_transaccion(instance)
    except Exception as exc:
        log.debug('RTE_SIGNAL_SKIP tx=%s err=%s',
                  getattr(instance, 'transaction_number', instance.pk), exc)
