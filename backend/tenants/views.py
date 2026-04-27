from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import Company, Subscription
from .serializers import CompanySerializer, SubscriptionSerializer
from .permissions import IsCompanyMember, IsAdminRole, IsAdminOrSupervisor


class CompanyViewSet(viewsets.ModelViewSet):
    serializer_class   = CompanySerializer
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'is_superuser', False):
            return Company.objects.all()
        return Company.objects.filter(id=user.company_id)

    def get_permissions(self):
        if self.action in ('create', 'destroy'):
            return [IsAuthenticated(), IsAdminRole()]
        if self.action in ('update', 'partial_update'):
            return [IsAuthenticated(), IsCompanyMember(), IsAdminRole()]
        return super().get_permissions()

    @action(detail=True, methods=['get'], url_path='subscription')
    def subscription(self, request, pk=None):
        company = self.get_object()
        sub, _ = Subscription.objects.get_or_create(company=company)
        return Response(SubscriptionSerializer(sub).data)

    @action(detail=True, methods=['get'], url_path='stats')
    def stats(self, request, pk=None):
        """Quick company-level stats: branch count, user count, tx count."""
        company = self.get_object()
        from users.models import Branch
        from django.contrib.auth import get_user_model
        User = get_user_model()

        branches = Branch.objects.filter(company=company, is_active=True).count()
        users    = User.objects.filter(company=company, is_active=True).count()

        try:
            from transactions.models import Transaction
            from django.utils import timezone
            from datetime import timedelta
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            txs_today   = Transaction.objects.filter(
                branch__company=company,
                created_at__gte=today_start,
            ).count()
        except Exception:
            txs_today = 0

        return Response({
            'branches':        branches,
            'users':           users,
            'transactions_today': txs_today,
        })
