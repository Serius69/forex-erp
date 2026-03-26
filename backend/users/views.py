from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login
from .models import User, UserActivity
from .serializers import UserSerializer, LoginSerializer, UserActivitySerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from rest_framework.decorators import api_view, permission_classes
from transactions.models import Transaction
from rates.models import ExchangeRate, Currency

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtrar por sucursal si no es admin
        if self.request.user.role != 'ADMIN':
            queryset = queryset.filter(branch=self.request.user.branch)
        
        return queryset
    
    @action(detail=False, methods=['GET'], url_path='me')
    def me(self, request):
        """Retorna el usuario autenticado actual."""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
    
    @action(detail=False, methods=['POST'], permission_classes=[AllowAny])
    def login(self, request):
        """Login personalizado con soporte para PIN y 2FA"""
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        
        # Registrar actividad
        UserActivity.objects.create(
            user=user,
            action='LOGIN',
            details={'method': 'password'},
            ip_address=self.get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        # Generar tokens
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': UserSerializer(user).data,
            'tokens': {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }
        })
    
    @action(detail=False, methods=['POST'], url_path='verify-pin')
    def verify_pin(self, request):
        """Verifica el PIN del usuario para operaciones sensibles"""
        pin = request.data.get('pin')
        
        if not pin:
            return Response(
                {'error': 'PIN requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if request.user.check_pin(pin):
            # Registrar actividad
            UserActivity.objects.create(
                user=request.user,
                action='PIN_VERIFIED',
                details={'success': True},
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
            
            return Response({'valid': True})
        
        return Response({'valid': False}, status=status.HTTP_401_UNAUTHORIZED)
    
    @action(detail=False, methods=['POST'], url_path='enable-two-factor')
    def enable_two_factor(self, request):
        """Habilita autenticación de dos factores"""
        user = request.user
        
        if user.is_two_factor_enabled:
            return Response(
                {'error': '2FA ya está habilitado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        secret = user.generate_two_factor_secret()
        qr_code = user.get_two_factor_qr_code()
        
        return Response({
            'secret': secret,
            'qr_code': qr_code,
            'instructions': 'Escanea el código QR con tu app de autenticación'
        })
    
    @action(detail=False, methods=['POST'], url_path='confirm-two-factor')
    def confirm_two_factor(self, request):
        """Confirma la habilitación de 2FA"""
        token = request.data.get('token')
        
        if not token:
            return Response(
                {'error': 'Token requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if request.user.verify_two_factor_token(token):
            request.user.is_two_factor_enabled = True
            request.user.save()
            
            return Response({'message': '2FA habilitado exitosamente'})
        
        return Response(
            {'error': 'Token inválido'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    @action(detail=False, methods=['GET'], url_path='my-activities')
    def my_activities(self, request):
        """Obtiene las actividades del usuario actual"""
        activities = UserActivity.objects.filter(
            user=request.user
        ).order_by('-timestamp')[:50]
        
        serializer = UserActivitySerializer(activities, many=True)
        return Response(serializer.data)
    
    def get_client_ip(self, request):
        """Obtiene la IP del cliente"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    @action(detail=False, methods=['POST'], url_path='set-pin')
    def set_pin(self, request):
        """Establece o actualiza el PIN del usuario"""
        pin         = request.data.get('pin')
        current_pin = request.data.get('current_pin')

        if not pin or len(pin) < 4:
            return Response(
                {'error': 'PIN debe tener al menos 4 dígitos'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Si ya tiene PIN, verificar el actual
        if request.user.pin and current_pin:
            if not request.user.check_pin(current_pin):
                return Response(
                    {'error': 'PIN actual incorrecto'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        request.user.set_pin(pin)
        return Response({'success': True, 'message': 'PIN actualizado'})

    @action(detail=False, methods=['POST'], url_path='change-password')
    def change_password(self, request):
        """Cambia la contraseña del usuario"""
        from django.contrib.auth import update_session_auth_hash
        old_password = request.data.get('old_password')
        new_password = request.data.get('new_password')

        if not old_password or not new_password:
            return Response(
                {'error': 'old_password y new_password son requeridos'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not request.user.check_password(old_password):
            return Response(
                {'error': 'Contraseña actual incorrecta'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(new_password) < 8:
            return Response(
                {'error': 'La contraseña debe tener al menos 8 caracteres'},
                status=status.HTTP_400_BAD_REQUEST
            )

        request.user.set_password(new_password)
        request.user.save()
        update_session_auth_hash(request, request.user)
        return Response({'success': True, 'message': 'Contraseña actualizada'})
    
    @action(detail=True, methods=['POST'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        """Admin resetea contraseña de un usuario"""
        if request.user.role != 'ADMIN':
            return Response({'error': 'Sin permisos'}, status=403)
        user        = self.get_object()
        new_password= request.data.get('new_password')
        if not new_password or len(new_password) < 8:
            return Response({'error': 'Contraseña inválida'}, status=400)
        user.set_password(new_password)
        user.save()
        return Response({'success': True})

    @action(detail=True, methods=['GET'], url_path='activities')
    def activities(self, request, pk=None):
        """Actividades de un usuario específico (solo ADMIN)"""
        if request.user.role != 'ADMIN':
            return Response({'error': 'Sin permisos'}, status=403)
        user       = self.get_object()
        activities = UserActivity.objects.filter(user=user).order_by('-timestamp')[:100]
        return Response(UserActivitySerializer(activities, many=True).data)


    from .models import User, UserActivity, Branch
    from .serializers import UserSerializer, UserActivitySerializer, BranchSerializer

    @action(detail=False, methods=['GET'], url_path='branches')
    def branches(self, request):
        """Lista de sucursales disponibles"""
        from .models import Branch
        from .serializers import BranchSerializer
        branches = Branch.objects.filter(is_active=True)
        return Response(BranchSerializer(branches, many=True).data)

from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    """Estadísticas para el dashboard principal."""
    from transactions.models import Transaction
    from rates.models import ExchangeRate, Currency

    today     = timezone.now().date()
    yesterday = today - timedelta(days=1)
    week_ago  = today - timedelta(days=7)

    # Filtrar por sucursal si no es admin
    tx_qs = Transaction.objects.filter(status='COMPLETED')
    if request.user.role != 'ADMIN':
        tx_qs = tx_qs.filter(branch=request.user.branch)

    # Transacciones de hoy
    today_txs      = tx_qs.filter(created_at__date=today)
    yesterday_txs  = tx_qs.filter(created_at__date=yesterday)

    today_count     = today_txs.count()
    yesterday_count = yesterday_txs.count()
    count_change    = (
        ((today_count - yesterday_count) / yesterday_count * 100)
        if yesterday_count else 0
    )

    # Volumen hoy en BOB
    today_volume    = float(today_txs.aggregate(s=Sum('amount_to'))['s'] or 0)
    yesterday_vol   = float(yesterday_txs.aggregate(s=Sum('amount_to'))['s'] or 0)
    volume_change   = (
        ((today_volume - yesterday_vol) / yesterday_vol * 100)
        if yesterday_vol else 0
    )

    # Utilidad hoy
    buy_vol  = float(today_txs.filter(transaction_type='BUY').aggregate(s=Sum('amount_to'))['s'] or 0)
    sell_vol = float(today_txs.filter(transaction_type='SELL').aggregate(s=Sum('amount_to'))['s'] or 0)
    profit   = sell_vol - buy_vol

    # Clientes únicos hoy
    unique_customers = today_txs.values('customer').distinct().count()

    # Tasas actuales
    current_rates = {}
    try:
        bob = Currency.objects.get(code='BOB')
        for rate in (ExchangeRate.objects
                     .filter(currency_to=bob, valid_until__isnull=True)
                     .select_related('currency_from')
                     .order_by('currency_from__code')):
            current_rates[rate.currency_from.code] = {
                'buy':      float(rate.buy_rate),
                'sell':     float(rate.sell_rate),
                'official': float(rate.official_rate),
            }
    except Currency.DoesNotExist:
        pass

    # Transacciones por hora (hoy)
    by_hour = []
    for hour in range(9, 19):  # 9am a 7pm
        count = today_txs.filter(created_at__hour=hour).count()
        by_hour.append({'hour': f'{hour:02d}:00', 'count': count})

    # Últimas 5 transacciones
    recent = today_txs.select_related(
        'customer', 'currency_from', 'cashier'
    ).order_by('-created_at')[:5]

    recent_data = [{
        'id':               t.id,
        'transaction_number': t.transaction_number,
        'customer':         t.customer.full_name,
        'type':             t.transaction_type,
        'currency':         t.currency_from.code,
        'amount':           float(t.amount_from),
        'total_bob':        float(t.amount_to),
        'created_at':       t.created_at.isoformat(),
    } for t in recent]

    return Response({
        'today_transactions':  today_count,
        'count_change_pct':    round(count_change, 1),
        'today_volume_bob':    today_volume,
        'volume_change_pct':   round(volume_change, 1),
        'today_profit_bob':    profit,
        'unique_customers':    unique_customers,
        'current_rates':       current_rates,
        'transactions_by_hour': by_hour,
        'recent_transactions': recent_data,
    })

class ForexTokenView(TokenObtainPairView):
    """
    Vista JWT personalizada para login del ERP.
    Extiende TokenObtainPairView para incluir datos del usuario
    y registrar actividad en el log.
    """
    permission_classes = [AllowAny]
    serializer_class   = TokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            # Obtener el usuario desde las credenciales
            from django.contrib.auth import authenticate
            username = request.data.get('username')
            password = request.data.get('password')
            user     = authenticate(request, username=username, password=password)

            if user:
                # Agregar datos del usuario a la respuesta
                response.data['user'] = {
                    'id':         user.id,
                    'username':   user.username,
                    'full_name':  user.get_full_name(),
                    'email':      user.email,
                    'role':       user.role,
                    'branch_id':  user.branch_id if hasattr(user, 'branch_id') else None,
                    'is_two_factor_enabled': getattr(user, 'is_two_factor_enabled', False),
                }

                # Registrar actividad de login
                try:
                    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
                    ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')

                    UserActivity.objects.create(
                        user=user,
                        action='LOGIN',
                        details={'method': 'jwt', 'endpoint': '/api/auth/login/'},
                        ip_address=ip,
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    )
                except Exception:
                    pass  # No interrumpir el login si falla el log

        return response
