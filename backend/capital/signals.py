# capital/signals.py
"""
Señales que conectan Transaction → CurrencyPosition.

Cuando una Transaction se completa:
  BUY  → empresa adquiere divisa → apply_buy en CurrencyPosition
  SELL → empresa vende divisa   → apply_sell en CurrencyPosition

Las posiciones se crean on-the-fly si no existen (get_or_create con lock).
Los errores de posición nunca interrumpen el flujo de transacción.
"""
import logging
from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction as db_tx

log = logging.getLogger('capital.signals')


@receiver(post_save, sender='transactions.Transaction')
def update_currency_position(sender, instance, created, **kwargs):
    """
    Actualiza CurrencyPosition cuando una Transaction pasa a COMPLETED.
    Opera en on_commit para garantizar que la TX esté confirmada en DB.
    """
    if instance.status != 'COMPLETED':
        return

    # El caller ya aplicó/revirtió los efectos manualmente (p.ej. la
    # anti-transacción de reverse()) — no volver a mover la posición.
    if getattr(instance, '_effects_already_applied', False):
        return

    # Evitar el bucle infinito cuando la reversa crea su propia TX
    update_fields = kwargs.get('update_fields') or []
    if update_fields and 'status' not in update_fields and not created:
        return

    # Solo divisas extranjeras (no BOB↔BOB)
    try:
        from_code = instance.currency_from.code
        to_code   = instance.currency_to.code
    except Exception:
        return

    if from_code == 'BOB' and to_code == 'BOB':
        return

    def _do_update():
        try:
            _apply_position_update(instance)
        except Exception as exc:
            log.error(
                'POSITION_UPDATE_FAIL tx=%s err=%s',
                getattr(instance, 'transaction_number', '?'), exc,
                exc_info=True,
            )

    try:
        db_tx.on_commit(_do_update)
    except Exception:
        _do_update()


def _apply_position_update(tx) -> None:
    """Aplica el efecto de la TX sobre CurrencyPosition con select_for_update."""
    from capital.models import CurrencyPosition
    from capital.position_service import CapitalPositionService

    branch   = tx.branch
    from_cur = tx.currency_from
    to_cur   = tx.currency_to

    with db_tx.atomic():
        if tx.transaction_type == 'BUY':
            # Empresa COMPRA divisa (from_cur ≠ BOB normalmente)
            # amount_from = unidades de divisa adquiridas
            # amount_to   = BOB pagados
            if from_cur.code != 'BOB':
                pos, _ = CurrencyPosition.objects.select_for_update().get_or_create(
                    branch=branch, currency=from_cur,
                    defaults={'avg_acquisition_cost': tx.exchange_rate},
                )
                pos.apply_buy(
                    amount=Decimal(str(tx.amount_from)),
                    rate_bob=tx.exchange_rate,
                )
                pos.save(update_fields=[
                    'net_position', 'avg_acquisition_cost',
                    'total_bought', 'total_cost_bob', 'last_tx_at', 'updated_at',
                ])
        else:  # SELL
            # Empresa VENDE divisa
            # from_cur es la divisa que el cliente entrega (si es SELL de USD → empresa recibe USD)
            # Depende de la convención: en este sistema SELL = cliente compra divisa extranjera
            # es decir la empresa la vende. currency_from=divisa extranjera, currency_to=BOB
            if from_cur.code != 'BOB':
                pos, _ = CurrencyPosition.objects.select_for_update().get_or_create(
                    branch=branch, currency=from_cur,
                    defaults={'avg_acquisition_cost': tx.exchange_rate},
                )
                pos.apply_sell(
                    amount=Decimal(str(tx.amount_from)),
                    rate_bob=tx.exchange_rate,
                )
                pos.save(update_fields=[
                    'net_position', 'total_sold', 'total_cost_bob',
                    'last_tx_at', 'updated_at',
                ])

    # Invalidar caché de posición y KPIs
    try:
        CapitalPositionService().invalidate(branch.pk)
        from capital.metrics import CapitalKPIService
        CapitalKPIService().invalidate(branch.pk)
    except Exception as exc:
        log.debug('POSITION_CACHE_INVALIDATE_ERR err=%s', exc)

    log.info(
        'POSITION_UPDATED tx=%s type=%s cur=%s branch=%s',
        tx.transaction_number, tx.transaction_type,
        from_cur.code, branch.pk,
    )

    # Emitir evento WebSocket
    try:
        from alerts.events import broadcast_event, CAPITAL_POSITION_UPDATED
        broadcast_event(
            CAPITAL_POSITION_UPDATED,
            {'branch_id': branch.pk, 'currency': from_cur.code},
            branch_id=branch.pk,
        )
    except Exception as exc:
        log.debug('CAPITAL_WS_BROADCAST_SKIP err=%s', exc)
