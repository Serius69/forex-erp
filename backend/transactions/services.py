from django.db import transaction as db_transaction
from django.core.exceptions import ValidationError
from decimal import Decimal
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from django.core.files.base import ContentFile
import qrcode
from datetime import datetime

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
        
        # Actualizar inventario
        self._update_inventory(transaction)
        
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
        """Valida disponibilidad en inventario"""
        from inventory.models import CurrencyInventory
        
        if transaction.transaction_type == 'SELL':
            # Verificar que hay suficiente divisa para vender
            try:
                inventory = CurrencyInventory.objects.get(
                    currency=transaction.currency_from,
                    branch=transaction.branch
                )
                
                if inventory.total_balance < transaction.amount_from:
                    raise ValidationError(
                        f"Saldo insuficiente de {transaction.currency_from.code}. "
                        f"Disponible: {inventory.total_balance}"
                    )
            except CurrencyInventory.DoesNotExist:
                raise ValidationError(
                    f"No hay inventario de {transaction.currency_from.code} en esta sucursal"
                )
    
    def _update_inventory(self, transaction):
        """Actualiza el inventario después de la transacción"""
        from inventory.models import CurrencyInventory, InventoryMovement
        
        if transaction.transaction_type == 'BUY':
            # Casa compra divisas (aumenta inventario de divisa extranjera)
            inventory, created = CurrencyInventory.objects.get_or_create(
                currency=transaction.currency_from,
                branch=transaction.branch,
                defaults={
                    'physical_balance': Decimal('0'),
                    'digital_balance': Decimal('0'),
                    'minimum_stock': Decimal('1000'),
                    'maximum_stock': Decimal('50000'),
                    'weighted_average_cost': transaction.exchange_rate
                }
            )
            inventory.add_currency(
                transaction.amount_from,
                transaction.exchange_rate,
                transaction.cashier
            )
        else:
            # Casa vende divisas (disminuye inventario)
            inventory = CurrencyInventory.objects.get(
                currency=transaction.currency_from,
                branch=transaction.branch
            )
            inventory.remove_currency(
                transaction.amount_from,
                transaction.cashier
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