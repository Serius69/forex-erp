import logging
from django.db import transaction as db_transaction
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from django.core.files.base import ContentFile
import qrcode
from datetime import datetime

log = logging.getLogger('transactions')

# ─────────────────────────────────────────────────────────────────────────────
# Constantes contables
# ─────────────────────────────────────────────────────────────────────────────

MONEY_Q = Decimal('0.01')

# Mapeo: método de pago → campo de CapitalComposicion que se ve afectado.
# Regla de negocio:
#   Efectivo y cheques → "fuertes" (billetes físicos de alta denominación por defecto)
#   QR, transferencias y tarjetas → "qr_transferencias" (digital)
PAYMENT_CASH_FIELD: dict = {
    'CASH':     'fuertes',
    'CHECK':    'fuertes',
    'QR':       'qr_transferencias',
    'TRANSFER': 'qr_transferencias',
    'CARD':     'qr_transferencias',
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers privados
# ─────────────────────────────────────────────────────────────────────────────

def _q(val) -> Decimal:
    return Decimal(str(val or 0)).quantize(MONEY_Q, rounding=ROUND_HALF_UP)



def _broadcast_capital_updated(branch_id) -> None:
    """
    Emite evento WebSocket 'capital_updated' al grupo 'capital_updates'.
    Fire-and-forget: nunca propaga excepciones al caller.
    """
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(
                'capital_updates',
                {
                    'type':      'capital_update',   # → consumer.capital_update()
                    'branch_id': branch_id,
                }
            )
    except Exception as exc:
        log.warning('WS_CAPITAL_BROADCAST_FAIL branch=%s err=%s', branch_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# apply_transaction_effects
# ─────────────────────────────────────────────────────────────────────────────

def apply_transaction_effects(transaction) -> None:
    """
    Aplica los efectos monetarios BOB de una transacción completada
    sobre CapitalComposicion y registra el movimiento en CashFlowLog.

    Regla contable:
        BUY  → empresa paga BOB al cliente  → efectivo_bob DISMINUYE
        SELL → empresa recibe BOB del cliente → efectivo_bob AUMENTA

    El campo exacto que se modifica depende del método de pago
    (ver PAYMENT_CASH_FIELD).

    IMPORTANTE:
        · Debe llamarse dentro de db_transaction.atomic() o justo después
          (la función crea su propio atomic() interno).
        · La transacción debe estar guardada (pk disponible, created_at seteado).
        · Si no existe CapitalComposicion para hoy, la crea con valores en 0.

    Args:
        transaction: instancia de transactions.Transaction ya guardada.

    Raises:
        ValidationError: si el movimiento resultaría en saldo negativo
                         y KAPITALYA_ALLOW_NEGATIVE_EFECTIVO=False (default).
    """
    from django.conf import settings
    from django.utils import timezone
    from capital.models import CapitalComposicion, CapitalComposicionHistory, CashFlowLog

    # Solo afecta transacciones completadas
    if transaction.status != 'COMPLETED':
        return
    # Transacciones BOB-BOB no afectan la composición de efectivo extranjero
    if (transaction.currency_from.code == 'BOB'
            and transaction.currency_to.code == 'BOB'):
        return

    monto_bob = _q(transaction.amount_to)
    campo     = PAYMENT_CASH_FIELD.get(transaction.payment_method, 'fuertes')

    if transaction.transaction_type == 'BUY':
        # Casa COMPRA divisa extranjera → PAGA bolivianos → efectivo BAJA
        delta      = -monto_bob
        tipo_flujo = 'OUT'
        concepto   = (
            f"COMPRA {transaction.currency_from.code} "
            f"× {transaction.amount_from} @ {transaction.exchange_rate}"
        )
    else:
        # Casa VENDE divisa extranjera → RECIBE bolivianos → efectivo SUBE
        delta      = +monto_bob
        tipo_flujo = 'IN'
        concepto   = (
            f"VENTA {transaction.currency_from.code} "
            f"× {transaction.amount_from} @ {transaction.exchange_rate}"
        )

    allow_negative = getattr(settings, 'KAPITALYA_ALLOW_NEGATIVE_EFECTIVO', False)

    with db_transaction.atomic():
        comp, created = (
            CapitalComposicion.objects
            .select_for_update()
            .get_or_create(
                branch=transaction.branch,
                fecha=timezone.localdate(),
                defaults={
                    'fuertes':              Decimal('0'),
                    'caja_chica':           Decimal('0'),
                    'monedas':              Decimal('0'),
                    'rotos':                Decimal('0'),
                    'sueltos':              Decimal('0'),
                    'qr_transferencias':    Decimal('0'),
                    'tarjetas_telefonicas': Decimal('0'),
                    'pasivos':              Decimal('0'),
                    'registrado_por':       transaction.cashier,
                }
            )
        )

        prev_val  = _q(getattr(comp, campo))
        prev_snap = comp.to_snapshot_dict()
        nuevo_val = prev_val + delta

        # Validación: no permitir saldo negativo (configurable)
        if nuevo_val < Decimal('0') and not allow_negative:
            raise ValidationError(
                f"La transacción resultaría en {campo} = {nuevo_val} BOB (negativo). "
                f"Saldo actual: {prev_val} BOB | Movimiento: {delta:+} BOB. "
                f"Verifique la caja antes de continuar o ajuste KAPITALYA_ALLOW_NEGATIVE_EFECTIVO."
            )

        setattr(comp, campo, nuevo_val)
        comp.save(update_fields=[campo, 'updated_at'])

        # Historial de composición (auditoría)
        CapitalComposicionHistory.objects.create(
            composicion    = comp,
            snapshot_prev  = prev_snap,
            snapshot_new   = comp.to_snapshot_dict(),
            motivo         = f"TX {transaction.transaction_number}: {concepto}",
            modificado_por = transaction.cashier,
        )

        # CashFlowLog (registro contable permanente)
        CashFlowLog.objects.create(
            transaction      = transaction,
            tipo             = tipo_flujo,
            concepto         = concepto,
            monto_bob        = monto_bob,
            campo_afectado   = campo,
            saldo_anterior   = prev_val,
            saldo_resultante = nuevo_val,
            branch           = transaction.branch,
            fecha            = timezone.localdate(),
        )

    log.info(
        'CASH_FLOW tx=%s tipo=%s campo=%s delta=%+.2f saldo_prev=%.2f saldo_new=%.2f',
        transaction.transaction_number, tipo_flujo, campo,
        delta, prev_val, nuevo_val,
    )

    # Registrar P&L en ledger analítico (fire-and-forget: nunca bloquea)
    try:
        from analytics.services import ProfitEngine
        ProfitEngine.record_transaction_profit(transaction)
    except Exception as exc:
        log.error('PROFIT_LEDGER_FAIL tx=%s err=%s', transaction.transaction_number, exc)

    # Guardar spread snapshot de esta transacción
    try:
        from analytics.services import SpreadService
        SpreadService.guardar_snapshot()
    except Exception as exc:
        log.warning('SPREAD_SNAPSHOT_FAIL tx=%s err=%s', transaction.transaction_number, exc)

    # Broadcast fuera del atomic — fire-and-forget
    _broadcast_capital_updated(transaction.branch_id)


# ─────────────────────────────────────────────────────────────────────────────
# reverse_transaction_effects
# ─────────────────────────────────────────────────────────────────────────────

def reverse_transaction_effects(transaction) -> None:
    """
    Revierte los efectos monetarios BOB de una transacción.
    Operación inversa exacta de apply_transaction_effects().

    Crea un CashFlowLog de compensación (tipo opuesto al original)
    para mantener el rastro contable completo.

    Se llama cuando:
        · Una transacción es revertida (Transaction.reverse())
        · Una transacción es eliminada (destroy en la vista)

    Args:
        transaction: instancia original de Transaction a revertir.
                     Puede estar en cualquier estado (el reverso siempre procede).
    """
    from django.utils import timezone
    from capital.models import CapitalComposicion, CapitalComposicionHistory, CashFlowLog

    # Transacciones BOB-BOB no tienen efectos de caja que revertir
    if (transaction.currency_from.code == 'BOB'
            and transaction.currency_to.code == 'BOB'):
        return

    monto_bob = _q(transaction.amount_to)
    campo     = PAYMENT_CASH_FIELD.get(transaction.payment_method, 'fuertes')

    if transaction.transaction_type == 'BUY':
        # El BUY original había DECREMENTADO el efectivo → reversa lo INCREMENTA
        delta      = +monto_bob
        tipo_flujo = 'IN'
        concepto   = (
            f"REVERSA COMPRA {transaction.currency_from.code} "
            f"× {transaction.amount_from} (TX {transaction.transaction_number})"
        )
    else:
        # El SELL original había INCREMENTADO el efectivo → reversa lo DECREMENTA
        delta      = -monto_bob
        tipo_flujo = 'OUT'
        concepto   = (
            f"REVERSA VENTA {transaction.currency_from.code} "
            f"× {transaction.amount_from} (TX {transaction.transaction_number})"
        )

    with db_transaction.atomic():
        try:
            comp = (
                CapitalComposicion.objects
                .select_for_update()
                .get(branch=transaction.branch, fecha=timezone.localdate())
            )
        except CapitalComposicion.DoesNotExist:
            # Sin composición hoy: el movimiento original no afectó la caja de hoy.
            # Si la TX fue de otro día, el saldo ya no es recuperable automáticamente.
            log.warning(
                'CASH_REVERSE_SKIP no CapitalComposicion hoy para branch=%s tx=%s',
                transaction.branch_id, transaction.transaction_number,
            )
            return

        prev_val  = _q(getattr(comp, campo))
        prev_snap = comp.to_snapshot_dict()
        nuevo_val = prev_val + delta

        setattr(comp, campo, nuevo_val)
        comp.save(update_fields=[campo, 'updated_at'])

        CapitalComposicionHistory.objects.create(
            composicion    = comp,
            snapshot_prev  = prev_snap,
            snapshot_new   = comp.to_snapshot_dict(),
            motivo         = concepto,
            modificado_por = transaction.cashier,
        )

        CashFlowLog.objects.create(
            transaction      = transaction,
            tipo             = tipo_flujo,
            concepto         = concepto,
            monto_bob        = monto_bob,
            campo_afectado   = campo,
            saldo_anterior   = prev_val,
            saldo_resultante = nuevo_val,
            branch           = transaction.branch,
            fecha            = timezone.localdate(),
        )

    log.info(
        'CASH_REVERSE tx=%s tipo=%s campo=%s delta=%+.2f saldo_prev=%.2f saldo_new=%.2f',
        transaction.transaction_number, tipo_flujo, campo,
        delta, prev_val, nuevo_val,
    )

    # Compensar P&L del ledger analítico
    try:
        from analytics.services import ProfitEngine
        ProfitEngine.record_reversal_profit(transaction)
    except Exception as exc:
        log.error('REVERSAL_LEDGER_FAIL tx=%s err=%s', transaction.transaction_number, exc)

    _broadcast_capital_updated(transaction.branch_id)


# ─────────────────────────────────────────────────────────────────────────────
# TransactionService
# ─────────────────────────────────────────────────────────────────────────────

class TransactionService:
    """Servicio para gestión de transacciones"""
    
    @db_transaction.atomic
    def create_transaction(self, data, user):
        """Crea una nueva transacción con validaciones"""
        from .models import Transaction, Customer
        from inventory.models import CurrencyInventory
        
        # Validar cliente
        customer = self._get_or_create_customer(data)
        
        # Crear transacción
        transaction = Transaction(
            transaction_type=data['transaction_type'],
            customer=customer,
            currency_from_id=data['currency_from'],
            currency_to_id=data['currency_to'],
            amount_from=Decimal(str(data['amount_from'])),
            amount_to=Decimal(str(data['amount_to'])),
            exchange_rate=Decimal(str(data['exchange_rate'])),
            payment_method=data['payment_method'],
            payment_reference=data.get('payment_reference', ''),
            cashier=user,
            branch=user.branch,
            notes=data.get('notes', '')
        )
        
        # Verificar si requiere supervisor
        if transaction.requires_supervisor and not data.get('supervisor_pin'):
            raise ValidationError("Esta transacción requiere autorización de supervisor")
        
        if data.get('supervisor_pin'):
            supervisor = self._validate_supervisor_pin(data['supervisor_pin'])
            transaction.supervisor = supervisor
        
        # Validar inventario
        self._validate_inventory(transaction)
        
        # Guardar transacción
        transaction.save()
        
        # Actualizar inventario de divisas
        self._update_inventory(transaction)

        # Aplicar efectos sobre el efectivo BOB (CapitalComposicion + CashFlowLog)
        apply_transaction_effects(transaction)

        # Generar comprobante
        receipt_file = self._generate_receipt(transaction)
        transaction.receipt_number = f"R-{transaction.transaction_number}"
        transaction.save()
        
        return transaction, receipt_file
    
    def _get_or_create_customer(self, data):
        """Obtiene o crea un cliente"""
        from .models import Customer
        
        customer_data = data.get('customer', {})
        
        if 'id' in customer_data:
            return Customer.objects.get(id=customer_data['id'])
        
        customer, created = Customer.objects.get_or_create(
            document_number=customer_data['document_number'],
            defaults={
                'document_type': customer_data.get('document_type', 'CI'),
                'full_name': customer_data['full_name'],
                'phone': customer_data.get('phone', ''),
                'email': customer_data.get('email', ''),
                'address': customer_data.get('address', ''),
            }
        )
        
        # Actualizar si ya existe
        if not created:
            for field in ['full_name', 'phone', 'email', 'address']:
                if customer_data.get(field):
                    setattr(customer, field, customer_data[field])
            customer.save()
        
        return customer
    
    def _validate_supervisor_pin(self, pin):
        """Valida PIN de supervisor"""
        from users.models import User
        
        supervisors = User.objects.filter(role__in=['ADMIN', 'SUPERVISOR'])
        
        for supervisor in supervisors:
            if supervisor.check_pin(pin):
                return supervisor
        
        raise ValidationError("PIN de supervisor inválido")
    
    def _validate_inventory(self, transaction):
        from inventory.models import CurrencyInventory

        # Solo validar si vendemos divisa extranjera (no BOB)
        if transaction.transaction_type == 'SELL' and transaction.currency_from.code != 'BOB':
            try:
                inventory = CurrencyInventory.objects.get(
                    currency=transaction.currency_from,
                    branch=transaction.branch
                )
                if inventory.total_balance < transaction.amount_from:
                    raise ValidationError(
                        f"Saldo insuficiente de {transaction.currency_from.code}. "
                        f"Disponible: {inventory.total_balance:.2f}"
                    )
            except CurrencyInventory.DoesNotExist:
                # Si no hay inventario registrado, permitir pero loguear
                import logging
                logging.getLogger(__name__).warning(
                    f"No inventory record for {transaction.currency_from.code} "
                    f"in branch {transaction.branch.code}"
                )
        
    def _update_inventory(self, transaction):
        """
        Actualiza el inventario después de la transacción.
        Usa select_for_update() para prevenir race conditions en operaciones concurrentes.
        Debe llamarse dentro de db_transaction.atomic().
        """
        from inventory.models import CurrencyInventory, InventoryMovement

        if transaction.transaction_type == 'BUY':
            # Casa compra divisas — aumenta inventario de divisa extranjera
            inventory, _ = CurrencyInventory.objects.select_for_update().get_or_create(
                currency=transaction.currency_from,
                branch=transaction.branch,
                defaults={
                    'physical_balance':       Decimal('0'),
                    'digital_balance':        Decimal('0'),
                    'minimum_stock':          Decimal('1000'),
                    'maximum_stock':          Decimal('50000'),
                    'weighted_average_cost':  transaction.exchange_rate,
                }
            )
            inventory.add_currency(
                transaction.amount_from,
                transaction.exchange_rate,
                transaction.cashier,
            )
        else:
            # Casa vende divisas — disminuye inventario
            try:
                inventory = CurrencyInventory.objects.select_for_update().get(
                    currency=transaction.currency_from,
                    branch=transaction.branch,
                )
            except CurrencyInventory.DoesNotExist:
                raise ValueError(
                    f"No existe inventario de {transaction.currency_from.code} "
                    f"en sucursal {transaction.branch.code}"
                )
            inventory.remove_currency(
                transaction.amount_from,
                transaction.cashier,
            )
    
    def _reverse_inventory(self, transaction):
        """
        Revierte el efecto de una transacción sobre el inventario.
        Operación inversa exacta de _update_inventory().
        Debe llamarse dentro de db_transaction.atomic().
        """
        from inventory.models import CurrencyInventory

        if transaction.transaction_type == 'BUY':
            # La compra había aumentado la divisa — deshacer: disminuir
            try:
                inventory = CurrencyInventory.objects.select_for_update().get(
                    currency=transaction.currency_from,
                    branch=transaction.branch,
                )
                inventory.remove_currency(
                    transaction.amount_from,
                    transaction.cashier,
                )
            except CurrencyInventory.DoesNotExist:
                import logging
                logging.getLogger('transactions').warning(
                    "REVERSE_INVENTORY_SKIP no record for %s in %s",
                    transaction.currency_from.code, transaction.branch.code,
                )
        else:
            # La venta había disminuido la divisa — deshacer: aumentar
            inventory, _ = CurrencyInventory.objects.select_for_update().get_or_create(
                currency=transaction.currency_from,
                branch=transaction.branch,
                defaults={
                    'physical_balance':      Decimal('0'),
                    'digital_balance':       Decimal('0'),
                    'minimum_stock':         Decimal('100'),
                    'maximum_stock':         Decimal('50000'),
                    'weighted_average_cost': transaction.exchange_rate,
                }
            )
            inventory.add_currency(
                transaction.amount_from,
                transaction.exchange_rate,
                transaction.cashier,
            )

    def _generate_receipt(self, transaction):
        """Genera comprobante PDF de la transacción"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        story = []
        styles = getSampleStyleSheet()
        
        # Título
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            alignment=1,  # Center
            spaceAfter=30
        )
        story.append(Paragraph("CASA DE CAMBIO", title_style))
        story.append(Paragraph("COMPROBANTE DE TRANSACCIÓN", styles['Heading2']))
        story.append(Spacer(1, 20))
        
        # Información de la transacción
        data = [
            ['Número:', transaction.transaction_number],
            ['Fecha:', transaction.created_at.strftime('%d/%m/%Y %H:%M')],
            ['Tipo:', transaction.get_transaction_type_display()],
            ['Cliente:', transaction.customer.full_name],
            ['Documento:', f"{transaction.customer.document_type} {transaction.customer.document_number}"],
            ['', ''],
            ['Divisa:', transaction.currency_from.code],
            ['Monto:', f"{transaction.amount_from:,.2f}"],
            ['Tipo de Cambio:', f"{transaction.exchange_rate:,.4f}"],
            ['Total BOB:', f"{transaction.amount_to:,.2f}"],
            ['', ''],
            ['Método de Pago:', transaction.get_payment_method_display()],
            ['Cajero:', transaction.cashier.get_full_name()],
            ['Sucursal:', transaction.branch.name],
        ]
        
        # Crear tabla
        table = Table(data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table)
        story.append(Spacer(1, 30))
        
        # Generar código QR
        qr_data = f"TRX:{transaction.transaction_number}|{transaction.amount_from}|{transaction.currency_from.code}"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        # Nota legal
        legal_text = """
        Este comprobante es válido como constancia de la operación cambiaria realizada.
        Conserve este documento para cualquier reclamo o consulta posterior.
        """
        story.append(Paragraph(legal_text, styles['Normal']))
        
        # Generar PDF
        doc.build(story)
        buffer.seek(0)
        
        return ContentFile(buffer.read(), name=f'receipt_{transaction.transaction_number}.pdf')