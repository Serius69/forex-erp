# reports/services/rte_service.py
"""
RTEService — generación automática del RTE (Registro de Transacciones en
Efectivo >= USD 1,000, normativa ASFI) con notificación push por WebSocket.

Antes de esta pieza el modelo CashTransactionReport existía pero nada lo
poblaba: los RTE solo se veían al generar el reporte mensual bajo demanda.
Ahora cada Transaction COMPLETED en efectivo se evalúa al crearse (señal
post_save) y, si su equivalente USD alcanza el umbral, se crea el RTE y se
emite una alerta global (AlertLog + WS 'alert_log' + email según severidad).
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction as db_tx
from django.utils import timezone

log = logging.getLogger('kapitalya.rte')

USD_Q = Decimal('0.01')


class RTEService:

    @classmethod
    def evaluar_transaccion(cls, tx) -> 'CashTransactionReport | None':
        """
        Evalúa una Transaction y crea su RTE si corresponde.

        Condiciones: COMPLETED + pago en efectivo + visible_asfi + cliente
        identificado + sin RTE previo + equivalente USD >= 1,000.

        Idempotente (OneToOne transaction↔rte_report). Nunca lanza hacia el
        caller: un fallo aquí no debe abortar el registro de la transacción.
        """
        from reports.models import CashTransactionReport

        try:
            if tx.status != 'COMPLETED' or tx.payment_method != 'CASH':
                return None
            if not getattr(tx, 'visible_asfi', False) or not tx.customer_id:
                return None
            if CashTransactionReport.objects.filter(transaction=tx).exists():
                return None

            equiv = cls._equivalente_usd(tx)
            if equiv is None:
                return None
            usd_equiv, currency_code, original_amount, rate_usd = equiv

            if not CashTransactionReport.should_report(usd_equiv):
                return None

            customer = tx.customer
            rte = CashTransactionReport.objects.create(
                transaction            = tx,
                report_date            = timezone.localtime(
                    tx.created_at or timezone.now()).date(),
                amount_usd_equiv       = usd_equiv,
                currency_code          = currency_code,
                original_amount        = original_amount,
                exchange_rate_usd      = rate_usd,
                customer_full_name     = customer.full_name,
                customer_document_type = customer.document_type,
                customer_document_num  = customer.document_number,
                customer_nationality   = customer.nationality or 'Boliviana',
                customer_is_pep        = customer.is_pep,
            )
            log.info('RTE_AUTO_CREATED num=%s tx=%s usd=%s pep=%s',
                     rte.report_number, tx.transaction_number,
                     usd_equiv, customer.is_pep)

            # Notificar después del commit: si la transacción externa hace
            # rollback, el RTE desaparece y la alerta no debe salir.
            db_tx.on_commit(lambda: cls._notificar(rte, tx))
            return rte

        except Exception as exc:
            log.error('RTE_EVAL_FAILED tx=%s err=%s',
                      getattr(tx, 'transaction_number', tx.pk), exc)
            return None

    # ── Equivalencia USD ──────────────────────────────────────────────────────

    @classmethod
    def _equivalente_usd(cls, tx):
        """
        Retorna (usd_equiv, currency_code, original_amount, rate_usd) o None.

        BUY : cliente entrega divisa → divisa = currency_from / amount_from.
        SELL: casa vende divisa      → divisa = currency_to   / amount_to.
        Si la divisa es USD el equivalente es directo; si no, se convierte el
        contravalor BOB con la tasa USD/BOB paralela vigente.
        """
        # En este sistema BUY y SELL registran divisa→BOB (currency_from=divisa,
        # currency_to=BOB). Determinar la pata extranjera como el lado que NO es
        # BOB corrige los SELL reales y mantiene compatible la orientación
        # invertida (BOB→divisa) que usan algunos tests/cargas legacy.
        if tx.currency_from and tx.currency_from.code != 'BOB':
            foreign, units, bob_total = tx.currency_from, tx.amount_from, tx.amount_to
        else:
            foreign, units, bob_total = tx.currency_to, tx.amount_to, tx.amount_from

        if foreign is None or not units:
            return None
        code = foreign.code
        if code == 'BOB':
            return None   # BOB↔BOB no es transacción en divisa

        units     = Decimal(str(units))
        bob_total = Decimal(str(bob_total or 0))

        if code == 'USD':
            scale = max(int(getattr(foreign, 'scale_factor', 1) or 1), 1)
            usd   = (units / scale).quantize(USD_Q, rounding=ROUND_HALF_UP)
            rate  = tx.exchange_rate or Decimal('0')
            return usd, code, units, rate

        rate_usd = cls._tasa_usd_bob()
        if not rate_usd or bob_total <= 0:
            log.warning('RTE_SIN_TASA_USD tx=%s divisa=%s — no evaluable',
                        tx.transaction_number, code)
            return None
        usd = (bob_total / rate_usd).quantize(USD_Q, rounding=ROUND_HALF_UP)
        return usd, code, units, rate_usd

    @staticmethod
    def _tasa_usd_bob():
        """Tasa USD→BOB vigente: mid del mercado paralelo (fallback físico)."""
        from rates.models import ExchangeRate
        for market in ('paralelo_digital', 'paralelo_fisico_empresa'):
            r = (ExchangeRate.objects
                 .filter(currency_from__code='USD', currency_to__code='BOB',
                         valid_until__isnull=True, market_type=market)
                 .order_by('-created_at')
                 .first())
            if r and r.buy_rate and r.sell_rate:
                return ((Decimal(str(r.buy_rate)) + Decimal(str(r.sell_rate)))
                        / 2).quantize(Decimal('0.000001'))
            if r and r.sell_rate:
                return Decimal(str(r.sell_rate))
        return None

    # ── Notificación push ─────────────────────────────────────────────────────

    @staticmethod
    def _notificar(rte, tx):
        """AlertLog + WS 'alert_log' + email vía GlobalAlertService."""
        try:
            from alerts.services import GlobalAlertService
            pep = ' — cliente PEP' if rte.customer_is_pep else ''
            GlobalAlertService.emit(
                source          = 'TRANSACTION',
                alert_type      = 'RTE_CREATED',
                severity        = 'HIGH' if rte.customer_is_pep else 'MEDIUM',
                title           = f'RTE {rte.report_number} generado',
                message         = (
                    f'Transacción {tx.transaction_number} en efectivo por '
                    f'USD {rte.amount_usd_equiv} equivalentes '
                    f'({rte.original_amount} {rte.currency_code}) requiere '
                    f'reporte ASFI{pep}. Cliente: {rte.customer_full_name} '
                    f'({rte.customer_document_num}).'
                ),
                accion_sugerida = ('Revisar el RTE en Reportes → ASFI y '
                                   'enviarlo dentro del plazo regulatorio.'),
                data            = {
                    'rte_id':           rte.id,
                    'report_number':    rte.report_number,
                    'transaction':      tx.transaction_number,
                    'amount_usd_equiv': str(rte.amount_usd_equiv),
                    'currency_code':    rte.currency_code,
                    'customer_is_pep':  rte.customer_is_pep,
                },
                branch          = tx.branch,
                triggered_by    = getattr(tx, 'cashier', None),
            )
        except Exception as exc:
            log.error('RTE_NOTIFY_FAILED rte=%s err=%s', rte.report_number, exc)
