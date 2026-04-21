from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate, update_session_auth_hash
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta
from .models import User, UserActivity, Branch
from .serializers import (
    UserSerializer, UserCreateSerializer, LoginSerializer,
    SignupSerializer, UserActivitySerializer, BranchSerializer,
)
from core.ratelimit import rate_limit


def _get_client_ip(request) -> str:
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR', '')


def _token_response(user: User, http_status=status.HTTP_200_OK) -> Response:
    """Build {access, refresh, user} response for any auth endpoint."""
    refresh = RefreshToken.for_user(user)
    return Response(
        {
            'access':  str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id':                    user.id,
                'username':              user.username,
                'email':                 user.email,
                'full_name':             user.get_full_name(),
                'role':                  user.role,
                'branch_id':             user.branch_id,
                'is_two_factor_enabled': user.is_two_factor_enabled,
                'is_verified':           user.is_verified,
            },
        },
        status=http_status,
    )


def _log_activity(user: User, action: str, request, extra: dict | None = None) -> None:
    try:
        UserActivity.objects.create(
            user       = user,
            action     = action,
            details    = extra or {},
            ip_address = _get_client_ip(request),
            user_agent = request.META.get('HTTP_USER_AGENT', ''),
        )
    except Exception:
        pass


# ── Signup ─────────────────────────────────────────────────────────────────────

class SignupView(APIView):
    permission_classes = [AllowAny]

    @rate_limit(requests=5, window=60, scope='ip')
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        _log_activity(user, 'SIGNUP', request, {'method': 'email'})
        return _token_response(user, status.HTTP_201_CREATED)


# ── Google OAuth ───────────────────────────────────────────────────────────────

class GoogleAuthView(APIView):
    permission_classes = [AllowAny]

    @rate_limit(requests=10, window=60, scope='ip')
    def post(self, request):
        credential = request.data.get('credential')
        if not credential:
            return Response({'error': 'credential requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from google.oauth2 import id_token
            from google.auth.transport import requests as google_requests
            from django.conf import settings as django_settings

            id_info = id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                django_settings.GOOGLE_CLIENT_ID,
            )
        except ValueError as exc:
            return Response({'error': f'Token inválido: {exc}'}, status=status.HTTP_401_UNAUTHORIZED)

        email = id_info.get('email', '').lower()
        if not email:
            return Response({'error': 'No se pudo obtener email de Google'}, status=status.HTTP_400_BAD_REQUEST)

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'username':    email.split('@')[0],
                'first_name':  id_info.get('given_name', ''),
                'last_name':   id_info.get('family_name', ''),
                'role':        'CASHIER',
                'is_active':   True,
                'is_verified': True,
            },
        )
        if created:
            user.set_unusable_password()
            user.save()

        if not user.is_active:
            return Response({'error': 'Cuenta inactiva'}, status=status.HTTP_403_FORBIDDEN)

        _log_activity(user, 'LOGIN', request, {'method': 'google', 'created': created})
        return _token_response(user)


# ── JWT Login (email/username + lockout) ───────────────────────────────────────

class ForexTokenView(TokenObtainPairView):
    """
    Login endpoint.
    Rate limit: 10 req/min/IP.
    Account lockout: 5 failed attempts → 15-min block.
    Returns: {access, refresh, user}.
    """
    permission_classes = [AllowAny]
    serializer_class   = TokenObtainPairSerializer

    @rate_limit(requests=10, window=60, scope='ip')
    def post(self, request, *args, **kwargs):
        username = request.data.get('username', '')

        candidate = _resolve_user(username)
        if candidate and candidate.is_locked_out():
            remaining = int((candidate.lockout_until - timezone.now()).total_seconds() / 60) + 1
            return Response(
                {'error': f'Cuenta bloqueada. Intenta en {remaining} min.', 'code': 'ACCOUNT_LOCKED'},
                status=status.HTTP_403_FORBIDDEN,
            )

        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            password = request.data.get('password', '')
            user     = authenticate(request, username=username, password=password)
            if user:
                user.reset_login_attempts()
                _log_activity(user, 'LOGIN', request, {'method': 'jwt'})
                response.data['user'] = {
                    'id':                    user.id,
                    'username':              user.username,
                    'email':                 user.email,
                    'full_name':             user.get_full_name(),
                    'role':                  user.role,
                    'branch_id':             user.branch_id,
                    'is_two_factor_enabled': user.is_two_factor_enabled,
                    'is_verified':           user.is_verified,
                }
        else:
            if candidate:
                candidate.record_failed_login()

        return response


def _resolve_user(username: str) -> User | None:
    if not username:
        return None
    try:
        return User.objects.get(email=username.lower()) if '@' in username \
               else User.objects.get(username=username)
    except User.DoesNotExist:
        return None


# ── Users ViewSet ──────────────────────────────────────────────────────────────

class UserViewSet(viewsets.ModelViewSet):
    queryset           = User.objects.all()
    serializer_class   = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset().select_related('branch')
        if self.request.user.role != 'ADMIN':
            qs = qs.filter(branch=self.request.user.branch)
        return qs

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return UserCreateSerializer
        return UserSerializer

    @action(detail=False, methods=['GET'], url_path='me')
    def me(self, request):
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=['POST'], permission_classes=[AllowAny])
    def login(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        _log_activity(user, 'LOGIN', request, {'method': 'password'})
        return _token_response(user)

    @action(detail=False, methods=['POST'], url_path='verify-pin')
    def verify_pin(self, request):
        pin = request.data.get('pin')
        if not pin:
            return Response({'error': 'PIN requerido'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.check_pin(pin):
            _log_activity(request.user, 'PIN_VERIFIED', request)
            return Response({'valid': True})
        return Response({'valid': False}, status=status.HTTP_401_UNAUTHORIZED)

    @action(detail=False, methods=['POST'], url_path='enable-two-factor')
    def enable_two_factor(self, request):
        if request.user.is_two_factor_enabled:
            return Response({'error': '2FA ya habilitado'}, status=status.HTTP_400_BAD_REQUEST)
        secret  = request.user.generate_two_factor_secret()
        qr_code = request.user.get_two_factor_qr_code()
        return Response({'secret': secret, 'qr_code': qr_code})

    @action(detail=False, methods=['POST'], url_path='confirm-two-factor')
    def confirm_two_factor(self, request):
        token = request.data.get('token')
        if not token:
            return Response({'error': 'Token requerido'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.verify_two_factor_token(token):
            request.user.is_two_factor_enabled = True
            request.user.save()
            return Response({'message': '2FA habilitado'})
        return Response({'error': 'Token inválido'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['GET'], url_path='my-activities')
    def my_activities(self, request):
        activities = UserActivity.objects.filter(user=request.user).order_by('-timestamp')[:50]
        return Response(UserActivitySerializer(activities, many=True).data)

    @action(detail=False, methods=['POST'], url_path='set-pin')
    def set_pin(self, request):
        pin         = request.data.get('pin')
        current_pin = request.data.get('current_pin')
        if not pin or len(pin) < 4:
            return Response({'error': 'PIN mínimo 4 dígitos'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.pin and current_pin and not request.user.check_pin(current_pin):
            return Response({'error': 'PIN actual incorrecto'}, status=status.HTTP_400_BAD_REQUEST)
        request.user.set_pin(pin)
        return Response({'success': True})

    @action(detail=False, methods=['POST'], url_path='change-password')
    def change_password(self, request):
        old_pw = request.data.get('old_password')
        new_pw = request.data.get('new_password')
        if not old_pw or not new_pw:
            return Response({'error': 'Campos requeridos'}, status=status.HTTP_400_BAD_REQUEST)
        if not request.user.check_password(old_pw):
            return Response({'error': 'Contraseña actual incorrecta'}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_pw) < 8:
            return Response({'error': 'Mínimo 8 caracteres'}, status=status.HTTP_400_BAD_REQUEST)
        request.user.set_password(new_pw)
        request.user.save()
        update_session_auth_hash(request, request.user)
        return Response({'success': True})

    @action(detail=True, methods=['POST'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        if request.user.role != 'ADMIN':
            return Response({'error': 'Sin permisos'}, status=403)
        user   = self.get_object()
        new_pw = request.data.get('new_password')
        if not new_pw or len(new_pw) < 8:
            return Response({'error': 'Contraseña inválida'}, status=400)
        user.set_password(new_pw)
        user.save()
        return Response({'success': True})

    @action(detail=True, methods=['GET'], url_path='activities')
    def activities(self, request, pk=None):
        if request.user.role != 'ADMIN':
            return Response({'error': 'Sin permisos'}, status=403)
        acts = UserActivity.objects.filter(user=self.get_object()).order_by('-timestamp')[:100]
        return Response(UserActivitySerializer(acts, many=True).data)

    @action(detail=False, methods=['GET'], url_path='branches')
    def branches(self, request):
        return Response(BranchSerializer(Branch.objects.filter(is_active=True), many=True).data)


# ── Dashboard Stats ────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    from transactions.models import Transaction
    from rates.models import ExchangeRate, Currency

    today     = timezone.now().date()
    yesterday = today - timedelta(days=1)

    tx_qs = Transaction.objects.filter(status='COMPLETED')
    if request.user.role != 'ADMIN':
        tx_qs = tx_qs.filter(branch=request.user.branch)

    today_txs     = tx_qs.filter(created_at__date=today)
    yesterday_txs = tx_qs.filter(created_at__date=yesterday)

    today_count     = today_txs.count()
    yesterday_count = yesterday_txs.count()
    count_change    = (
        (today_count - yesterday_count) / yesterday_count * 100 if yesterday_count else 0
    )

    today_volume  = float(today_txs.aggregate(s=Sum('amount_to'))['s'] or 0)
    yesterday_vol = float(yesterday_txs.aggregate(s=Sum('amount_to'))['s'] or 0)
    volume_change = (
        (today_volume - yesterday_vol) / yesterday_vol * 100 if yesterday_vol else 0
    )

    buy_vol  = float(today_txs.filter(transaction_type='BUY').aggregate(s=Sum('amount_to'))['s'] or 0)
    sell_vol = float(today_txs.filter(transaction_type='SELL').aggregate(s=Sum('amount_to'))['s'] or 0)

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

    by_hour = [
        {'hour': f'{h:02d}:00', 'count': today_txs.filter(created_at__hour=h).count()}
        for h in range(9, 19)
    ]

    recent = (today_txs.select_related('customer', 'currency_from', 'cashier')
              .order_by('-created_at')[:5])

    return Response({
        'today_transactions':    today_count,
        'count_change_pct':      round(count_change, 1),
        'today_volume_bob':      today_volume,
        'volume_change_pct':     round(volume_change, 1),
        'today_profit_bob':      sell_vol - buy_vol,
        'unique_customers':      today_txs.values('customer').distinct().count(),
        'current_rates':         current_rates,
        'transactions_by_hour':  by_hour,
        'recent_transactions': [{
            'id':                 t.id,
            'transaction_number': t.transaction_number,
            'customer':           t.customer.full_name,
            'type':               t.transaction_type,
            'currency':           t.currency_from.code,
            'amount':             float(t.amount_from),
            'total_bob':          float(t.amount_to),
            'created_at':         t.created_at.isoformat(),
        } for t in recent],
    })
