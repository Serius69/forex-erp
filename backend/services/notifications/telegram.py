"""Notificaciones salientes por Telegram — best-effort, NUNCA lanza.

Este módulo es el destino que ya importan `rates/tasks.py`,
`transactions/signals.py` e `inventory/alerts.py`.

Credenciales (settings o entorno): ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``.

Formato: se envía con parse_mode **HTML** (más robusto que Markdown con datos
dinámicos). Los títulos/etiquetas van en <b>negrita</b> y los datos tabulares en
bloques monoespaciados <pre> (columnas alineadas = "tabla" legible en Telegram).
Todo valor dinámico se escapa con html.escape para no romper el parseo.
"""
from __future__ import annotations

import html
import logging
import os

logger = logging.getLogger("kapitalya.telegram")

_TELEGRAM_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT_S = 10.0

_MARKET_ABBR = {
    "paralelo_digital": "digital",
    "paralelo_fisico_competencia": "comp.",
    "paralelo_fisico_empresa": "empresa",
    "parallel": "paralelo",
    "official": "oficial",
}
_FIELD_ES = {"buy": "compra", "sell": "venta"}


def _creds() -> tuple[str, str]:
    token = chat_id = ""
    try:
        from django.conf import settings
        token = (getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "").strip()
        chat_id = (getattr(settings, "TELEGRAM_CHAT_ID", "") or "").strip()
    except Exception:
        pass
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not chat_id:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return token, chat_id


def telegram_configured() -> bool:
    token, chat_id = _creds()
    return bool(token and chat_id)


def _esc(v) -> str:
    """Escapa un valor para HTML de Telegram."""
    return html.escape(str(v), quote=False)


def _mono_table(headers: list[str], rows: list[list[str]]) -> str:
    """Arma una tabla monoespaciada dentro de <pre> con columnas alineadas."""
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]

    def _fmt(cells):
        # Números (col ≥ 2) alineados a la derecha; texto a la izquierda.
        out = []
        for i, cell in enumerate(cells):
            s = str(cell)
            out.append(s.rjust(widths[i]) if i >= 2 else s.ljust(widths[i]))
        return "  ".join(out).rstrip()

    lines = [_fmt(headers)] + [_fmt(r) for r in rows]
    body = _esc("\n".join(lines))
    return f"<pre>{body}</pre>"


def send_telegram(text: str, *, chat_id: str | None = None) -> bool:
    """Manda ``text`` (HTML de Telegram) al chat configurado. Best-effort."""
    token, default_chat = _creds()
    chat = (chat_id or default_chat).strip()
    if not token or not chat:
        logger.info("Telegram no configurado; alerta no enviada: %.120s", text.replace("\n", " "))
        return False
    try:
        import httpx

        resp = httpx.post(
            _TELEGRAM_SEND_URL.format(token=token),
            json={
                "chat_id": chat,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=_TIMEOUT_S,
        )
        if resp.status_code == 200 and resp.json().get("ok") is True:
            return True
        logger.warning("Telegram rechazó el mensaje: HTTP %s — %.200s", resp.status_code, resp.text)
        return False
    except Exception as exc:  # noqa: BLE001 — best-effort por contrato
        logger.warning("Fallo enviando a Telegram: %s", exc)
        return False


# ── Alertas específicas que el resto del backend ya importa ──────────────────

def alert_suspicious_rate(currency, market, previous, new, pct_change) -> bool:
    """Variación significativa (>5%) o tasa INFERENCE detectada en las tasas."""
    rows = []
    if previous is not None:
        rows.append(["Antes", f"{previous:.4f}"])
    rows.append(["Ahora", f"{new:.4f}"])
    if pct_change is not None:
        rows.append(["Cambio", f"{pct_change:+.1f}%"])
    table = _mono_table(["Dato", "Valor"], rows)
    text = (
        f"⚠️ <b>Variación fuerte de tasa</b>\n"
        f"{_esc(currency)} · {_esc(_MARKET_ABBR.get(market, market))} (BOB)\n"
        f"{table}"
    )
    return send_telegram(text)


def alert_large_transaction(transaction_number, transaction_type, amount, currency, user, dt) -> bool:
    """Transacción de alto monto (≥ LARGE_TX_THRESHOLD_BOB)."""
    rows = [
        ["N.º", str(transaction_number)],
        ["Tipo", str(transaction_type)],
        ["Monto", f"{amount} {currency}"],
        ["Cajero", str(user)],
    ]
    if dt:
        rows.append(["Fecha", _fmt_dt(dt)])
    text = f"💰 <b>Transacción de alto monto</b>\n{_mono_table(['Campo', 'Valor'], rows)}"
    return send_telegram(text)


def alert_failed_transaction(transaction_number, transaction_type, amount, currency, status, user, dt) -> bool:
    """Transacción cancelada / revertida."""
    rows = [
        ["N.º", str(transaction_number)],
        ["Tipo", str(transaction_type)],
        ["Monto", f"{amount} {currency}"],
        ["Estado", str(status)],
        ["Cajero", str(user)],
    ]
    if dt:
        rows.append(["Fecha", _fmt_dt(dt)])
    text = f"🚫 <b>Transacción {_esc(status)}</b>\n{_mono_table(['Campo', 'Valor'], rows)}"
    return send_telegram(text)


def alert_inventory_critical(alert_type, currency, branch, severity, message) -> bool:
    """Alerta de inventario de severidad HIGH / CRITICAL."""
    icon = "🔴" if str(severity).upper() == "CRITICAL" else "🟠"
    rows = [
        ["Tipo", str(alert_type)],
        ["Divisa", str(currency)],
        ["Sucursal", str(branch)],
    ]
    text = (
        f"{icon} <b>Inventario {_esc(severity)}</b>\n"
        f"{_mono_table(['Campo', 'Valor'], rows)}\n"
        f"{_esc(message)}"
    )
    return send_telegram(text)


def alert_negative_inventory(currency, branch, balance) -> bool:
    """Saldo de inventario negativo (físico o digital)."""
    rows = [
        ["Divisa", str(currency)],
        ["Sucursal", str(branch)],
        ["Saldo", str(balance)],
    ]
    text = f"🔴 <b>Inventario NEGATIVO</b>\n{_mono_table(['Campo', 'Valor'], rows)}"
    return send_telegram(text)


# ── Digest de cambios de tasa (tabla) ────────────────────────────────────────

def alert_rate_changes(changes: list[dict]) -> bool:
    """Digest en TABLA de los cambios de tasa que cruzaron el umbral."""
    if not changes:
        return False
    rows = []
    for c in changes[:30]:
        pct = ((c["new"] - c["old"]) / c["old"] * 100) if c["old"] else 0.0
        arrow = "▲" if c["new"] >= c["old"] else "▼"
        rows.append([
            c["code"],
            _MARKET_ABBR.get(c["market"], str(c["market"])[:8]),
            _FIELD_ES.get(c["field"], c["field"]),
            f"{c['old']:.4f}",
            f"{c['new']:.4f}",
            f"{arrow}{pct:+.2f}%",
        ])
    table = _mono_table(["Div", "Merc", "Campo", "Antes", "Ahora", "Δ%"], rows)
    extra = f"\n… y {len(changes) - 30} más" if len(changes) > 30 else ""
    return send_telegram(f"📊 <b>Tasas actualizadas · forex-erp</b>\n{table}{extra}")


def _fmt_dt(dt) -> str:
    if not dt:
        return ""
    try:
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""
