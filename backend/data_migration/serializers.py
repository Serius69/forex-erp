# data_migration/serializers.py
from rest_framework import serializers
from .models import MigrationLog, MigrationCheckpoint, ColumnMapping

# Únicos targets con persistidor implementado (data_migration.services.importer.PERSISTERS).
# 'inventory'/'users' no tienen persistidor → se excluyen para no abortar el batch entero.
VALID_TARGET_MODELS = ['transactions', 'rates', 'customers', 'capital']


class ColumnMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ColumnMapping
        fields = [
            'id', 'sheet_column', 'model_field', 'transform',
            'is_required', 'default_value', 'validation_regex', 'order',
        ]


class MigrationCheckpointSerializer(serializers.ModelSerializer):
    class Meta:
        model  = MigrationCheckpoint
        fields = ['last_row_index', 'last_batch_num', 'saved_at']


class MigrationLogSerializer(serializers.ModelSerializer):
    column_mappings = ColumnMappingSerializer(many=True, read_only=True)
    checkpoint      = MigrationCheckpointSerializer(read_only=True)
    progress_pct    = serializers.FloatField(read_only=True)
    duration_seconds = serializers.FloatField(read_only=True)
    created_by_username = serializers.SerializerMethodField()

    class Meta:
        model  = MigrationLog
        fields = [
            'id', 'name', 'spreadsheet_id', 'sheet_name', 'target_model',
            'status', 'total_rows', 'processed_rows', 'success_rows',
            'error_rows', 'skipped_rows', 'dry_run', 'skip_errors',
            'batch_size', 'error_log', 'summary', 'progress_pct',
            'duration_seconds', 'created_by_username',
            'started_at', 'finished_at', 'created_at', 'updated_at',
            'column_mappings', 'checkpoint',
        ]
        read_only_fields = [
            'id', 'status', 'total_rows', 'processed_rows', 'success_rows',
            'error_rows', 'skipped_rows', 'error_log', 'summary',
            'started_at', 'finished_at', 'created_at', 'updated_at',
        ]

    def get_created_by_username(self, obj) -> str | None:
        return obj.created_by.username if obj.created_by else None


class StartMigrationSerializer(serializers.Serializer):
    """Payload para iniciar una nueva migración."""
    name           = serializers.CharField(max_length=200)
    spreadsheet_id = serializers.CharField(max_length=200)
    sheet_name     = serializers.CharField(max_length=200)
    target_model   = serializers.ChoiceField(choices=VALID_TARGET_MODELS)
    dry_run        = serializers.BooleanField(default=False)
    skip_errors    = serializers.BooleanField(default=False)
    batch_size     = serializers.IntegerField(default=100, min_value=10, max_value=1000)
    column_mappings = ColumnMappingSerializer(many=True, required=False)

    def validate_target_model(self, value):
        # Rechazar al crear (no al ejecutar) si no hay persistidor para el target.
        from data_migration.services.importer import PERSISTERS
        if value not in PERSISTERS:
            raise serializers.ValidationError(
                f'target_model "{value}" no tiene persistidor implementado. '
                f'Opciones válidas: {sorted(PERSISTERS)}'
            )
        return value


class SuggestMappingSerializer(serializers.Serializer):
    """Payload para sugerencia de mapeo."""
    spreadsheet_id = serializers.CharField(max_length=200)
    sheet_name     = serializers.CharField(max_length=200)
    target_model   = serializers.ChoiceField(choices=VALID_TARGET_MODELS)
    sample_rows    = serializers.IntegerField(default=10, min_value=1, max_value=50)


class ValidateMappingSerializer(serializers.Serializer):
    """Payload para validar un mapeo antes de migrar."""
    target_model    = serializers.ChoiceField(choices=VALID_TARGET_MODELS)
    column_mappings = ColumnMappingSerializer(many=True)
