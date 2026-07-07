# data_migration/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import MigrationLog, MigrationCheckpoint, ColumnMapping


class ColumnMappingInline(admin.TabularInline):
    model  = ColumnMapping
    extra  = 0
    fields = ['sheet_column', 'model_field', 'transform', 'is_required', 'default_value', 'order']
    ordering = ['order', 'sheet_column']


class MigrationCheckpointInline(admin.StackedInline):
    model     = MigrationCheckpoint
    extra     = 0
    readonly_fields = ['last_row_index', 'last_batch_num', 'saved_at', 'state_snapshot']
    can_delete = False


@admin.register(MigrationLog)
class MigrationLogAdmin(admin.ModelAdmin):
    list_display  = [
        'name', 'target_model', 'status_badge', 'progress_display',
        'dry_run', 'created_by', 'created_at',
    ]
    list_filter   = ['status', 'target_model', 'dry_run']
    search_fields = ['name', 'spreadsheet_id', 'sheet_name']
    readonly_fields = [
        'id', 'status', 'total_rows', 'processed_rows', 'success_rows',
        'error_rows', 'skipped_rows', 'error_log', 'summary',
        'started_at', 'finished_at', 'created_at', 'updated_at',
        'progress_pct', 'duration_seconds',
    ]
    inlines = [MigrationCheckpointInline, ColumnMappingInline]
    ordering = ['-created_at']

    fieldsets = [
        ('Identificación', {
            'fields': ['id', 'name', 'spreadsheet_id', 'sheet_name', 'target_model'],
        }),
        ('Estado', {
            'fields': ['status', 'total_rows', 'processed_rows', 'success_rows',
                       'error_rows', 'skipped_rows', 'progress_pct'],
        }),
        ('Configuración', {
            'fields': ['dry_run', 'skip_errors', 'batch_size'],
        }),
        ('Resultados', {
            'fields': ['summary', 'error_log', 'duration_seconds'],
            'classes': ['collapse'],
        }),
        ('Auditoría', {
            'fields': ['created_by', 'started_at', 'finished_at', 'created_at', 'updated_at'],
        }),
    ]

    def status_badge(self, obj):
        colors = {
            'PENDING':   '#6c757d',
            'RUNNING':   '#007bff',
            'PAUSED':    '#fd7e14',
            'COMPLETED': '#28a745',
            'FAILED':    '#dc3545',
            'VALIDATED': '#20c997',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:4px;'
            'font-size:11px;font-weight:bold">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Estado'

    def progress_display(self, obj):
        pct = obj.progress_pct
        color = '#28a745' if pct == 100 else '#007bff'
        return format_html(
            '<div style="width:120px;background:#e9ecef;border-radius:4px;overflow:hidden">'
            '<div style="width:{pct}%;background:{color};height:16px;text-align:center;'
            'color:white;font-size:11px;line-height:16px">{pct}%</div></div>',
            pct=pct, color=color,
        )
    progress_display.short_description = 'Progreso'


@admin.register(ColumnMapping)
class ColumnMappingAdmin(admin.ModelAdmin):
    list_display  = ['migration', 'sheet_column', 'model_field', 'transform', 'is_required', 'order']
    list_filter   = ['migration__target_model', 'transform', 'is_required']
    search_fields = ['sheet_column', 'model_field', 'migration__name']
    ordering      = ['migration', 'order', 'sheet_column']
