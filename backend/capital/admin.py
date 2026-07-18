from django.contrib import admin
from .models import (
    Gasto, CapitalSnapshot, CapitalManualEntry, CapitalComposicion,
    CashBOB, CashFlowLog, CurrencyPosition, CurrencyPositionHistory,
    Acreedor, MovimientoAcreedor, MovimientoCajaChica,
)


@admin.register(CurrencyPosition)
class CurrencyPositionAdmin(admin.ModelAdmin):
    list_display   = ['branch', 'currency', 'net_position', 'avg_acquisition_cost',
                      'unrealized_pnl_parallel', 'unrealized_pnl_official', 'last_tx_at']
    list_filter    = ['branch', 'currency']
    readonly_fields = ['net_position', 'avg_acquisition_cost', 'total_bought', 'total_sold',
                       'total_cost_bob', 'unrealized_pnl_parallel', 'unrealized_pnl_official',
                       'parallel_rate_used', 'official_rate_used', 'last_tx_at',
                       'created_at', 'updated_at']
    ordering       = ['branch', 'currency__code']

    def has_add_permission(self, request):
        return False


@admin.register(CurrencyPositionHistory)
class CurrencyPositionHistoryAdmin(admin.ModelAdmin):
    list_display   = ['position', 'fecha', 'net_position', 'unrealized_pnl_parallel',
                      'snapshot_type', 'created_at']
    list_filter    = ['snapshot_type', 'fecha']
    readonly_fields = [f.name for f in CurrencyPositionHistory._meta.get_fields()
                       if hasattr(f, 'name')]
    ordering       = ['-fecha']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CashFlowLog)
class CashFlowLogAdmin(admin.ModelAdmin):
    list_display  = ['fecha', 'tipo', 'monto_bob', 'concepto', 'branch', 'created_at']
    list_filter   = ['tipo', 'branch', 'fecha']
    search_fields = ['concepto', 'transaction__transaction_number']
    readonly_fields = [f.name for f in CashFlowLog._meta.get_fields()
                       if hasattr(f, 'name')]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Gasto)
class GastoAdmin(admin.ModelAdmin):
    list_display  = ['fecha', 'categoria', 'descripcion', 'monto_bob', 'medio_pago', 'branch']
    list_filter   = ['categoria', 'medio_pago', 'branch']
    search_fields = ['descripcion', 'proveedor', 'nro_factura']
    date_hierarchy = 'fecha'


@admin.register(CapitalSnapshot)
class CapitalSnapshotAdmin(admin.ModelAdmin):
    list_display  = ['fecha', 'branch', 'tipo', 'total_bob', 'generado_por', 'created_at']
    list_filter   = ['tipo', 'branch']
    readonly_fields = ['created_at']
    date_hierarchy  = 'fecha'


class MovimientoAcreedorInline(admin.TabularInline):
    model   = MovimientoAcreedor
    extra   = 0
    fields  = ['fecha', 'tipo', 'monto_bob', 'monto_divisa', 'concepto']


@admin.register(Acreedor)
class AcreedorAdmin(admin.ModelAdmin):
    list_display  = ['nombre', 'moneda', 'branch', 'is_active', 'created_at']
    list_filter   = ['is_active', 'moneda', 'branch']
    search_fields = ['nombre', 'documento']
    inlines       = [MovimientoAcreedorInline]
    readonly_fields = ['created_at', 'updated_at']


@admin.register(MovimientoAcreedor)
class MovimientoAcreedorAdmin(admin.ModelAdmin):
    list_display  = ['fecha', 'acreedor', 'tipo', 'monto_bob', 'concepto', 'registrado_por']
    list_filter   = ['tipo', 'fecha']
    search_fields = ['acreedor__nombre', 'concepto']
    date_hierarchy  = 'fecha'
    readonly_fields = ['created_at', 'updated_at']


@admin.register(MovimientoCajaChica)
class MovimientoCajaChicaAdmin(admin.ModelAdmin):
    list_display  = ['fecha', 'branch', 'tipo', 'monto_bob', 'concepto', 'registrado_por']
    list_filter   = ['tipo', 'branch', 'fecha']
    search_fields = ['concepto']
    date_hierarchy  = 'fecha'
    readonly_fields = ['created_at', 'updated_at']
