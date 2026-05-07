from django.contrib import admin
from .models import Transaction, Customer, TransactionDocument, TransactionAuditLog, FraudRule


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display  = ['transaction_number', 'transaction_type', 'status', 'currency_from',
                     'amount_from', 'exchange_rate', 'fraud_score', 'approval_required',
                     'cashier', 'branch', 'created_at']
    list_filter   = ['status', 'transaction_type', 'transaction_category',
                     'approval_required', 'branch']
    search_fields = ['transaction_number', 'nombre_cliente', 'carnet_identidad']
    readonly_fields = ['transaction_number', 'created_at', 'updated_at', 'completed_at',
                       'fraud_score', 'fraud_flags', 'parallel_rate_at_creation',
                       'rate_lock_expires_at', 'approved_by', 'approved_at']
    date_hierarchy = 'created_at'
    ordering       = ['-created_at']


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display  = ['full_name', 'document_type', 'document_number', 'is_pep', 'is_frequent', 'company']
    list_filter   = ['document_type', 'is_pep', 'is_frequent', 'company']
    search_fields = ['full_name', 'document_number', 'email', 'phone']


@admin.register(FraudRule)
class FraudRuleAdmin(admin.ModelAdmin):
    list_display  = ['name', 'rule_type', 'threshold', 'decision', 'score_delta', 'is_active']
    list_filter   = ['rule_type', 'decision', 'is_active']
    list_editable = ['threshold', 'decision', 'score_delta', 'is_active']
    search_fields = ['name', 'description']
    ordering      = ['rule_type', 'name']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Invalidar caché para que workers recarguen inmediatamente
        try:
            from django.core.cache import cache
            cache.delete('fraud_rules_active')
        except Exception:
            pass


@admin.register(TransactionAuditLog)
class TransactionAuditLogAdmin(admin.ModelAdmin):
    list_display  = ['transaction_number', 'action', 'user_display', 'ip_address',
                     'timestamp_utc', 'checksum_sha256']
    list_filter   = ['action']
    search_fields = ['transaction_number', 'user_display', 'ip_address']
    readonly_fields = [f.name for f in TransactionAuditLog._meta.get_fields()
                       if hasattr(f, 'name')]
    ordering      = ['-timestamp_utc']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
