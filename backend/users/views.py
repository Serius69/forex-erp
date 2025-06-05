from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login
from .models import User, UserActivity
from .serializers import UserSerializer, LoginSerializer, UserActivitySerializer

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
    
    @action(detail=False, methods=['POST'])
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
    
    @action(detail=False, methods=['POST'])
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
    
    @action(detail=False, methods=['POST'])
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
    
    @action(detail=False, methods=['GET'])
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