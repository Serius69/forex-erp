from rest_framework import serializers
from .models import CurrencyInventory, InventoryMovement, InventoryTransfer, InventoryCard
from .alerts import InventoryAlert
from rates.serializers import CurrencySerializer
from users.serializers import BranchSerializer, UserSerializer


class InventoryMovementSerializer(serializers.ModelSerializer):
    user          = serializers.StringRelatedField()
    value         = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    currency_code = serializers.CharField(source='inventory.currency.code', read_only=True)
    branch_name   = serializers.CharField(source='inventory.branch.name',   read_only=True)

    class Meta:
        model  = InventoryMovement
        fields = [
            'id', 'movement_type', 'amount', 'rate',
            'balance_before', 'balance_after',
            'reference', 'notes', 'user', 'value',
            'currency_code', 'branch_name',
            'created_at',
        ]
        read_only_fields = ['created_at']


class CurrencyInventorySerializer(serializers.ModelSerializer):
    currency               = CurrencySerializer(read_only=True)
    branch                 = BranchSerializer(read_only=True)
    total_balance          = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True)
    real_total_balance     = serializers.DecimalField(
        max_digits=20, decimal_places=2, read_only=True,
        help_text='Saldo total en unidades reales (total_balance × scale_factor)')
    needs_replenishment    = serializers.BooleanField(read_only=True)
    is_overstocked         = serializers.BooleanField(read_only=True)
    stock_level_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model  = CurrencyInventory
        fields = [
            'id', 'currency', 'branch',
            'physical_balance', 'digital_balance', 'total_balance',
            'real_total_balance',
            'minimum_stock', 'maximum_stock', 'reorder_point',
            'weighted_average_cost',
            'needs_replenishment', 'is_overstocked', 'stock_level_percentage',
            'last_updated', 'last_recount',
        ]
        read_only_fields = ['last_updated']


class InventoryTransferSerializer(serializers.ModelSerializer):
    currency      = CurrencySerializer(read_only=True)
    source_branch = BranchSerializer(read_only=True)
    target_branch = BranchSerializer(read_only=True)
    requested_by  = UserSerializer(read_only=True)
    authorized_by = UserSerializer(read_only=True)
    received_by   = UserSerializer(read_only=True)

    class Meta:
        model  = InventoryTransfer
        fields = [
            'id', 'transfer_number',
            'currency', 'source_branch', 'target_branch',
            'amount', 'rate', 'status',
            'requested_by', 'authorized_by', 'received_by',
            'notes',
            'created_at', 'authorized_at', 'completed_at',
        ]
        read_only_fields = [
            'transfer_number', 'created_at', 'authorized_at', 'completed_at']


class InventoryAdjustmentSerializer(serializers.Serializer):
    physical_count = serializers.DecimalField(max_digits=15, decimal_places=2)
    digital_count  = serializers.DecimalField(max_digits=15, decimal_places=2)
    reason         = serializers.CharField(max_length=200)


class InventoryAlertSerializer(serializers.ModelSerializer):
    inventory_currency = serializers.SerializerMethodField()
    inventory_branch   = serializers.SerializerMethodField()
    triggered_by       = serializers.StringRelatedField()
    resolved_by        = serializers.StringRelatedField()

    class Meta:
        model  = InventoryAlert
        fields = [
            'id', 'alert_type', 'severity', 'message',
            'inventory_currency', 'inventory_branch',
            'is_resolved', 'data',
            'triggered_by', 'resolved_by',
            'created_at', 'resolved_at',
        ]
        read_only_fields = ['created_at', 'resolved_at']

    def get_inventory_currency(self, obj):
        return obj.inventory.currency.code if obj.inventory_id else None

    def get_inventory_branch(self, obj):
        return obj.inventory.branch.name if obj.inventory_id else None


class InventoryCardSerializer(serializers.ModelSerializer):
    class Meta:
        model  = InventoryCard
        fields = ['id', 'currency', 'amount', 'status', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']