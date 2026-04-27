"""
CompanyFilterMixin — attach to any ModelViewSet to enforce tenant isolation.

For models with a direct `company` FK:
    queryset_company_field = 'company'   (default)

For models that reach company through branch:
    queryset_company_field = 'branch__company'

For CASHIER role, additionally restrict to the user's branch:
    branch_field = 'branch'              (default; set to None to skip)

Usage:
    class TransactionViewSet(CompanyFilterMixin, ModelViewSet):
        queryset_company_field = 'branch__company'
        branch_field           = 'branch'
"""
from django.db.models import QuerySet


class CompanyFilterMixin:
    queryset_company_field: str = 'company'
    branch_field: str | None    = 'branch'

    # ------------------------------------------------------------------
    def get_queryset(self) -> QuerySet:
        qs = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated or not getattr(user, 'company_id', None):
            return qs.none()

        # 1. Tenant isolation — always filter by company
        qs = qs.filter(**{self.queryset_company_field: user.company_id})

        # 2. Branch isolation for CASHIER role
        if (
            self.branch_field
            and getattr(user, 'role', 'CASHIER') == 'CASHIER'
            and getattr(user, 'branch_id', None)
        ):
            qs = qs.filter(**{self.branch_field: user.branch_id})

        return qs

    # ------------------------------------------------------------------
    def perform_create(self, serializer):
        """Auto-inject company (and branch for cashiers) on create."""
        user = self.request.user
        extra: dict = {}

        # Inject company if the model has a direct company FK
        if self.queryset_company_field == 'company':
            extra['company'] = user.company

        # Inject branch if the serializer field exists and user has a branch
        if (
            self.branch_field == 'branch'
            and 'branch' not in serializer.validated_data
            and getattr(user, 'branch_id', None)
        ):
            from users.models import Branch
            extra['branch'] = user.branch

        serializer.save(**extra)
