from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.utils import timezone
from django.core.cache import cache
from .models import Currency, ExchangeRate, RateConfiguration
from .serializers import CurrencySerializer, ExchangeRateSerializer, RateConfigurationSerializer
from .services import RateService

class CurrencyViewSet(viewsets.ModelViewSet):
    queryset = Currency.objects.filter(is_active=True)
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticated]

class ExchangeRateViewSet(viewsets.ModelViewSet):
    queryset = ExchangeRate.objects.all()
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros opcionales
        currency_from = self.request.query_params.get('currency_from')
        currency_to = self.request.query_params.get('currency_to')
        active_only = self.request.query_params.get('active_only', 'true')
        
        if currency_from:
            queryset = queryset.filter(currency_from__code=currency_from)
        if currency_to:
            queryset = queryset.filter(currency_to__code=currency_to)
        if active_only.lower() == 'true':
            queryset = queryset.filter(valid_until__isnull=True)
        
        return queryset.select_related('currency_from', 'currency_to')
    
    @action(detail=False, methods=['GET'], permission_classes=[AllowAny])
    def current(self, request):
        """Obtiene todas las tasas actuales"""
        # Intentar obtener del cache primero
        cached_rates = cache.get('all_current_rates')
        if cached_rates:
            return Response(cached_rates)
        
        service = RateService()
        rates = {}
        
        for currency in Currency.objects.filter(is_active=True).exclude(code='BOB'):
            rate_data = service.get_current_rates(currency.code)
            if rate_data:
                rates[currency.code] = rate_data
        
        # Cache por 5 minutos
        cache.set('all_current_rates', rates, 300)
        
        return Response(rates)
    
    @action(detail=False, methods=['POST'])
    def update_rates(self, request):
        """Actualiza las tasas desde fuentes externas"""
        if request.user.role != 'ADMIN':
            return Response(
                {'error': 'Solo administradores pueden actualizar tasas'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        source = request.data.get('source', 'BCB')
        service = RateService()
        
        try:
            rates = service.fetch_official_rates(source)
            return Response({
                'success': True,
                'rates': rates,
                'source': source,
                'timestamp': timezone.now()
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['POST'], permission_classes=[AllowAny])
    def calculate(self, request):
        """Calcula el cambio de divisas"""
        amount = request.data.get('amount')
        currency_from = request.data.get('currency_from')
        currency_to = request.data.get('currency_to', 'BOB')
        transaction_type = request.data.get('transaction_type')
        
        if not all([amount, currency_from, transaction_type]):
            return Response(
                {'error': 'Faltan parámetros requeridos'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            service = RateService()
            result = service.calculate_exchange(
                Decimal(str(amount)),
                currency_from,
                currency_to,
                transaction_type
            )
            return Response(result)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

class RateConfigurationViewSet(viewsets.ModelViewSet):
    queryset = RateConfiguration.objects.all()
    serializer_class = RateConfigurationSerializer
    permission_classes = [IsAuthenticated]
    
    def update(self, request, *args, **kwargs):
        """Solo administradores pueden actualizar configuraciones"""
        if request.user.role != 'ADMIN':
            return Response(
                {'error': 'No autorizado'},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)