from rest_framework import serializers
from .models import Transaction, Customer, TransactionDocument
from users.serializers import UserSerializer, BranchSerializer
from rates.serializers import CurrencySerializer


class CustomerSerializer(serializers.ModelSerializer):
    transaction_count = serializers.SerializerMethodField()
    total_volume      = serializers.SerializerMethodField()

    class Meta:
        model  = Customer
        fields = [
            'id', 'document_type', 'document_number', 'full_name',
            'phone', 'email', 'address', 'birth_date', 'nationality',
            'is_pep', 'is_frequent', 'notes',
            'transaction_count', 'total_volume',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']
    def get_transaction_count(self, obj):
        return obj.transaction_count  # usa la @property

    def get_total_volume(self, obj):
        return float(obj.total_volume) if obj.total_volume else 0

class TransactionDocumentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField()

    class Meta:
        model  = TransactionDocument
        fields = ['id', 'document_type', 'file', 'description',
                  'uploaded_by', 'uploaded_at']
        read_only_fields = ['uploaded_at']


class TransactionSerializer(serializers.ModelSerializer):
    customer      = CustomerSerializer(read_only=True)
    currency_from = CurrencySerializer(read_only=True)
    currency_to   = CurrencySerializer(read_only=True)
    cashier       = UserSerializer(read_only=True)
    supervisor    = UserSerializer(read_only=True)
    branch        = BranchSerializer(read_only=True)
    documents     = TransactionDocumentSerializer(many=True, read_only=True)
    profit_margin       = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True)
    requires_supervisor = serializers.BooleanField(read_only=True)

    class Meta:
        model  = Transaction
        fields = [
            'id', 'transaction_number', 'transaction_type', 'status',
            'customer', 'currency_from', 'currency_to',
            'amount_from', 'amount_to', 'exchange_rate',
            'payment_method', 'payment_reference',
            'cashier', 'supervisor', 'branch',
            'notes', 'receipt_number',
            'profit_margin', 'requires_supervisor',
            'documents',
            'created_at', 'updated_at', 'completed_at',
        ]
        read_only_fields = [
            'transaction_number', 'created_at', 'updated_at', 'completed_at']


class TransactionCreateSerializer(serializers.ModelSerializer):
    customer_id     = serializers.PrimaryKeyRelatedField(
        queryset=__import__('transactions.models', fromlist=['Customer']).Customer.objects.all(),
        source='customer')
    currency_from_id = serializers.PrimaryKeyRelatedField(
        queryset=__import__('rates.models', fromlist=['Currency']).Currency.objects.all(),
        source='currency_from')
    currency_to_id = serializers.PrimaryKeyRelatedField(
        queryset=__import__('rates.models', fromlist=['Currency']).Currency.objects.all(),
        source='currency_to')

    class Meta:
        model  = Transaction
        fields = [
            'transaction_type', 'customer_id',
            'currency_from_id', 'currency_to_id',
            'amount_from', 'amount_to', 'exchange_rate',
            'payment_method', 'payment_reference', 'notes',
        ]