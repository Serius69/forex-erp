from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from django.http import HttpResponse
from .models import Transaction, Customer, TransactionDocument
from .serializers import (
    TransactionSerializer, CustomerSerializer,
    TransactionCreateSerializer, TransactionDocumentSerializer
)
from .services import TransactionService
from .permissions import CanReverseTransaction

class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtrar por sucursal si no es admin
        if not self.request.user.has_perm('transactions.can_view_all_branches'):
            queryset = queryset.filter(branch=self.request.user.branch)
        
        # Filtros adicionales
        customer_id = self.request.query_params.get('customer_id')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        status = self.request.query_params.get('status')
        transaction_type = self.request.query_params.get('type')
        
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)
        if status:
            queryset = queryset.filter(status=status)
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        
        return queryset.select_related(
            'customer', 'currency_from', 'currency_to', 
            'cashier', 'branch', 'supervisor'
        ).order_by('-created_at')
    
    def get_serializer_class(self):
        if self.action == 'create':
            return TransactionCreateSerializer
        return TransactionSerializer
    
    def create(self, request):
        """Crea nueva transacción"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        service = TransactionService()
        
        try:
            transaction, receipt_file = service.create_transaction(
                serializer.validated_data,
                request.user
            )
            
            # Guardar documento del recibo
            TransactionDocument.objects.create(
                transaction=transaction,
                document_type='RECEIPT',
                file=receipt_file,
                description='Comprobante de transacción',
                uploaded_by=request.user
            )
            
            # Registrar actividad
            from users.models import UserActivity
            UserActivity.objects.create(
                user=request.user,
                action='TRANSACTION_CREATED',
                details={
                    'transaction_id': transaction.id,
                    'transaction_number': transaction.transaction_number,
                    'amount': float(transaction.amount_from),
                    'currency': transaction.currency_from.code
                },
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
            
            return Response(
                TransactionSerializer(transaction).data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['POST'], permission_classes=[CanReverseTransaction])
    def reverse(self, request, pk=None):
        """Revierte una transacción"""
        transaction = self.get_object()
        reason = request.data.get('reason', '')
        
        if not reason:
            return Response(
                {'error': 'Debe proporcionar una razón para la reversa'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            reversal = transaction.reverse(request.user, reason)
            
            return Response({
                'success': True,
                'reversal': TransactionSerializer(reversal).data
            })
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['GET'])
    def receipt(self, request, pk=None):
        """Descarga el comprobante de la transacción"""
        transaction = self.get_object()
        
        try:
            document = transaction.documents.filter(
                document_type='RECEIPT'
            ).latest('uploaded_at')
            
            response = HttpResponse(
                document.file,
                content_type='application/pdf'
            )
            response['Content-Disposition'] = f'attachment; filename="{transaction.transaction_number}.pdf"'
            return response
            
        except TransactionDocument.DoesNotExist:
            # Generar nuevo comprobante
            service = TransactionService()
            receipt_file = service._generate_receipt(transaction)
            
            response = HttpResponse(receipt_file, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{transaction.transaction_number}.pdf"'
            return response
    
    @action(detail=False, methods=['GET'])
    def daily_summary(self, request):
        """Resumen diario de transacciones"""
        date = request.query_params.get('date', timezone.now().date())
        
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d').date()
        
        transactions = self.get_queryset().filter(
            created_at__date=date
        )
        
        summary = {
            'date': date,
            'total_transactions': transactions.count(),
            'by_type': {
                'buy': transactions.filter(transaction_type='BUY').count(),
                'sell': transactions.filter(transaction_type='SELL').count(),
            },
            'by_currency': {},
            'total_volume_bob': 0,
            'by_payment_method': {},
            'by_hour': []
        }
        
        # Resumen por divisa
        currencies = transactions.values('currency_from__code').distinct()
        for currency in currencies:
            code = currency['currency_from__code']
            currency_transactions = transactions.filter(currency_from__code=code)
            
            summary['by_currency'][code] = {
                'buy': {
                    'count': currency_transactions.filter(transaction_type='BUY').count(),
                    'volume': currency_transactions.filter(
                        transaction_type='BUY'
                    ).aggregate(Sum('amount_from'))['amount_from__sum'] or 0
                },
                'sell': {
                    'count': currency_transactions.filter(transaction_type='SELL').count(),
                    'volume': currency_transactions.filter(
                        transaction_type='SELL'
                    ).aggregate(Sum('amount_from'))['amount_from__sum'] or 0
                }
            }
        
        # Volumen total en BOB
        summary['total_volume_bob'] = transactions.aggregate(
            Sum('amount_to')
        )['amount_to__sum'] or 0
        
        # Por método de pago
        payment_methods = transactions.values('payment_method').annotate(
            count=Count('id'),
            volume=Sum('amount_to')
        )
        
        for pm in payment_methods:
            summary['by_payment_method'][pm['payment_method']] = {
                'count': pm['count'],
                'volume': float(pm['volume'] or 0)
            }
        
        # Por hora del día
        for hour in range(24):
            hour_transactions = transactions.filter(
                created_at__hour=hour
            )
            summary['by_hour'].append({
                'hour': hour,
                'count': hour_transactions.count(),
                'volume': float(
                    hour_transactions.aggregate(
                        Sum('amount_to')
                    )['amount_to__sum'] or 0
                )
            })
        
        return Response(summary)
    
    @action(detail=False, methods=['GET'])
    def pending_approvals(self, request):
        """Transacciones pendientes de aprobación"""
        if request.user.role not in ['ADMIN', 'SUPERVISOR']:
            return Response(
                {'error': 'No autorizado'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        pending = self.get_queryset().filter(
            status='PENDING',
            supervisor__isnull=True
        ).filter(
            Q(amount_from__gte=5000) | Q(amount_to__gte=35000)
        )
        
        serializer = self.get_serializer(pending, many=True)
        return Response(serializer.data)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Búsqueda
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(document_number__icontains=search) |
                Q(full_name__icontains=search) |
                Q(phone__icontains=search)
            )
        
        # Filtro de clientes frecuentes
        frequent_only = self.request.query_params.get('frequent_only')
        if frequent_only == 'true':
            queryset = queryset.filter(is_frequent=True)
        
        return queryset.annotate(
            transaction_count=Count('transactions'),
            total_volume=Sum('transactions__amount_from')
        ).order_by('-transaction_count')
    
    @action(detail=False, methods=['GET'])
    def search(self, request):
        """Búsqueda rápida de cliente por documento"""
        document = request.query_params.get('document')
        
        if not document:
            return Response(
                {'error': 'Número de documento requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            customer = Customer.objects.get(document_number=document)
            return Response(CustomerSerializer(customer).data)
        except Customer.DoesNotExist:
            return Response(
                {'message': 'Cliente no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['GET'])
    def transactions(self, request, pk=None):
        """Obtiene las transacciones de un cliente"""
        customer = self.get_object()
        transactions = Transaction.objects.filter(
            customer=customer
        ).order_by('-created_at')[:50]
        
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['POST'])
    def mark_frequent(self, request, pk=None):
        """Marca un cliente como frecuente"""
        customer = self.get_object()
        customer.is_frequent = True
        customer.save()
        
        return Response({'success': True})