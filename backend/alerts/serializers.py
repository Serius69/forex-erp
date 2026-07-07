from rest_framework import serializers
from .models import AlertLog


class AlertLogSerializer(serializers.ModelSerializer):
    branch_name          = serializers.CharField(source='branch.name',           read_only=True, default=None)
    triggered_by_name    = serializers.CharField(source='triggered_by.username', read_only=True, default=None)
    acknowledged_by_name = serializers.CharField(source='acknowledged_by.username', read_only=True, default=None)
    severity_display     = serializers.CharField(source='get_severity_display',  read_only=True)
    source_display       = serializers.CharField(source='get_source_display',    read_only=True)
    # Campos normalizados al formato de salida del AlertGenerator
    tipo   = serializers.CharField(source='source',   read_only=True)
    nivel  = serializers.SerializerMethodField()

    class Meta:
        model  = AlertLog
        fields = [
            'id',
            'tipo', 'nivel',                          # formato AlertGenerator
            'source', 'source_display',               # legacy
            'alert_type', 'severity', 'severity_display',
            'title', 'message',
            'accion_sugerida',
            'data',
            'branch', 'branch_name',
            'triggered_by', 'triggered_by_name',
            'is_acknowledged', 'acknowledged_by', 'acknowledged_by_name', 'acknowledged_at',
            'created_at',
        ]
        read_only_fields = fields

    def get_nivel(self, obj) -> str:
        """Convierte severity (CRITICAL/HIGH/MEDIUM/LOW) al nivel estándar (CRITICAL/WARNING/INFO)."""
        return {
            'CRITICAL': 'CRITICAL',
            'HIGH':     'WARNING',
            'MEDIUM':   'WARNING',
            'LOW':      'INFO',
        }.get(obj.severity, 'INFO')


class AlertSummarySerializer(serializers.Serializer):
    total_active = serializers.IntegerField()
    by_severity  = serializers.DictField(child=serializers.IntegerField())
    by_source    = serializers.DictField(child=serializers.IntegerField())
    latest       = AlertLogSerializer(many=True)
