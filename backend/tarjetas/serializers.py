# tarjetas/serializers.py
from rest_framework import serializers
from .models import TipoTarjeta, LoteCompra, VentaTarjeta, DetalleVentaLote, MovimientoTarjeta


class TipoTarjetaSerializer(serializers.ModelSerializer):
    stock_actual          = serializers.IntegerField(read_only=True)
    costo_promedio        = serializers.DecimalField(max_digits=10, decimal_places=4, read_only=True)
    valor_inventario_bob  = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model  = TipoTarjeta
        fields = [
            'id', 'operadora', 'nombre', 'denominacion', 'descripcion',
            'is_active', 'stock_actual', 'costo_promedio', 'valor_inventario_bob',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class LoteCompraSerializer(serializers.ModelSerializer):
    tipo_tarjeta_nombre = serializers.CharField(source='tipo_tarjeta.nombre', read_only=True)
    costo_total_bob     = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    registrado_por_name = serializers.CharField(source='registrado_por.get_full_name', read_only=True)

    class Meta:
        model  = LoteCompra
        fields = [
            'id', 'tipo_tarjeta', 'tipo_tarjeta_nombre',
            'proveedor', 'cantidad_total', 'cantidad_restante',
            'precio_costo', 'costo_total_bob',
            'numero_factura', 'fecha_compra',
            'is_active', 'notas',
            'registrado_por_name', 'created_at',
        ]
        read_only_fields = ['cantidad_restante', 'is_active', 'created_at']


class RegistrarLoteSerializer(serializers.Serializer):
    """Payload para registrar un nuevo lote de compra."""
    tipo_tarjeta_id = serializers.PrimaryKeyRelatedField(
        queryset=TipoTarjeta.objects.filter(is_active=True),
        source='tipo_tarjeta',
    )
    cantidad        = serializers.IntegerField(min_value=1)
    precio_costo    = serializers.DecimalField(max_digits=10, decimal_places=4, min_value='0.0001')
    proveedor       = serializers.CharField(max_length=200, default='Proveedor')
    numero_factura  = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    fecha_compra    = serializers.DateField(required=False, allow_null=True)
    notas           = serializers.CharField(required=False, allow_blank=True, default='')


class LoteAPICreateSerializer(serializers.Serializer):
    """
    Serializer para POST /api/tarjetas/lotes/ según API spec.

    Acepta los nombres de campo tal como los define la documentación:
      tipo_tarjeta  (int FK)  — no tipo_tarjeta_id
      cantidad_total (int)    — no cantidad
    """
    tipo_tarjeta   = serializers.PrimaryKeyRelatedField(
        queryset=TipoTarjeta.objects.filter(is_active=True),
        help_text='ID del TipoTarjeta',
    )
    proveedor      = serializers.CharField(max_length=200, default='Proveedor')
    cantidad_total = serializers.IntegerField(min_value=1, help_text='Cantidad de tarjetas en el lote')
    precio_costo   = serializers.DecimalField(max_digits=10, decimal_places=4, min_value='0.0001',
                                              help_text='Precio de costo unitario en BOB')
    numero_factura = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    fecha_compra   = serializers.DateField(required=False, allow_null=True)
    notas          = serializers.CharField(required=False, allow_blank=True, default='')


class DetalleVentaLoteSerializer(serializers.ModelSerializer):
    lote_id         = serializers.IntegerField(source='lote.id', read_only=True)
    costo_unitario  = serializers.DecimalField(max_digits=10, decimal_places=4, read_only=True)
    costo_total     = serializers.DecimalField(max_digits=15, decimal_places=4, read_only=True)

    class Meta:
        model  = DetalleVentaLote
        fields = ['lote_id', 'cantidad_consumida', 'costo_unitario', 'costo_total']


class VentaTarjetaSerializer(serializers.ModelSerializer):
    tipo_tarjeta_nombre = serializers.CharField(source='tipo_tarjeta.nombre', read_only=True)
    cajero_nombre       = serializers.CharField(source='cajero.get_full_name', read_only=True)
    detalles_lote       = DetalleVentaLoteSerializer(many=True, read_only=True)

    class Meta:
        model  = VentaTarjeta
        fields = [
            'id', 'numero_venta',
            'tipo_tarjeta', 'tipo_tarjeta_nombre',
            'cantidad', 'precio_venta', 'total_bob',
            'comision_bob', 'total_con_comision',
            'costo_fifo_bob', 'ganancia_bob',
            'medio_pago', 'cliente_nombre', 'cliente_tel',
            'notas', 'cajero_nombre',
            'detalles_lote', 'created_at',
        ]
        read_only_fields = [
            'numero_venta', 'total_bob', 'total_con_comision',
            'costo_fifo_bob', 'ganancia_bob', 'created_at',
        ]


class RegistrarVentaSerializer(serializers.Serializer):
    """Payload para registrar una venta de tarjetas."""
    tipo_tarjeta_id = serializers.PrimaryKeyRelatedField(
        queryset=TipoTarjeta.objects.filter(is_active=True),
        source='tipo_tarjeta',
    )
    cantidad        = serializers.IntegerField(min_value=1)
    precio_venta    = serializers.DecimalField(max_digits=10, decimal_places=2, min_value='0.01')
    comision_bob    = serializers.DecimalField(max_digits=10, decimal_places=2, min_value='0',
                                               required=False, default='0')
    medio_pago      = serializers.ChoiceField(choices=['CASH', 'QR', 'TRANSFER'], default='CASH')
    cliente_nombre  = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    cliente_tel     = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    notas           = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        tipo    = data['tipo_tarjeta']
        stock   = tipo.stock_actual
        cant    = data['cantidad']
        if cant > stock:
            raise serializers.ValidationError(
                f"Stock insuficiente de {tipo.nombre}. Disponible: {stock}."
            )
        return data


# ── Serializer de compra standalone (mismo campos, alias más claro) ───────────

class ComprarTarjetaSerializer(serializers.Serializer):
    """
    POST /api/tarjetas/comprar/

    Registra la compra de un lote de tarjetas (aumenta stock).
    El tipo de tarjeta se pasa directamente en el body.
    """
    tipo_tarjeta_id = serializers.PrimaryKeyRelatedField(
        queryset=TipoTarjeta.objects.filter(is_active=True),
        source='tipo_tarjeta',
        help_text="ID del TipoTarjeta (ver GET /api/tarjetas/tipos/)",
    )
    cantidad        = serializers.IntegerField(min_value=1, help_text="Número de tarjetas compradas")
    precio_costo    = serializers.DecimalField(
        max_digits=10, decimal_places=4, min_value='0.0001',
        help_text="Precio de costo unitario en BOB",
    )
    proveedor       = serializers.CharField(max_length=200, default='Proveedor')
    numero_factura  = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    fecha_compra    = serializers.DateField(required=False, allow_null=True)
    notas           = serializers.CharField(required=False, allow_blank=True, default='')


class VenderTarjetaSerializer(serializers.Serializer):
    """
    POST /api/tarjetas/vender/

    Registra la venta de tarjetas a un cliente (disminuye stock, FIFO).
    El tipo de tarjeta se pasa directamente en el body.
    """
    tipo_tarjeta_id = serializers.PrimaryKeyRelatedField(
        queryset=TipoTarjeta.objects.filter(is_active=True),
        source='tipo_tarjeta',
        help_text="ID del TipoTarjeta (ver GET /api/tarjetas/tipos/)",
    )
    cantidad        = serializers.IntegerField(min_value=1, help_text="Número de tarjetas a vender")
    precio_venta    = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value='0.01',
        help_text="Precio de venta unitario en BOB",
    )
    comision_bob    = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value='0',
        required=False, default='0',
        help_text="Comisión adicional en BOB (opcional)",
    )
    medio_pago      = serializers.ChoiceField(
        choices=['CASH', 'QR', 'TRANSFER'], default='CASH',
    )
    cliente_nombre  = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    cliente_tel     = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    notas           = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        tipo  = data['tipo_tarjeta']
        stock = tipo.stock_actual
        if data['cantidad'] > stock:
            raise serializers.ValidationError(
                {'cantidad': f"Stock insuficiente de '{tipo.nombre}'. "
                             f"Disponible: {stock}, solicitado: {data['cantidad']}."}
            )
        return data


class MovimientoTarjetaSerializer(serializers.ModelSerializer):
    """Serializer de lectura para el libro diario de tarjetas."""
    tipo_tarjeta_nombre  = serializers.CharField(source='tipo_tarjeta.nombre', read_only=True)
    tipo_tarjeta_operadora = serializers.CharField(source='tipo_tarjeta.operadora', read_only=True)
    usuario_nombre       = serializers.CharField(source='usuario.get_full_name', read_only=True)
    impacto_caja_bob     = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True,
    )

    class Meta:
        model  = MovimientoTarjeta
        fields = [
            'id', 'tipo_movimiento',
            'tipo_tarjeta', 'tipo_tarjeta_nombre', 'tipo_tarjeta_operadora',
            'cantidad', 'precio_unitario', 'total_bob',
            'ganancia_bob', 'impacto_caja_bob',
            'lote_compra', 'venta_tarjeta',
            'usuario_nombre', 'branch',
            'notas', 'created_at',
        ]
        read_only_fields = fields
