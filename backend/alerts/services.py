"""
GlobalAlertService — punto de entrada único para emitir alertas en Kapitalya.

Responsabilidades
-----------------
1. Persiste la alerta en AlertLog (PostgreSQL).
2. Emite `alert_log` por WebSocket al grupo `rates_updates` (todos los clientes).
3. Delega a SystemAlert.create() para mantener compatibilidad con el cache Redis.
4. Registra en el logger correspondiente a la severidad.

Diseño de resiliencia
---------------------
- Nunca propaga excepciones. Un fallo en el alerting no rompe el sistema principal.
- Cada paso (DB, WS, cache) falla de forma independiente.
- Retorna None en lugar de lanzar si ocurre cualquier error.

Normalización de severidad
--------------------------
Los distintos subsistemas usan terminología diferente:
  snapshots/alerts.py  : CRITICAL, WARNING, INFO
  analytics/services.py: CRITICAL, WARNING
  core/alerts.py       : CRITICAL, HIGH, MEDIUM, LOW

El GlobalAlertService acepta todos y normaliza a CRITICAL / HIGH / MEDIUM / LOW.
"""
from __future__ import annotations

import logging
import statistics
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

log = logging.getLogger('kapitalya.alerts')

# Mapa de normalización para severidades externas → modelo interno
_SEV_NORMALIZE: dict[str, str] = {
    'CRITICAL': 'CRITICAL',
    'HIGH':     'HIGH',
    'WARNING':  'HIGH',    # snapshots y analytics usan WARNING → HIGH
    'MEDIUM':   'MEDIUM',
    'LOW':      'LOW',
    'INFO':     'LOW',     # snapshots usa INFO → LOW
}


class GlobalAlertService:
    """
    Interfaz estática para crear alertas desde cualquier parte del sistema.
    """

    @staticmethod
    def emit(
        source:          str,
        alert_type:      str,
        severity:        str,
        title:           str,
        message:         str,
        data:            dict | None = None,
        branch                       = None,
        triggered_by                 = None,
        accion_sugerida: str         = '',
    ) -> Optional['alerts.models.AlertLog']:
        """
        Crea y propaga una alerta global.

        Parameters
        ----------
        source      : una de AlertLog.SOURCE_* (SNAPSHOT, TRANSACTION, …)
        alert_type  : tipo específico, ej. LOSS_DETECTED, CAPITAL_DROP
        severity    : CRITICAL | HIGH | WARNING | MEDIUM | LOW | INFO
        title       : título corto para la UI (≤200 chars)
        message     : descripción completa del evento
        data        : dict con contexto adicional (deltas, valores, umbrales)
        branch      : instancia Branch o None para alertas globales
        triggered_by: instancia User o None

        Returns
        -------
        AlertLog creado, o None si falló la persistencia.
        """
        severity_norm = _SEV_NORMALIZE.get(severity.upper(), 'MEDIUM')

        alert_log = GlobalAlertService._persist(
            source, alert_type, severity_norm, title, message,
            data or {}, branch, triggered_by, accion_sugerida,
        )

        GlobalAlertService._push_websocket(alert_log, severity_norm, title, message, source)
        GlobalAlertService._push_system_cache(source, message, severity_norm)
        GlobalAlertService._send_email(severity_norm, title, message, source, alert_type)
        GlobalAlertService._log(severity_norm, source, alert_type, message)

        return alert_log

    # ── Paso 1: persistir en BD ──────────────────────────────────────────────

    @staticmethod
    def _persist(source, alert_type, severity, title, message,
                 data, branch, triggered_by,
                 accion_sugerida='') -> Optional['alerts.models.AlertLog']:
        try:
            from alerts.models import AlertLog
            return AlertLog.objects.create(
                source          = source,
                alert_type      = alert_type,
                severity        = severity,
                title           = title,
                message         = message,
                accion_sugerida = accion_sugerida or '',
                data            = data,
                branch          = branch,
                triggered_by    = triggered_by,
            )
        except Exception as exc:
            log.error('ALERT_PERSIST_FAILED src=%s type=%s err=%s', source, alert_type, exc)
            return None

    # ── Paso 2: emitir por WebSocket ─────────────────────────────────────────

    @staticmethod
    def _push_websocket(alert_log, severity, title, message, source):
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            layer = get_channel_layer()
            if layer is None:
                return

            payload = {
                'type':       'alert_log',          # → RateConsumer.alert_log()
                'alert': {
                    'id':         str(alert_log.id) if alert_log else None,
                    'source':     source,
                    'severity':   severity,
                    'title':      title,
                    'message':    message,
                    'created_at': alert_log.created_at.isoformat() if alert_log else None,
                },
            }
            async_to_sync(layer.group_send)('rates_updates', payload)
        except Exception as exc:
            log.debug('ALERT_WS_FAILED err=%s', exc)

    # ── Paso 3: compatibilidad cache Redis ───────────────────────────────────

    @staticmethod
    def _push_system_cache(source, message, severity):
        try:
            from core.alerts import SystemAlert
            SystemAlert.create(component=source.lower(), message=message, severity=severity)
        except Exception as exc:
            log.debug('ALERT_CACHE_FAILED err=%s', exc)

    # ── Paso 4: email para alertas CRITICAL/HIGH ─────────────────────────────

    @staticmethod
    def _send_email(severity: str, title: str, message: str, source: str, alert_type: str) -> None:
        if severity not in ('CRITICAL', 'HIGH'):
            return
        try:
            from django.conf import settings as djset
            from django.core.mail import send_mail

            recipients = getattr(djset, 'ALERT_EMAIL_RECIPIENTS', [])
            if not recipients:
                return

            severity_label = '🔴 CRÍTICO' if severity == 'CRITICAL' else '🟠 ALTO'
            subject = f'[Kapitalya] {severity_label}: {title}'
            body = (
                f'Se ha generado una alerta {severity_label} en Kapitalya ERP.\n\n'
                f'Fuente : {source}\n'
                f'Tipo   : {alert_type}\n'
                f'Título : {title}\n\n'
                f'Detalle:\n{message}\n\n'
                f'-- Kapitalya Sistema Financiero --'
            )
            send_mail(
                subject,
                body,
                djset.DEFAULT_FROM_EMAIL,
                recipients,
                fail_silently=True,
            )
        except Exception as exc:
            log.debug('ALERT_EMAIL_FAILED err=%s', exc)

    # ── Paso 5: logger ───────────────────────────────────────────────────────

    @staticmethod
    def _log(severity, source, alert_type, message):
        msg = 'ALERT src=%s type=%s msg=%s', source, alert_type, message
        if severity == 'CRITICAL':
            log.critical(*msg)
        elif severity == 'HIGH':
            log.error(*msg)
        elif severity == 'MEDIUM':
            log.warning(*msg)
        else:
            log.info(*msg)

    # ── Helpers de fuente específica ─────────────────────────────────────────

    @staticmethod
    def from_snapshot_alert(snap_alert: dict, branch=None) -> Optional['alerts.models.AlertLog']:
        """
        Convierte una alerta de AlertEngine (snapshots/alerts.py) al sistema global.

        snap_alert viene con keys: type, severity, message + extras de contexto.
        """
        TITLE_MAP = {
            'LOSS_DETECTED':      'Pérdida de capital detectada',
            'NEGATIVE_BALANCE':   'Balance negativo',
            'INVENTORY_MISMATCH': 'Discrepancia de inventario',
            'SUDDEN_SPIKE':       'Spike súbito de capital',
            'EFECTIVO_DROP':      'Caída de efectivo',
            'CURRENCY_DROP':      'Caída de stock de divisa',
            'INTEGRITY_FAILURE':  'Fallo de integridad SHA-256',
        }
        alert_type = snap_alert.get('type', 'UNKNOWN')
        return GlobalAlertService.emit(
            source     = 'SNAPSHOT',
            alert_type = alert_type,
            severity   = snap_alert.get('severity', 'HIGH'),
            title      = TITLE_MAP.get(alert_type, alert_type.replace('_', ' ').title()),
            message    = snap_alert.get('message', ''),
            data       = {k: v for k, v in snap_alert.items()
                          if k not in ('type', 'severity', 'message')},
            branch     = branch,
        )

    @staticmethod
    def from_anomaly(anomaly: dict, branch=None) -> Optional['alerts.models.AlertLog']:
        """
        Convierte una anomalía de AnomalyDetector (analytics) al sistema global.

        anomaly viene con keys: rule, severity, description, currency?, value?, threshold?
        """
        TITLE_MAP = {
            'CAPITAL_DROP':      'Caída de capital',
            'MISSING_CASH':      'Discrepancia de caja',
            'NEGATIVE_BALANCE':  'Balance negativo',
            'RATE_INVERTED':     'Tasa invertida (spread negativo)',
            'RATE_STALE':        'Tasa sin actualizar',
            'RATE_BCB_DEVIATION':'Desviación sobre tasa BCB',
            'SPREAD_BELOW_MIN':  'Spread por debajo del mínimo',
            'EXPOSURE_HIGH':     'Alta concentración de divisa',
        }
        rule = anomaly.get('rule', 'UNKNOWN')
        return GlobalAlertService.emit(
            source     = 'ANOMALY',
            alert_type = rule,
            severity   = anomaly.get('severity', 'HIGH'),
            title      = TITLE_MAP.get(rule, rule.replace('_', ' ').title()),
            message    = anomaly.get('description', ''),
            data       = {k: v for k, v in anomaly.items()
                          if k not in ('rule', 'severity', 'description')},
            branch     = branch,
        )

    @staticmethod
    def from_system(component: str, message: str, severity: str = 'HIGH',
                    details: dict = None) -> Optional['alerts.models.AlertLog']:
        """Wrapper para alertas de infraestructura del sistema."""
        TITLE_MAP = {
            'db':           'Error de base de datos',
            'celery':       'Error en Celery',
            'ml':           'Error en modelos ML',
            'rates':        'Error de tasas de cambio',
            'security':     'Alerta de seguridad',
            'transactions': 'Anomalía en transacciones',
            'health':       'Fallo de salud del sistema',
            'backup':       'Error en backup',
        }
        return GlobalAlertService.emit(
            source     = 'SYSTEM',
            alert_type = component.upper(),
            severity   = severity,
            title      = TITLE_MAP.get(component, f'Error en {component}'),
            message    = message,
            data       = details or {},
        )


# ─────────────────────────────────────────────────────────────────────────────
# AlertGenerator — motor de alertas inteligentes y accionables
# ─────────────────────────────────────────────────────────────────────────────

class AlertGenerator:
    """
    Genera alertas inteligentes, priorizadas y accionables para la UI del operador.

    Categorías
    ----------
    PRECIO      — Binance/digital subió/bajó >2%; competencia cambió precios
    INVENTORY   — Stock bajo (necesita reposición) o sobre-stock (capital inmovilizado)
    RIESGO      — Volatilidad alta (>1.5% std dev 2h); spread por debajo del mínimo
    OPERATIVO   — Volumen inusual de transacciones INTERNA; descuadre de caja
    OPORTUNIDAD — Diferencial Binance vs empresa >1.5%; oportunidad de arbitraje

    Salida por alerta
    -----------------
    {
      'tipo':            str,   # PRECIO | INVENTORY | RIESGO | OPERATIVO | OPORTUNIDAD
      'nivel':           str,   # INFO | WARNING | CRITICAL
      'mensaje':         str,
      'accion_sugerida': str,
      'moneda':          str,   # código divisa o vacío para alertas globales
      'timestamp':       str,   # ISO 8601
    }

    Deduplicación
    -------------
    Cada (tipo, alert_type, branch, currency) se suprime durante 30 minutos en cache.
    Evita inundar la UI cuando tasas/transacciones actualizan frecuentemente.
    """

    # ── Umbrales (ajustables vía settings) ────────────────────────────────────
    PRECIO_MOVE_WARNING_PCT  = Decimal('2.0')   # >2% en 1h → WARNING
    PRECIO_MOVE_CRITICAL_PCT = Decimal('4.0')   # >4% en 1h → CRITICAL
    COMP_DIFF_WARNING_PCT    = Decimal('1.5')   # >1.5% vs competencia → INFO
    VOLATILITY_WARNING_PCT   = Decimal('1.5')   # std dev >1.5% en 2h → WARNING
    VOLATILITY_CRITICAL_PCT  = Decimal('3.0')   # std dev >3.0% en 2h → CRITICAL
    SPREAD_MIN_PCT           = Decimal('0.30')  # spread mínimo rentable
    SPREAD_WARN_MULT         = Decimal('1.5')   # <1.5× el mínimo → WARNING
    INTERNA_TX_WARNING       = 8                # >8 tx internas/h → WARNING
    INTERNA_TX_CRITICAL      = 20               # >20 tx internas/h → CRITICAL
    OPORTUNIDAD_UMBRAL_PCT   = Decimal('1.5')   # diferencial >1.5% → INFO
    COMPRA_PRIMA_MAX_PCT     = Decimal('2.0')   # compramos >2% sobre digital → WARNING
    DEDUP_MINUTES            = 30               # ventana sin duplicados

    # ── Constantes de fuente ──────────────────────────────────────────────────
    SRC_PRECIO      = 'PRECIO'
    SRC_INVENTARIO  = 'INVENTORY'
    SRC_RIESGO      = 'RIESGO'
    SRC_OPERATIVO   = 'OPERATIVO'
    SRC_OPORTUNIDAD = 'OPORTUNIDAD'

    # ── Mapa nivel → severidad AlertLog ──────────────────────────────────────
    _NIVEL_TO_SEV = {'CRITICAL': 'CRITICAL', 'WARNING': 'HIGH', 'INFO': 'LOW'}

    # ═════════════════════════════════════════════════════════════════════════
    # API principal
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    def generar_alertas(cls, branch, currency: str = None) -> list[dict]:
        """
        Evalúa todas las categorías y retorna lista de alertas accionables.
        También persiste y emite cada alerta vía GlobalAlertService (BD + WebSocket).

        Args:
            branch:   Branch instance — requerido para inventario/capital
            currency: código de divisa específica, o None para todas las activas

        Returns:
            list[dict] con keys: tipo, nivel, mensaje, accion_sugerida, moneda, timestamp
        """
        resultado: list[dict] = []

        currencies = [currency] if currency else cls._get_active_currencies(branch)

        for cur in currencies:
            resultado.extend(cls._alertas_precio(branch, cur))
            resultado.extend(cls._alertas_inventario(branch, cur))
            resultado.extend(cls._alertas_riesgo(branch, cur))
            resultado.extend(cls._alertas_oportunidad(branch, cur))

        resultado.extend(cls._alertas_operativo(branch))

        # Ordenar: CRITICAL primero, INFO último
        _ord = {'CRITICAL': 0, 'WARNING': 1, 'INFO': 2}
        resultado.sort(key=lambda a: _ord.get(a.get('nivel', 'INFO'), 2))

        return resultado

    # ═════════════════════════════════════════════════════════════════════════
    # Infraestructura interna
    # ═════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_active_currencies(branch) -> list[str]:
        """Retorna códigos de divisas con inventario activo en la sucursal."""
        try:
            from inventory.models import CurrencyInventory
            return list(
                CurrencyInventory.objects
                .filter(branch=branch)
                .exclude(currency__code='BOB')
                .values_list('currency__code', flat=True)
            )
        except Exception:
            return []

    @staticmethod
    def _is_dup(source: str, alert_type: str, branch, currency: str = '') -> bool:
        try:
            from django.core.cache import cache
            branch_id = getattr(branch, 'id', 0) or 0
            return bool(cache.get(f'algen:{source}:{alert_type}:{branch_id}:{currency}'))
        except Exception:
            return False

    @classmethod
    def _mark_dup(cls, source: str, alert_type: str, branch, currency: str = '') -> None:
        try:
            from django.core.cache import cache
            branch_id = getattr(branch, 'id', 0) or 0
            cache.set(
                f'algen:{source}:{alert_type}:{branch_id}:{currency}',
                1,
                timeout=cls.DEDUP_MINUTES * 60,
            )
        except Exception:
            pass

    @classmethod
    def _emit(cls, tipo: str, nivel: str, mensaje: str, accion: str,
              branch, currency: str = '', data: dict = None) -> dict | None:
        """
        Deduplica, persiste y emite una alerta.
        Retorna el dict de alerta o None si es duplicado.
        """
        alert_type = f'{tipo}_{currency}' if currency else tipo
        if cls._is_dup(tipo, alert_type, branch, currency):
            return None

        cls._mark_dup(tipo, alert_type, branch, currency)

        severity = cls._NIVEL_TO_SEV.get(nivel.upper(), 'MEDIUM')
        try:
            GlobalAlertService.emit(
                source          = tipo,
                alert_type      = alert_type,
                severity        = severity,
                title           = mensaje[:100],
                message         = mensaje,
                accion_sugerida = accion,
                data            = data or {},
                branch          = branch,
            )
        except Exception as exc:
            log.debug('ALERT_GEN_EMIT_FAIL tipo=%s err=%s', tipo, exc)

        from django.utils import timezone as _tz
        return {
            'tipo':            tipo,
            'nivel':           nivel.upper(),
            'mensaje':         mensaje,
            'accion_sugerida': accion,
            'moneda':          currency,
            'timestamp':       _tz.now().isoformat(),
        }

    # ═════════════════════════════════════════════════════════════════════════
    # 1. PRECIO — movimiento en Binance/digital + comparación con competencia
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    def _alertas_precio(cls, branch, currency: str) -> list[dict]:
        alertas = []
        try:
            from rates.models import ExchangeRate
            from analytics.models import SpreadSnapshot
            from django.utils import timezone as _tz
            from datetime import timedelta

            # Tasa activa con mayor prioridad de mercado
            tasas = {
                t.market_type: t
                for t in ExchangeRate.objects
                .filter(currency_from__code=currency, valid_until__isnull=True)
                .select_related('currency_from')
            }
            tasa = (
                tasas.get('paralelo_fisico_empresa')
                or tasas.get('parallel')
                or tasas.get('digital')
            )
            if not tasa:
                return alertas

            scale        = Decimal(str(tasa.currency_from.scale_factor or 1))
            sell_actual  = Decimal(str(tasa.sell_rate)) / scale

            # ── Movimiento vs hace 1h ──────────────────────────────────────
            snap_1h = (
                SpreadSnapshot.objects
                .filter(
                    currency_code=currency,
                    market_type=tasa.market_type,
                    timestamp__lte=_tz.now() - timedelta(hours=1),
                )
                .order_by('-timestamp')
                .first()
            )
            if snap_1h and Decimal(str(snap_1h.sell_rate or 0)) > 0:
                sell_prev = Decimal(str(snap_1h.sell_rate)) / scale
                delta_pct = abs((sell_actual - sell_prev) / sell_prev * 100)
                sube      = sell_actual > sell_prev
                dir_txt   = 'subió' if sube else 'bajó'

                if delta_pct >= cls.PRECIO_MOVE_CRITICAL_PCT:
                    nivel  = 'CRITICAL'
                    accion = (
                        f'Ajustar precio de {"venta" if sube else "compra"} '
                        f'{currency} al menos {float(delta_pct):.1f}% '
                        f'para reflejar el mercado'
                    )
                elif delta_pct >= cls.PRECIO_MOVE_WARNING_PCT:
                    nivel  = 'WARNING'
                    accion = (
                        f'Revisar tasas {currency}: mercado {dir_txt} '
                        f'{float(delta_pct):.1f}% en 1h'
                    )
                else:
                    nivel = None

                if nivel:
                    a = cls._emit(
                        tipo     = cls.SRC_PRECIO,
                        nivel    = nivel,
                        mensaje  = (
                            f'{currency} (Binance/digital) {dir_txt} '
                            f'{float(delta_pct):.2f}% en la última hora '
                            f'({float(sell_prev):.4f} → {float(sell_actual):.4f})'
                        ),
                        accion   = accion,
                        branch   = branch,
                        currency = currency,
                        data     = {
                            'sell_prev':   str(sell_prev),
                            'sell_actual': str(sell_actual),
                            'delta_pct':   str(delta_pct),
                            'market_type': tasa.market_type,
                        },
                    )
                    if a:
                        alertas.append(a)

            # ── Comparación vs competencia ─────────────────────────────────
            mt_comp = 'parallel' if tasa.market_type != 'parallel' else 'paralelo_fisico_empresa'
            tasa_comp = tasas.get(mt_comp)
            if tasa_comp:
                sell_comp = Decimal(str(tasa_comp.sell_rate)) / scale
                if sell_comp > 0:
                    diff_pct = (sell_actual - sell_comp) / sell_comp * 100
                    if abs(diff_pct) >= cls.COMP_DIFF_WARNING_PCT:
                        if diff_pct > 0:
                            msg    = (
                                f'Nuestro precio de venta {currency} '
                                f'({float(sell_actual):.4f}) es {float(diff_pct):.1f}% '
                                f'mayor que la competencia ({float(sell_comp):.4f})'
                            )
                            accion = (
                                f'Evaluar reducir precio de venta {currency} '
                                f'para no perder clientes frente al mercado'
                            )
                        else:
                            msg    = (
                                f'Nuestro precio de venta {currency} '
                                f'({float(sell_actual):.4f}) es {float(abs(diff_pct)):.1f}% '
                                f'menor que la competencia ({float(sell_comp):.4f})'
                            )
                            accion = (
                                f'Se puede subir precio de venta {currency} '
                                f'hasta {float(sell_comp):.4f} sin perder competitividad'
                            )
                        a = cls._emit(
                            tipo     = cls.SRC_PRECIO,
                            nivel    = 'INFO',
                            mensaje  = msg,
                            accion   = accion,
                            branch   = branch,
                            currency = f'{currency}_comp',
                            data     = {
                                'sell_empresa': str(sell_actual),
                                'sell_comp':    str(sell_comp),
                                'diff_pct':     str(diff_pct),
                            },
                        )
                        if a:
                            alertas.append(a)

        except Exception as exc:
            log.debug('ALERT_PRECIO cur=%s err=%s', currency, exc)
        return alertas

    # ═════════════════════════════════════════════════════════════════════════
    # 2. INVENTARIO — stock bajo o sobre-stock
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    def _alertas_inventario(cls, branch, currency: str) -> list[dict]:
        alertas = []
        try:
            from inventory.models import CurrencyInventory
            inv     = CurrencyInventory.objects.get(currency__code=currency, branch=branch)
            stock   = Decimal(str(inv.total_balance))
            reorder = Decimal(str(inv.reorder_point))
            maximum = Decimal(str(inv.maximum_stock))

            if inv.needs_replenishment:
                if reorder > 0 and stock < reorder * Decimal('0.5'):
                    nivel  = 'CRITICAL'
                    accion = (
                        f'Comprar {currency} de inmediato: '
                        f'se necesitan al menos {float(max(Decimal("0"), reorder - stock)):.2f} unidades'
                    )
                else:
                    nivel  = 'WARNING'
                    accion = (
                        f'Reponer {currency}: '
                        f'{float(max(Decimal("0"), reorder - stock)):.2f} unidades adicionales'
                    )
                a = cls._emit(
                    tipo     = cls.SRC_INVENTARIO,
                    nivel    = nivel,
                    mensaje  = (
                        f'Stock {"crítico" if nivel == "CRITICAL" else "bajo"} de {currency}: '
                        f'{float(stock):.2f} '
                        f'(punto de reorden: {float(reorder):.2f})'
                    ),
                    accion   = accion,
                    branch   = branch,
                    currency = currency,
                    data     = {
                        'stock':   str(stock),
                        'reorder': str(reorder),
                        'deficit': str(max(Decimal('0'), reorder - stock)),
                    },
                )
                if a:
                    alertas.append(a)

            elif inv.is_overstocked:
                wac               = Decimal(str(inv.weighted_average_cost or 0))
                capital_inmov     = stock * wac
                exceso            = stock - maximum
                a = cls._emit(
                    tipo     = cls.SRC_INVENTARIO,
                    nivel    = 'INFO',
                    mensaje  = (
                        f'Sobre-stock de {currency}: '
                        f'{float(stock):.2f} (máximo: {float(maximum):.2f}) — '
                        f'capital inmovilizado aprox. Bs {float(capital_inmov):,.0f}'
                    ),
                    accion   = (
                        f'Bajar precio de venta {currency} para rotar stock — '
                        f'objetivo reducir {float(exceso):.2f} unidades'
                    ),
                    branch   = branch,
                    currency = currency,
                    data     = {
                        'stock':          str(stock),
                        'maximum':        str(maximum),
                        'exceso':         str(exceso),
                        'capital_inmov':  str(capital_inmov),
                    },
                )
                if a:
                    alertas.append(a)

        except Exception as exc:
            log.debug('ALERT_INVENTARIO cur=%s err=%s', currency, exc)
        return alertas

    # ═════════════════════════════════════════════════════════════════════════
    # 3. RIESGO — volatilidad alta + spread insuficiente
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    def _alertas_riesgo(cls, branch, currency: str) -> list[dict]:
        alertas = []
        try:
            from analytics.models import SpreadSnapshot
            from django.utils import timezone as _tz
            from datetime import timedelta

            snaps = list(
                SpreadSnapshot.objects
                .filter(
                    currency_code=currency,
                    timestamp__gte=_tz.now() - timedelta(hours=2),
                )
                .order_by('timestamp')
                .values_list('sell_rate', 'spread_pct')
            )
            if len(snaps) < 3:
                return alertas

            sell_rates  = [float(r[0]) for r in snaps if r[0]]
            spread_vals = [Decimal(str(r[1])) for r in snaps if r[1] is not None]

            # ── Volatilidad ────────────────────────────────────────────────
            if len(sell_rates) >= 3:
                mean_rate = statistics.mean(sell_rates)
                if mean_rate > 0:
                    std_dev   = statistics.stdev(sell_rates)
                    vol_pct   = Decimal(str(std_dev / mean_rate * 100))

                    if vol_pct >= cls.VOLATILITY_CRITICAL_PCT:
                        nivel  = 'CRITICAL'
                        accion = (
                            f'Reducir exposición {currency}: volatilidad '
                            f'{float(vol_pct):.1f}% — ampliar spread y limitar montos'
                        )
                    elif vol_pct >= cls.VOLATILITY_WARNING_PCT:
                        nivel  = 'WARNING'
                        accion = (
                            f'Monitorear {currency}: volatilidad {float(vol_pct):.1f}% — '
                            f'considerar ampliar spread preventivamente'
                        )
                    else:
                        nivel = None

                    if nivel:
                        a = cls._emit(
                            tipo     = cls.SRC_RIESGO,
                            nivel    = nivel,
                            mensaje  = (
                                f'Alta volatilidad en {currency}: '
                                f'{float(vol_pct):.2f}% (std dev 2h, '
                                f'{len(sell_rates)} puntos)'
                            ),
                            accion   = accion,
                            branch   = branch,
                            currency = currency,
                            data     = {
                                'volatilidad_pct': str(vol_pct),
                                'snapshots_2h':    len(sell_rates),
                            },
                        )
                        if a:
                            alertas.append(a)

            # ── Spread insuficiente ────────────────────────────────────────
            if spread_vals:
                spread_actual = spread_vals[-1]
                warn_floor    = cls.SPREAD_MIN_PCT * cls.SPREAD_WARN_MULT

                if spread_actual < cls.SPREAD_MIN_PCT:
                    a = cls._emit(
                        tipo     = cls.SRC_RIESGO,
                        nivel    = 'CRITICAL',
                        mensaje  = (
                            f'Spread {currency} bajo mínimo rentable: '
                            f'{float(spread_actual):.4f}% '
                            f'(mínimo: {float(cls.SPREAD_MIN_PCT):.2f}%)'
                        ),
                        accion   = (
                            f'Corregir tasas {currency}: '
                            f'aumentar spread a ≥{float(cls.SPREAD_MIN_PCT):.2f}% '
                            f'para cubrir costos operativos'
                        ),
                        branch   = branch,
                        currency = f'{currency}_spread',
                        data     = {
                            'spread_actual': str(spread_actual),
                            'spread_min':    str(cls.SPREAD_MIN_PCT),
                        },
                    )
                    if a:
                        alertas.append(a)
                elif spread_actual < warn_floor:
                    a = cls._emit(
                        tipo     = cls.SRC_RIESGO,
                        nivel    = 'WARNING',
                        mensaje  = (
                            f'Spread {currency} cerca del límite: '
                            f'{float(spread_actual):.4f}% '
                            f'(recomendado: >{float(warn_floor):.2f}%)'
                        ),
                        accion   = (
                            f'Revisar tasas {currency}: spread estrecho '
                            f'reduce margen de seguridad'
                        ),
                        branch   = branch,
                        currency = f'{currency}_spread',
                        data     = {
                            'spread_actual': str(spread_actual),
                            'spread_min':    str(cls.SPREAD_MIN_PCT),
                            'warn_floor':    str(warn_floor),
                        },
                    )
                    if a:
                        alertas.append(a)

        except Exception as exc:
            log.debug('ALERT_RIESGO cur=%s err=%s', currency, exc)
        return alertas

    # ═════════════════════════════════════════════════════════════════════════
    # 4. OPERATIVO — tx internas masivas + descuadre de caja
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    def _alertas_operativo(cls, branch) -> list[dict]:
        alertas = []

        # ── Volumen de transacciones INTERNA en 1h ────────────────────────
        try:
            from transactions.models import Transaction
            from django.utils import timezone as _tz
            from datetime import timedelta

            count = Transaction.objects.filter(
                branch=branch,
                transaction_category='INTERNA',
                status='COMPLETED',
                created_at__gte=_tz.now() - timedelta(hours=1),
            ).count()

            if count >= cls.INTERNA_TX_CRITICAL:
                nivel  = 'CRITICAL'
                accion = (
                    f'Revisar de inmediato las {count} transacciones INTERNA '
                    f'registradas en la última hora — posible uso indebido'
                )
            elif count >= cls.INTERNA_TX_WARNING:
                nivel  = 'WARNING'
                accion = (
                    f'Monitorear uso del canal INTERNA: '
                    f'{count} transacciones en la última hora'
                )
            else:
                nivel = None

            if nivel:
                a = cls._emit(
                    tipo   = cls.SRC_OPERATIVO,
                    nivel  = nivel,
                    mensaje= (
                        f'Volumen inusual de transacciones INTERNA: '
                        f'{count} en la última hora'
                    ),
                    accion = accion,
                    branch = branch,
                    data   = {'count_interna': count, 'ventana_horas': 1},
                )
                if a:
                    alertas.append(a)
        except Exception as exc:
            log.debug('ALERT_OPERATIVO_TX err=%s', exc)

        # ── Descuadre de caja ─────────────────────────────────────────────
        try:
            from capital.models import CapitalComposicion, CashFlowLog
            from django.utils import timezone as _tz
            from django.db.models import Sum as _Sum

            hoy  = _tz.localdate()
            comp = CapitalComposicion.objects.filter(branch=branch, fecha=hoy).first()
            if comp:
                # Flujo neto de CashFlowLog del día
                flujo = (
                    CashFlowLog.objects
                    .filter(branch=branch, created_at__date=hoy)
                    .aggregate(total=_Sum('delta_bob'))
                )['total'] or Decimal('0')

                import datetime
                comp_ayer = CapitalComposicion.objects.filter(
                    branch=branch,
                    fecha=hoy - datetime.timedelta(days=1),
                ).first()
                saldo_ini = Decimal(str(
                    comp_ayer.total_efectivo_local() if comp_ayer else 0
                ))

                saldo_esp  = saldo_ini + flujo
                saldo_real = Decimal(str(comp.total_efectivo_local()))
                descuadre  = abs(saldo_real - saldo_esp)

                if descuadre > Decimal('500'):
                    nivel  = 'CRITICAL' if descuadre > Decimal('2000') else 'WARNING'
                    a = cls._emit(
                        tipo   = cls.SRC_OPERATIVO,
                        nivel  = nivel,
                        mensaje= (
                            f'Descuadre de caja: Bs {float(descuadre):,.2f} '
                            f'(esperado Bs {float(saldo_esp):,.2f}, '
                            f'declarado Bs {float(saldo_real):,.2f})'
                        ),
                        accion = (
                            'Realizar conteo físico de caja y reconciliar '
                            'con los registros de transacciones del día'
                        ),
                        branch = branch,
                        data   = {
                            'saldo_real':     str(saldo_real),
                            'saldo_esperado': str(saldo_esp),
                            'descuadre':      str(descuadre),
                        },
                    )
                    if a:
                        alertas.append(a)
        except Exception as exc:
            log.debug('ALERT_OPERATIVO_CAJA err=%s', exc)

        return alertas

    # ═════════════════════════════════════════════════════════════════════════
    # 5. OPORTUNIDAD — diferencial Binance/digital vs empresa
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    def _alertas_oportunidad(cls, branch, currency: str) -> list[dict]:
        alertas = []
        try:
            from rates.models import ExchangeRate

            tasa_emp = (
                ExchangeRate.objects
                .filter(
                    currency_from__code=currency,
                    valid_until__isnull=True,
                    market_type='paralelo_fisico_empresa',
                )
                .select_related('currency_from')
                .first()
            )
            tasa_dig = (
                ExchangeRate.objects
                .filter(
                    currency_from__code=currency,
                    valid_until__isnull=True,
                    market_type='digital',
                )
                .first()
            )
            if not tasa_emp or not tasa_dig:
                return alertas

            scale       = Decimal(str(tasa_emp.currency_from.scale_factor or 1))
            sell_emp    = Decimal(str(tasa_emp.sell_rate)) / scale
            buy_emp     = Decimal(str(tasa_emp.buy_rate))  / scale
            sell_dig    = Decimal(str(tasa_dig.sell_rate)) / scale

            if sell_dig <= 0:
                return alertas

            # ── Venta: digital > empresa → podemos subir precio ───────────
            dif_venta = (sell_dig - sell_emp) / sell_dig * 100
            if dif_venta >= cls.OPORTUNIDAD_UMBRAL_PCT:
                precio_sug = sell_dig * Decimal('0.99')
                a = cls._emit(
                    tipo     = cls.SRC_OPORTUNIDAD,
                    nivel    = 'INFO',
                    mensaje  = (
                        f'Oportunidad en {currency}: precio digital '
                        f'({float(sell_dig):.4f}) es {float(dif_venta):.1f}% '
                        f'mayor que nuestro precio de venta ({float(sell_emp):.4f})'
                    ),
                    accion   = (
                        f'Subir precio de venta {currency} a ≈{float(precio_sug):.4f} '
                        f'(1% bajo el digital) para capturar margen adicional'
                    ),
                    branch   = branch,
                    currency = currency,
                    data     = {
                        'sell_empresa':    str(sell_emp),
                        'sell_digital':    str(sell_dig),
                        'diferencial_pct': str(dif_venta),
                        'precio_sugerido': str(precio_sug),
                    },
                )
                if a:
                    alertas.append(a)

            # ── Compra: compramos más caro que el digital → ajustar ───────
            if buy_emp > 0:
                prima_compra = (buy_emp - sell_dig) / sell_dig * 100
                if prima_compra >= cls.COMPRA_PRIMA_MAX_PCT:
                    precio_sug = sell_dig * Decimal('1.005')
                    a = cls._emit(
                        tipo     = cls.SRC_OPORTUNIDAD,
                        nivel    = 'WARNING',
                        mensaje  = (
                            f'Compramos {currency} caro: '
                            f'nuestra compra ({float(buy_emp):.4f}) es '
                            f'{float(prima_compra):.1f}% sobre el digital '
                            f'({float(sell_dig):.4f})'
                        ),
                        accion   = (
                            f'Bajar precio de compra {currency} a ≈{float(precio_sug):.4f} '
                            f'(0.5% sobre digital) para mejorar margen de entrada'
                        ),
                        branch   = branch,
                        currency = f'{currency}_compra',
                        data     = {
                            'buy_empresa':  str(buy_emp),
                            'sell_digital': str(sell_dig),
                            'prima_pct':    str(prima_compra),
                            'precio_sug':   str(precio_sug),
                        },
                    )
                    if a:
                        alertas.append(a)

        except Exception as exc:
            log.debug('ALERT_OPORTUNIDAD cur=%s err=%s', currency, exc)
        return alertas
