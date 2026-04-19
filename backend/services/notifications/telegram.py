"""
services/notifications/telegram.py
-----------------------------------
Utilidad para enviar mensajes a través de un Bot de Telegram.

Configuración requerida en .env:
    TELEGRAM_BOT_TOKEN=<token del bot>
    TELEGRAM_CHAT_ID=<ID del chat o canal destino>

Uso:
    from services.notifications.telegram import send_telegram_message
    send_telegram_message("🚨 ALERTA: ...")

Fire-and-forget: cualquier error se registra en logs pero nunca
interrumpe el flujo principal que lo invocó.
"""
from __future__ import annotations

import logging
from datetime import datetime

import requests
from django.conf import settings

log = logging.getLogger('kapitalya.notifications.telegram')

_API_BASE = 'https://api.telegram.org/bot{token}/sendMessage'
_TIMEOUT  = 5  # segundos


def send_telegram_message(message: str) -> bool:
    """
    Envía *message* al chat configurado vía TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.

    Returns True si la API respondió 200, False en cualquier otro caso.
    Nunca lanza excepciones — siempre fire-and-forget.
    """
    token   = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', None)

    if not token or not chat_id:
        log.debug('TELEGRAM_SKIP — TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados')
        return False

    url = _API_BASE.format(token=token)
    payload = {
        'chat_id':    chat_id,
        'text':       message,
        'parse_mode': 'HTML',
    }

    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        if resp.status_code == 200:
            log.info('TELEGRAM_SENT chat_id=%s', chat_id)
            return True
        log.warning(
            'TELEGRAM_ERROR status=%d body=%s',
            resp.status_code, resp.text[:300],
        )
        return False
    except requests.exceptions.Timeout:
        log.warning('TELEGRAM_TIMEOUT url=%s', url)
        return False
    except Exception as exc:
        log.warning('TELEGRAM_FAIL error=%s', exc)
        return False


# ------------------------------------------------------------------ #
#  Helpers de formato para cada tipo de anomalía                       #
# ------------------------------------------------------------------ #

def _fmt_date(dt=None) -> str:
    d = dt or datetime.now()
    return d.strftime('%d/%m/%Y %H:%M')


def alert_large_transaction(
    *,
    transaction_number: str,
    transaction_type: str,
    amount: str | float,
    currency: str,
    user: str,
    dt=None,
) -> bool:
    """Alerta: transacción de monto elevado."""
    msg = (
        '🚨 <b>ALERTA — Transacción de Alto Monto</b>\n'
        f'Tipo: {transaction_type}\n'
        f'N°: {transaction_number}\n'
        f'Monto: {amount} {currency}\n'
        f'Usuario: {user}\n'
        f'Fecha: {_fmt_date(dt)}'
    )
    return send_telegram_message(msg)


def alert_failed_transaction(
    *,
    transaction_number: str,
    transaction_type: str,
    amount: str | float,
    currency: str,
    status: str,
    user: str,
    dt=None,
) -> bool:
    """Alerta: transacción cancelada o revertida."""
    msg = (
        '⚠️ <b>ALERTA — Transacción Cancelada/Revertida</b>\n'
        f'Tipo: {transaction_type}\n'
        f'Estado: {status}\n'
        f'N°: {transaction_number}\n'
        f'Monto: {amount} {currency}\n'
        f'Usuario: {user}\n'
        f'Fecha: {_fmt_date(dt)}'
    )
    return send_telegram_message(msg)


def alert_negative_inventory(
    *,
    currency: str,
    branch: str,
    balance: str | float,
    dt=None,
) -> bool:
    """Alerta: inventario con saldo negativo."""
    msg = (
        '🚨 <b>ALERTA — Inventario Negativo</b>\n'
        f'Tipo: INVENTARIO_NEGATIVO\n'
        f'Moneda: {currency}\n'
        f'Sucursal: {branch}\n'
        f'Balance: {balance}\n'
        f'Fecha: {_fmt_date(dt)}'
    )
    return send_telegram_message(msg)


def alert_inventory_critical(
    *,
    alert_type: str,
    currency: str,
    branch: str,
    severity: str,
    message: str,
    dt=None,
) -> bool:
    """Alerta: alerta de inventario HIGH/CRITICAL."""
    icon = '🚨' if severity == 'CRITICAL' else '⚠️'
    msg = (
        f'{icon} <b>ALERTA — Inventario {severity}</b>\n'
        f'Tipo: {alert_type}\n'
        f'Moneda: {currency}\n'
        f'Sucursal: {branch}\n'
        f'Detalle: {message}\n'
        f'Fecha: {_fmt_date(dt)}'
    )
    return send_telegram_message(msg)


def alert_suspicious_rate(
    *,
    currency: str,
    market: str,
    previous: float,
    new: float,
    pct_change: float,
    dt=None,
) -> bool:
    """Alerta: variación sospechosa en tipo de cambio."""
    direction = 'subió' if pct_change > 0 else 'bajó'
    msg = (
        '📈 <b>ALERTA — Variación Sospechosa de Tipo de Cambio</b>\n'
        f'Tipo: TASA_SOSPECHOSA\n'
        f'Moneda: {currency} ({market})\n'
        f'Monto: {previous:.4f} → {new:.4f}\n'
        f'Cambio: {direction} {abs(pct_change):.1f}%\n'
        f'Usuario: Sistema\n'
        f'Fecha: {_fmt_date(dt)}'
    )
    return send_telegram_message(msg)
