# tarjetas/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    TipoTarjeta, LoteCompra, VentaTarjeta,
    DetalleVentaLote, MovimientoTarjeta, AlertaInventarioTarjeta,
)


@admin.register(TipoTarjeta)
class TipoTarjetaAdmin(admin.ModelAdmin):
    list_display  = ('nombre', 'operadora', 'denominacion', 'stock_badge', 'is_active', 'updated_at')
    list_filter   = ('operadora', 'is_active')
    search_fields = ('nombre',)
    ordering      = ('operadora', 'denominacion')

    def stock_badge(self, obj):
        stock = obj.stock_actual
        color = 'red' if stock < 5 else ('orange' if stock < 20 else 'green')
        return format_html('<b style="color:{};">{}</b>', color, stock)
    stock_badge.short_description = 'Stock'


class DetalleVentaLoteInline(admin.TabularInline):
    model  = DetalleVentaLote
    extra  = 0
    fields = ('lote', 'cantidad_consumida', 'costo_unitario', 'costo_total_display')
    readonly_fields = ('lote', 'cantidad_consumida', 'costo_unitario', 'costo_total_display')

    def costo_total_display(self, obj):
        return f"Bs. {obj.costo_total}"
    costo_total_display.short_description = 'Costo Total'

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LoteCompra)
class LoteCompraAdmin(admin.ModelAdmin):
    list_display    = (
        'id', 'tipo_tarjeta', 'operadora_display',
        'cantidad_total', 'cantidad_restante', 'precio_costo',
        'is_active', 'proveedor', 'numero_factura', 'fecha_compra',
    )
    list_filter     = ('is_active', 'tipo_tarjeta__operadora', 'tipo_tarjeta')
    search_fields   = ('proveedor', 'numero_factura', 'tipo_tarjeta__nombre')
    ordering        = ('fecha_compra', 'id')
    readonly_fields = ('cantidad_restante', 'is_active', 'created_at', 'updated_at')
    date_hierarchy  = 'fecha_compra'

    def operadora_display(self, obj):
        return obj.tipo_tarjeta.operadora
    operadora_display.short_description = 'Operadora'
    operadora_display.admin_order_field = 'tipo_tarjeta__operadora'

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(VentaTarjeta)
class VentaTarjetaAdmin(admin.ModelAdmin):
    list_display    = (
        'numero_venta', 'tipo_tarjeta', 'cantidad',
        'precio_venta', 'total_bob', 'ganancia_bob',
        'estado', 'medio_pago', 'cajero', 'created_at',
    )
    list_filter     = ('estado', 'medio_pago', 'tipo_tarjeta__operadora', 'branch')
    search_fields   = ('numero_venta', 'cliente_nombre', 'cliente_tel')
    ordering        = ('-created_at',)
    date_hierarchy  = 'created_at'
    readonly_fields = (
        'numero_venta', 'total_bob', 'costo_fifo_bob', 'ganancia_bob',
        'total_con_comision', 'created_at', 'anulado_at', 'anulado_por',
    )
    inlines         = [DetalleVentaLoteInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(MovimientoTarjeta)
class MovimientoTarjetaAdmin(admin.ModelAdmin):
    list_display    = (
        'tipo_movimiento', 'tipo_tarjeta', 'cantidad',
        'precio_unitario', 'total_bob', 'ganancia_bob',
        'usuario', 'branch', 'created_at',
    )
    list_filter     = ('tipo_movimiento', 'tipo_tarjeta__operadora', 'branch')
    search_fields   = ('tipo_tarjeta__nombre', 'notas')
    ordering        = ('-created_at',)
    date_hierarchy  = 'created_at'
    readonly_fields = [f.name for f in MovimientoTarjeta._meta.get_fields()
                       if hasattr(f, 'column')]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AlertaInventarioTarjeta)
class AlertaInventarioTarjetaAdmin(admin.ModelAdmin):
    list_display    = (
        'tipo_tarjeta', 'branch', 'stock_minimo', 'stock_critico', 'is_active',
    )
    list_filter     = ('is_active', 'tipo_tarjeta__operadora')
    search_fields   = ('tipo_tarjeta__nombre',)
