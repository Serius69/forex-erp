from rest_framework import serializers
from .models import (CashTransactionReport, SuspiciousActivityReport,
                     PEPRegistry, DailyOperationLog, GeneratedReport)
from users.serializers import UserSerializer
from transactions.serializers import CustomerSerializer
from transactions.models import Customer


class RTESerializer(serializers.ModelSerializer):
    submitted_by = UserSerializer(read_only=True)

    class Meta:
        model  = CashTransactionReport
        fields = [
            'id', 'report_number', 'report_date',
            'amount_usd_equiv', 'currency_code',
            'original_amount', 'exchange_rate_usd',
            'customer_full_name', 'customer_document_type',
            'customer_document_num', 'customer_nationality',
            'customer_is_pep', 'status', 'asfi_reference',
            'submitted_by', 'submitted_at', 'notes', 'created_at',
        ]
        read_only_fields = ['report_number', 'created_at']


class ROUESerializer(serializers.ModelSerializer):
    customer     = CustomerSerializer(read_only=True)
    detected_by  = UserSerializer(read_only=True)
    reviewed_by  = UserSerializer(read_only=True)
    submitted_by = UserSerializer(read_only=True)

    class Meta:
        model  = SuspiciousActivityReport
        fields = [
            'id', 'report_number', 'report_type', 'risk_level', 'status',
            'customer', 'description', 'indicators',
            'amount_involved', 'currency_involved',
            'detected_by', 'reviewed_by', 'submitted_by',
            'asfi_reference', 'internal_notes',
            'detected_at', 'reviewed_at', 'submitted_at',
        ]
        read_only_fields = ['report_number', 'detected_at']


class CreateROUESerializer(serializers.ModelSerializer):
    customer_id = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(),
        source='customer')

    class Meta:
        model  = SuspiciousActivityReport
        fields = [
            'report_type', 'risk_level', 'customer_id',
            'description', 'indicators',
            'amount_involved', 'currency_involved',
        ]

    def create(self, validated_data):
        validated_data['detected_by'] = self.context['request'].user
        return super().create(validated_data)


class PEPSerializer(serializers.ModelSerializer):
    customer      = CustomerSerializer(read_only=True)
    registered_by = UserSerializer(read_only=True)
    is_active     = serializers.BooleanField(read_only=True)

    class Meta:
        model  = PEPRegistry
        fields = [
            'id', 'customer', 'position', 'institution',
            'since_date', 'until_date', 'risk_level',
            'enhanced_dd', 'review_date', 'notes',
            'registered_by', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class CreatePEPSerializer(serializers.ModelSerializer):
    customer_id = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(),
        source='customer')

    class Meta:
        model  = PEPRegistry
        fields = [
            'customer_id', 'position', 'institution',
            'since_date', 'until_date', 'risk_level',
            'enhanced_dd', 'review_date', 'notes',
        ]

    def create(self, validated_data):
        validated_data['registered_by'] = self.context['request'].user
        return super().create(validated_data)


class DailyLogSerializer(serializers.ModelSerializer):
    closed_by = UserSerializer(read_only=True)

    class Meta:
        model  = DailyOperationLog
        fields = [
            'id', 'log_date', 'branch', 'status',
            'total_transactions',
            'total_buy_bob', 'total_sell_bob', 'total_profit_bob',
            'rte_count',
            'opening_balance_bob', 'closing_balance_bob',
            'excel_file', 'pdf_file',
            'closed_by', 'closed_at', 'created_at', 'notes',
        ]
        read_only_fields = ['created_at']


class GeneratedReportSerializer(serializers.ModelSerializer):
    generated_by = UserSerializer(read_only=True)

    class Meta:
        model  = GeneratedReport
        fields = [
            'id', 'report_type', 'format',
            'date_from', 'date_to',
            'file_path', 'file_size_kb',
            'generated_by', 'generated_at', 'parameters',
        ]
        read_only_fields = ['generated_at']