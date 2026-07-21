# snapshots/serializers.py
from rest_framework import serializers
from .models import SystemSnapshot


class SystemSnapshotListSerializer(serializers.ModelSerializer):
    """Serializer compacto para listado — excluye data_json grande."""
    user_username  = serializers.CharField(source='user.username',   read_only=True, default=None)
    branch_code    = serializers.CharField(source='branch.code',     read_only=True, default=None)
    branch_name    = serializers.CharField(source='branch.name',     read_only=True, default=None)
    module_display = serializers.CharField(source='get_module_display', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    capital_total_bob = serializers.CharField(read_only=True)
    integrity_ok   = serializers.SerializerMethodField()

    class Meta:
        model  = SystemSnapshot
        fields = [
            'id', 'timestamp',
            'user_username', 'branch_code', 'branch_name',
            'module', 'module_display',
            'action', 'action_display',
            'capital_total_bob',
            'checksum', 'integrity_ok',
            'metadata_json',
        ]
        read_only_fields = fields

    def get_integrity_ok(self, obj):
        return obj.verify_integrity()


class SystemSnapshotDetailSerializer(SystemSnapshotListSerializer):
    """Serializer completo para detalle — incluye data_json."""
    class Meta(SystemSnapshotListSerializer.Meta):
        fields = SystemSnapshotListSerializer.Meta.fields + ['data_json']


class SnapshotOnDemandSerializer(serializers.Serializer):
    """Payload para solicitar un snapshot manual on-demand."""
    module = serializers.ChoiceField(
        choices=[c[0] for c in SystemSnapshot.MODULE_CHOICES],
        default='manual',
        help_text='Módulo a registrar',
    )
    notas  = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        help_text='Nota libre asociada al snapshot',
    )
