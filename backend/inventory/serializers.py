from rest_framework import serializers
from .models import CurrencyInventory, InventoryMovement, InventoryTransfer
from .alerts import InventoryAlert
from rates.serializers import CurrencySerializer
from users.serializers import BranchSerializer, UserSerializer


class InventoryMovementSerializer(serializers.ModelSerializer):
    user  = serializers.StringRelatedField()
    value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model  = InventoryMovement
        fields = [
            'id', 'movement_type', 'amount', 'rate',
            'balance_before', 'balance_after',
            'reference', 'notes', 'user', 'value', 'created_at',
        ]
        read_only_fields = ['created_at']


class CurrencyInventorySerializer(serializers.ModelSerializer):
    currency               = CurrencySerializer(read_only=True)
    branch                 = BranchSerializer(read_only=True)
    total_balance          = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True)
    needs_replenishment    = serializers.BooleanField(read_only=True)
    is_overstocked         = serializers.BooleanField(read_only=True)
    stock_level_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model  = CurrencyInventory
        fields = [
            'id', 'currency', 'branch',
            'physical_balance', 'digital_balance', 'total_balance',
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


class InventoryAlertSerializer(serializers.Serializer):
    """Serializer básico para alertas — ajusta según tu modelo InventoryAlert."""
    id         = serializers.IntegerField(read_only=True)
    alert_type = serializers.CharField()
    severity   = serializers.CharField()
    is_resolved = serializers.BooleanField()
    created_at = serializers.DateTimeField(read_only=True)