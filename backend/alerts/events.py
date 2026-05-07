"""
Sistema centralizado de eventos en tiempo real vía Django Channels.

Uso:
    from alerts.events import broadcast_event, RATE_UPDATED, TRANSACTION_CREATED

    broadcast_event(
        event_type = RATE_UPDATED,
        payload    = {'currency': 'USD', 'buy': 9.30, 'sell': 9.60},
        room       = 'rates',              # grupo global
    )

    # O por empresa/sucursal (multi-tenant):
    broadcast_event(
        event_type = TRANSACTION_CREATED,
        payload    = {'id': tx.pk, 'amount': 1000},
        company_id = tx.branch.company_id,
        branch_id  = tx.branch_id,
    )

Rooms disponibles:
  - 'rates'                    → group 'rates_updates'   (RateConsumer)
  - 'rates_live'               → group 'rates_live'      (RatesConsumer)
  - company_{id}               → group 'company_{id}'
  - branch_{id}                → group 'branch_{id}'
"""

import logging
from typing import Any

log = logging.getLogger('kapitalya.events')

# ── Tipos de eventos ──────────────────────────────────────────────────────────
RATE_UPDATED                = 'RATE_UPDATED'
TRANSACTION_CREATED         = 'TRANSACTION_CREATED'
TRANSACTION_STATUS_CHANGED  = 'TRANSACTION_STATUS_CHANGED'
CAPITAL_POSITION_UPDATED    = 'CAPITAL_POSITION_UPDATED'
INVENTORY_UPDATED           = 'INVENTORY_UPDATED'
ALERT_TRIGGERED             = 'ALERT_TRIGGERED'
KPI_UPDATED                 = 'KPI_UPDATED'
EXTRACTION_CYCLE_DONE       = 'EXTRACTION_CYCLE_DONE'

# Mapping event_type → canal WS handler name (snake_case requerido por Channels)
_EVENT_HANDLER_MAP = {
    RATE_UPDATED:               'rates_update',
    TRANSACTION_CREATED:        'transaction_event',
    TRANSACTION_STATUS_CHANGED: 'transaction_event',
    CAPITAL_POSITION_UPDATED:   'capital_update',
    INVENTORY_UPDATED:          'inventory_update',
    ALERT_TRIGGERED:            'alert_log',
    KPI_UPDATED:                'kpi_update',
    EXTRACTION_CYCLE_DONE:      'extraction_update',
}

# Mapping room alias → nombre real del group en channel layer
_ROOM_MAP = {
    'rates':      'rates_updates',
    'rates_live': 'rates_live',
    'alerts':     'rates_updates',   # AlertConsumer también escucha rates_updates
}


def _group_name(room: str | None, company_id=None, branch_id=None) -> str:
    """Resuelve el nombre del grupo channel layer."""
    if branch_id is not None:
        return f'branch_{branch_id}'
    if company_id is not None:
        return f'company_{company_id}'
    if room and room in _ROOM_MAP:
        return _ROOM_MAP[room]
    return room or 'rates_updates'


def broadcast_event(
    event_type: str,
    payload: dict[str, Any],
    room: str | None = None,
    company_id: int | None = None,
    branch_id: int | None = None,
) -> None:
    """
    Publica un evento al grupo de Django Channels correspondiente.

    Si se especifica branch_id, se envía al grupo 'branch_{branch_id}'.
    Si se especifica company_id, se envía al grupo 'company_{company_id}'.
    Si se especifica room, se traduce via _ROOM_MAP.
    Todos son mutuamente excluyentes; branch_id tiene prioridad.

    Es seguro llamar desde código síncrono (Celery, signals Django):
    usa async_to_sync internamente.
    """
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if layer is None:
            return

        group    = _group_name(room, company_id, branch_id)
        handler  = _EVENT_HANDLER_MAP.get(event_type, 'generic_event')
        message  = {
            'type':       handler,
            'event_type': event_type,
            **payload,
        }

        async_to_sync(layer.group_send)(group, message)
        log.debug('BROADCAST event=%s group=%s', event_type, group)

    except Exception as exc:
        log.debug('BROADCAST_SKIP event=%s error=%s', event_type, exc)


def broadcast_to_company(event_type: str, payload: dict, company_id: int) -> None:
    """Atajo para eventos de empresa."""
    broadcast_event(event_type, payload, company_id=company_id)


def broadcast_to_branch(event_type: str, payload: dict, branch_id: int) -> None:
    """Atajo para eventos de sucursal."""
    broadcast_event(event_type, payload, branch_id=branch_id)
