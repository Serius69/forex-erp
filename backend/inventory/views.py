from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F, ExpressionWrapper, DecimalField
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from tenants.permissions import IsCompanyMember

# total_balance es @property, no campo DB — usar esta expresión en queries
_TOTAL_BAL = ExpressionWrapper(
    F('physical_balance') + F('digital_balance'),
    output_field=DecimalField(max_digits=15, decimal_places=2),
)
from .models import CurrencyInventory, InventoryMovement, InventoryTransfer, InventoryCard
from .alerts import InventoryAlert, InventoryAlertService
from .serializers import (
    CurrencyInventorySerializer,
    InventoryMovementSerializer,
    InventoryTransferSerializer,
    InventoryAlertSerializer,
    InventoryAdjustmentSerializer,
    InventoryCardSerializer,
)

class CurrencyInventoryViewSet(viewsets.ModelViewSet):
    queryset = CurrencyInventory.objects.all()
    serializer_class = CurrencyInventorySerializer
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        # Tenant isolation
        if getattr(user, 'company_id', None):
            queryset = queryset.filter(branch__company_id=user.company_id)

        # Branch isolation for CASHIER
        if user.role == 'CASHIER' and user.branch_id:
            queryset = queryset.filter(branch_id=user.branch_id)
        
        # Filtros adicionales
        branch_id = self.request.query_params.get('branch_id')
        currency_code = self.request.query_params.get('currency')
        needs_replenishment = self.request.query_params.get('needs_replenishment')
        
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        if currency_code:
            queryset = queryset.filter(currency__code=currency_code)
        if needs_replenishment == 'true':
            queryset = queryset.filter(
                Q(physical_balance__lte=F('reorder_point')) |
                Q(digital_balance__lte=F('reorder_point'))
            )
        
        return queryset.select_related('currency', 'branch').annotate(
            recent_movements=Count('movements', filter=Q(
                movements__created_at__gte=timezone.now() - timedelta(days=7)
            ))
        )
    
    @action(detail=False, methods=['GET'])
    def summary(self, request):
        """Resumen general del inventario"""
        inventories = self.get_queryset()

        # Anotar total_balance como campo DB para poder filtrar
        inventories_ann = inventories.annotate(total_balance_db=_TOTAL_BAL)

        summary = {
            'total_currencies': inventories_ann.count(),
            'needs_replenishment': inventories_ann.filter(
                total_balance_db__lte=F('reorder_point')
            ).count(),
            'overstocked': inventories_ann.filter(
                total_balance_db__gt=F('maximum_stock')
            ).count(),
            'by_currency': {},
            'total_value_bob': 0
        }
        
        # Resumen por divisa
        for inventory in inventories:
            currency_code = inventory.currency.code
            
            if currency_code not in summary['by_currency']:
                summary['by_currency'][currency_code] = {
                    'total_balance': 0,
                    'total_value': 0,
                    'branches': []
                }
            
            summary['by_currency'][currency_code]['total_balance'] += float(inventory.total_balance)
            value = float(inventory.total_balance * inventory.weighted_average_cost)
            summary['by_currency'][currency_code]['total_value'] += value
            summary['by_currency'][currency_code]['branches'].append({
                'branch': inventory.branch.name,
                'balance': float(inventory.total_balance),
                'status': 'low' if inventory.needs_replenishment else 'normal'
            })
            
            summary['total_value_bob'] += value
        
        return Response(summary)
    
    @action(detail=True, methods=['POST'])
    def adjust(self, request, pk=None):
        """Ajusta el inventario"""
        inventory = self.get_object()
        serializer = InventoryAdjustmentSerializer(data=request.data)
        
        if serializer.is_valid():
            data = serializer.validated_data
            
            inventory.adjust_inventory(
                physical_count=data['physical_count'],
                digital_count=data['digital_count'],
                user=request.user,
                reason=data['reason']
            )
            
            return Response({
                'success': True,
                'new_balance': {
                    'physical': float(inventory.physical_balance),
                    'digital': float(inventory.digital_balance),
                    'total': float(inventory.total_balance)
                }
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['GET'])
    def movements(self, request, pk=None):
        """Obtiene movimientos del inventario"""
        inventory = self.get_object()
        
        # Filtros
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        movement_type = request.query_params.get('type')
        
        movements = inventory.movements.all()
        
        if date_from:
            movements = movements.filter(created_at__gte=date_from)
        if date_to:
            movements = movements.filter(created_at__lte=date_to)
        if movement_type:
            movements = movements.filter(movement_type=movement_type)
        
        page = self.paginate_queryset(movements)
        if page is not None:
            serializer = InventoryMovementSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = InventoryMovementSerializer(movements, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['POST'])
    def transfer(self, request, pk=None):
        """Inicia transferencia a otra sucursal"""
        inventory = self.get_object()
        
        target_branch_id = request.data.get('target_branch_id')
        amount = request.data.get('amount')
        notes = request.data.get('notes', '')
        
        if not all([target_branch_id, amount]):
            return Response(
                {'error': 'Faltan datos requeridos'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            amount = Decimal(str(amount))
            
            # Crear transferencia
            transfer = InventoryTransfer.objects.create(
                currency=inventory.currency,
                source_branch=inventory.branch,
                target_branch_id=target_branch_id,
                amount=amount,
                rate=inventory.weighted_average_cost,
                requested_by=request.user,
                notes=notes
            )
            
            # Si el usuario es admin o supervisor, autorizar automáticamente
            if request.user.role in ['ADMIN', 'SUPERVISOR']:
                transfer.authorized_by = request.user
                transfer.authorized_at = timezone.now()
                transfer.status = 'IN_TRANSIT'
                transfer.save()
                
                # Realizar la transferencia
                inventory.transfer_to_branch(
                    transfer.target_branch,
                    amount,
                    request.user
                )
            
            return Response(
                InventoryTransferSerializer(transfer).data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

class InventoryTransferViewSet(viewsets.ModelViewSet):
    queryset = InventoryTransfer.objects.all()
    serializer_class = InventoryTransferSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros
        transfer_status = self.request.query_params.get('status')
        branch_id = self.request.query_params.get('branch_id')

        if transfer_status:
            queryset = queryset.filter(status=transfer_status)
        
        if branch_id:
            queryset = queryset.filter(
                Q(source_branch_id=branch_id) | Q(target_branch_id=branch_id)
            )
        
        return queryset.select_related(
            'currency', 'source_branch', 'target_branch',
            'requested_by', 'authorized_by', 'received_by'
        )
    
    @action(detail=True, methods=['POST'])
    def authorize(self, request, pk=None):
        """Autoriza una transferencia pendiente"""
        transfer = self.get_object()
        
        if request.user.role not in ['ADMIN', 'SUPERVISOR']:
            return Response(
                {'error': 'No autorizado'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if transfer.status != 'PENDING':
            return Response(
                {'error': 'La transferencia no está pendiente'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Autorizar
        transfer.authorized_by = request.user
        transfer.authorized_at = timezone.now()
        transfer.status = 'IN_TRANSIT'
        transfer.save()
        
        # Ejecutar transferencia
        try:
            source_inventory = CurrencyInventory.objects.get(
                currency=transfer.currency,
                branch=transfer.source_branch
            )
            source_inventory.transfer_to_branch(
                transfer.target_branch,
                transfer.amount,
                request.user
            )
            
            return Response({'success': True})
            
        except Exception as e:
            transfer.status = 'CANCELLED'
            transfer.save()
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['POST'])
    def receive(self, request, pk=None):
        """Confirma recepción de transferencia"""
        transfer = self.get_object()
        
        if transfer.status != 'IN_TRANSIT':
            return Response(
                {'error': 'La transferencia no está en tránsito'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if request.user.branch != transfer.target_branch:
            return Response(
                {'error': 'Solo puede recibir personal de la sucursal destino'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        transfer.received_by = request.user
        transfer.completed_at = timezone.now()
        transfer.status = 'COMPLETED'
        transfer.save()
        
        return Response({'success': True})

class InventoryAlertViewSet(viewsets.ModelViewSet):
    queryset = InventoryAlert.objects.all()
    serializer_class = InventoryAlertSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros
        is_resolved = self.request.query_params.get('is_resolved')
        severity = self.request.query_params.get('severity')
        alert_type = self.request.query_params.get('type')
        
        if is_resolved is not None:
            queryset = queryset.filter(is_resolved=is_resolved == 'true')
        if severity:
            queryset = queryset.filter(severity=severity)
        if alert_type:
            queryset = queryset.filter(alert_type=alert_type)
        
        # Filtrar por sucursal si no es admin
        if self.request.user.role != 'ADMIN':
            queryset = queryset.filter(inventory__branch=self.request.user.branch)
        
        return queryset.select_related(
            'inventory__currency',
            'inventory__branch',
            'triggered_by',
            'resolved_by'
        )
    
    @action(detail=False, methods=['GET'])
    def active(self, request):
        """Obtiene alertas activas"""
        alerts = self.get_queryset().filter(is_resolved=False)
        
        # Agrupar por severidad
        summary = {
            'critical': alerts.filter(severity='CRITICAL').count(),
            'high': alerts.filter(severity='HIGH').count(),
            'medium': alerts.filter(severity='MEDIUM').count(),
            'low': alerts.filter(severity='LOW').count(),
            'alerts': self.get_serializer(alerts[:10], many=True).data
        }
        
        return Response(summary)
    
    @action(detail=True, methods=['POST'])
    def resolve(self, request, pk=None):
        """Resuelve una alerta"""
        alert = self.get_object()
        notes = request.data.get('notes', '')
        
        if alert.is_resolved:
            return Response(
                {'error': 'La alerta ya está resuelta'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        alert.resolve(request.user, notes)
        
        return Response({'success': True})
    
    @action(detail=False, methods=['POST'])
    def check_all(self, request):
        """Ejecuta verificación de todos los inventarios"""
        if request.user.role != 'ADMIN':
            return Response(
                {'error': 'No autorizado'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        alerts_created = InventoryAlertService.check_all_inventories()

        return Response({
            'alerts_created': len(alerts_created),
            'alerts': InventoryAlertSerializer(alerts_created, many=True).data
        })


class InventoryMovementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InventoryMovementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = InventoryMovement.objects.select_related(
            'inventory__currency', 'inventory__branch', 'user'
        ).order_by('-created_at')

        if self.request.user.role != 'ADMIN':
            qs = qs.filter(inventory__branch=self.request.user.branch)

        currency     = self.request.query_params.get('currency')
        mov_type     = self.request.query_params.get('type')
        date_from    = self.request.query_params.get('date_from')
        date_to      = self.request.query_params.get('date_to')
        inventory_id = self.request.query_params.get('inventory_id')

        if currency:
            qs = qs.filter(inventory__currency__code=currency)
        if mov_type:
            qs = qs.filter(movement_type=mov_type)
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)
        if inventory_id:
            qs = qs.filter(inventory_id=inventory_id)

        return qs


class InventoryCardViewSet(viewsets.ModelViewSet):
    queryset = InventoryCard.objects.all()
    serializer_class = InventoryCardSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        currency = self.request.query_params.get('currency')
        status   = self.request.query_params.get('status')
        if currency:
            queryset = queryset.filter(currency__iexact=currency)
        if status:
            queryset = queryset.filter(status=status)
        return queryset