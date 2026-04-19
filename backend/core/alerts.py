"""
Sistema de alertas internas de Kapitalya ERP.

Detecta y registra fallos en:
  - Base de datos
  - Celery / tareas programadas
  - Predicciones ML
  - Tasas de cambio
  - Inventario crítico
  - Seguridad (múltiples intentos fallidos, rate limits)

Las alertas se almacenan en cache (Redis) y pueden enviarse por:
  - WebSocket al frontend (canal 'system_alerts')
  - Log de seguridad
  - (futuro) Email/Slack

No lanza excepciones — el alerting nunca debe romper el sistema principal.
"""
import logging
from datetime import datetime, timezone
from django.core.cache import cache
from django.conf import settings

log = logging.getLogger('kapitalya.health')
log_security = logging.getLogger('kapitalya.security')

# ── Constantes ────────────────────────────────────────────────────────────────
SEVERITY_LEVELS = ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
ALERT_CACHE_KEY = 'system_alerts_queue'
ALERT_CACHE_TTL = 86400  # 24 horas
MAX_ALERTS_IN_CACHE = 100


class SystemAlert:
    """
    Interfaz para crear y recuperar alertas del sistema.
    """

    @staticmethod
    def create(
        component: str,
        message: str,
        severity: str = 'HIGH',
        details: dict = None,
    ) -> dict | None:
        """
        Crea una alerta del sistema.

        Args:
            component:  módulo afectado ('db', 'celery', 'ml', 'rates', 'security')
            message:    descripción del problema
            severity:   LOW | MEDIUM | HIGH | CRITICAL
            details:    datos adicionales opcionales

        Returns:
            dict con la alerta creada, o None si falló
        """
        if severity not in SEVERITY_LEVELS:
            severity = 'HIGH'

        alert = {
            'id':        _generate_alert_id(component),
            'component': component,
            'message':   message,
            'severity':  severity,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'details':   details or {},
            'resolved':  False,
        }

        try:
            # Guardar en cache
            alerts = cache.get(ALERT_CACHE_KEY, [])
            alerts.insert(0, alert)
            alerts = alerts[:MAX_ALERTS_IN_CACHE]
            cache.set(ALERT_CACHE_KEY, alerts, ALERT_CACHE_TTL)

            # Log según severidad
            log_msg = f"SYSTEM_ALERT severity={severity} component={component} msg={message}"
            if severity == 'CRITICAL':
                log.critical(log_msg)
            elif severity == 'HIGH':
                log.error(log_msg)
            elif severity == 'MEDIUM':
                log.warning(log_msg)
            else:
                log.info(log_msg)

            # Push via WebSocket al frontend
            SystemAlert._push_to_websocket(alert)

        except Exception as e:
            # Nunca romper el sistema por un fallo en el alerting
            log.warning("ALERT_CREATE_FAILED: %s", e)
            return None

        return alert

    @staticmethod
    def get_active(limit: int = 20) -> list:
        """Recupera las alertas activas más recientes."""
        try:
            alerts = cache.get(ALERT_CACHE_KEY, [])
            active = [a for a in alerts if not a.get('resolved', False)]
            return active[:limit]
        except Exception:
            return []

    @staticmethod
    def get_all(limit: int = 50) -> list:
        """Recupera todas las alertas (activas + resueltas)."""
        try:
            return cache.get(ALERT_CACHE_KEY, [])[:limit]
        except Exception:
            return []

    @staticmethod
    def resolve(alert_id: str, resolved_by: str = 'system') -> bool:
        """Marca una alerta como resuelta."""
        try:
            alerts = cache.get(ALERT_CACHE_KEY, [])
            for alert in alerts:
                if alert.get('id') == alert_id:
                    alert['resolved'] = True
                    alert['resolved_by'] = resolved_by
                    alert['resolved_at'] = datetime.now(timezone.utc).isoformat()
                    break
            cache.set(ALERT_CACHE_KEY, alerts, ALERT_CACHE_TTL)
            log.info("ALERT_RESOLVED id=%s by=%s", alert_id, resolved_by)
            return True
        except Exception as e:
            log.warning("ALERT_RESOLVE_FAILED id=%s error=%s", alert_id, e)
            return False

    @staticmethod
    def resolve_by_component(component: str, resolved_by: str = 'system') -> int:
        """Resuelve todas las alertas de un componente."""
        try:
            alerts = cache.get(ALERT_CACHE_KEY, [])
            count = 0
            for alert in alerts:
                if alert.get('component') == component and not alert.get('resolved'):
                    alert['resolved'] = True
                    alert['resolved_by'] = resolved_by
                    alert['resolved_at'] = datetime.now(timezone.utc).isoformat()
                    count += 1
            cache.set(ALERT_CACHE_KEY, alerts, ALERT_CACHE_TTL)
            if count:
                log.info("ALERTS_RESOLVED_BY_COMPONENT component=%s count=%d", component, count)
            return count
        except Exception:
            return 0

    @staticmethod
    def _push_to_websocket(alert: dict):
        """
        Envía la alerta en tiempo real via Django Channels.
        Falla silenciosamente si channels no está disponible.
        """
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            channel_layer = get_channel_layer()
            if channel_layer is None:
                return

            async_to_sync(channel_layer.group_send)(
                'rates_updates',  # grupo de WebSocket que el frontend ya escucha
                {
                    'type':  'system_alert',
                    'alert': alert,
                }
            )
        except Exception:
            pass  # WebSocket no disponible — la alerta está en cache de todas formas


# ── Detector de anomalías financieras ────────────────────────────────────────

class FinancialAnomalyDetector:
    """
    Detecta y alerta sobre anomalías en transacciones financieras.
    """

    # Thresholds configurables
    LARGE_TX_BOB = getattr(settings, 'LARGE_TX_THRESHOLD_BOB', 100_000)  # Bs 100k
    MAX_TX_PER_HOUR = getattr(settings, 'MAX_TX_PER_HOUR_PER_USER', 50)

    @staticmethod
    def check_large_transaction(tx) -> bool:
        """
        Alerta si una transacción supera el umbral de monto grande.
        Retorna True si se emitió alerta.
        """
        try:
            amount = float(tx.amount_to or 0)
            if amount >= FinancialAnomalyDetector.LARGE_TX_BOB:
                SystemAlert.create(
                    component='transactions',
                    message=(
                        f'Transacción de alto monto: Bs {amount:,.2f} '
                        f'(N° {tx.transaction_number})'
                    ),
                    severity='MEDIUM',
                    details={
                        'transaction_id':     tx.id,
                        'transaction_number': tx.transaction_number,
                        'amount_bob':         str(amount),
                        'customer':           str(tx.customer),
                        'cashier':            str(tx.cashier),
                    },
                )
                return True
        except Exception as e:
            log.warning("ANOMALY_CHECK_FAILED: %s", e)
        return False

    @staticmethod
    def check_rapid_transactions(user_id: int, branch_id: int) -> bool:
        """
        Detecta múltiples transacciones rápidas del mismo cajero.
        Útil para detectar errores operativos o uso abusivo.
        """
        cache_key = f"tx_count_rate:user:{user_id}:branch:{branch_id}"
        try:
            count = cache.get(cache_key, 0)
            if count >= FinancialAnomalyDetector.MAX_TX_PER_HOUR:
                log_security.warning(
                    "RAPID_TX_DETECTED user_id=%d branch_id=%d count=%d",
                    user_id, branch_id, count,
                )
                SystemAlert.create(
                    component='security',
                    message=f'Transacciones rápidas detectadas: usuario {user_id} ({count}/hora)',
                    severity='MEDIUM',
                    details={'user_id': user_id, 'branch_id': branch_id, 'count': count},
                )
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def record_transaction(user_id: int, branch_id: int):
        """Incrementa el contador de transacciones del cajero para detección de anomalías."""
        cache_key = f"tx_count_rate:user:{user_id}:branch:{branch_id}"
        try:
            current = cache.get(cache_key, 0)
            if current == 0:
                cache.set(cache_key, 1, timeout=3600)
            else:
                cache.incr(cache_key)
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_alert_id(component: str) -> str:
    """Genera un ID único para la alerta."""
    import hashlib
    ts = str(datetime.now(timezone.utc).timestamp())
    return hashlib.sha256(f"{component}:{ts}".encode()).hexdigest()[:16]


# ── Vista de alertas para el admin (integrada en health) ─────────────────────

def get_alerts_summary() -> dict:
    """Resumen de alertas para el dashboard de métricas."""
    all_alerts = SystemAlert.get_all(50)
    active = [a for a in all_alerts if not a.get('resolved')]

    by_severity = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    for a in active:
        sev = a.get('severity', 'LOW')
        by_severity[sev] = by_severity.get(sev, 0) + 1

    return {
        'total_active':    len(active),
        'by_severity':     by_severity,
        'latest':          active[:5],
    }
