# capital/serializers.py
from rest_framework import serializers
from .models import (Gasto, IngresoExtra, CapitalSnapshot, CapitalManualEntry,
                     CapitalEntryHistory, CapitalComposicion,
                     CapitalComposicionHistory, CashBOB)
from users.serializers import BranchSerializer, UserSerializer


def _branch_para_registro(user):
    """Sucursal del usuario, o la principal activa de su empresa (ADMIN sin branch)."""
    if user.branch_id:
        return user.branch
    from users.models import Branch
    return (Branch.objects
            .filter(company_id=user.company_id, is_active=True)
            .order_by('-is_main', 'id').first())


class GastoSerializer(serializers.ModelSerializer):
    registrado_por_nombre = serializers.CharField(
        source='registrado_por.get_full_name', read_only=True
    )
    branch_nombre = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model  = Gasto
        fields = [
            'id', 'fecha', 'categoria', 'descripcion',
            'monto_bob', 'medio_pago', 'proveedor', 'nro_factura',
            'notas', 'branch', 'branch_nombre',
            'registrado_por_nombre', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class CrearGastoSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Gasto
        fields = [
            'fecha', 'categoria', 'descripcion',
            'monto_bob', 'medio_pago', 'proveedor', 'nro_factura', 'notas',
        ]

    def create(self, validated_data):
        request = self.context['request']
        validated_data['branch']         = _branch_para_registro(request.user)
        validated_data['registrado_por'] = request.user
        return super().create(validated_data)


class IngresoExtraSerializer(serializers.ModelSerializer):
    registrado_por_nombre = serializers.CharField(
        source='registrado_por.get_full_name', read_only=True
    )
    branch_nombre = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model  = IngresoExtra
        fields = [
            'id', 'fecha', 'tipo', 'monto_bob', 'medio_pago',
            'notas', 'branch', 'branch_nombre',
            'registrado_por_nombre', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class CrearIngresoExtraSerializer(serializers.ModelSerializer):
    class Meta:
        model  = IngresoExtra
        fields = ['fecha', 'tipo', 'monto_bob', 'medio_pago', 'notas']

    def create(self, validated_data):
        request = self.context['request']
        validated_data['branch']         = _branch_para_registro(request.user)
        validated_data['registrado_por'] = request.user
        return super().create(validated_data)


class CapitalSnapshotSerializer(serializers.ModelSerializer):
    generado_por_nombre = serializers.CharField(
        source='generado_por.get_full_name', read_only=True
    )
    branch_nombre = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model  = CapitalSnapshot
        fields = [
            'id', 'fecha', 'branch', 'branch_nombre',
            'efectivo_bob', 'qr_bob', 'divisas_bob', 'tarjetas_bob',
            'pasivos_bob', 'total_bob',
            'detalle_divisas', 'detalle_tarjetas',
            'tipo', 'notas',
            'generado_por_nombre', 'created_at',
        ]
        read_only_fields = ['created_at']


class CrearSnapshotSerializer(serializers.Serializer):
    efectivo_bob  = serializers.DecimalField(max_digits=18, decimal_places=2,
                                              min_value='0', default='0')
    qr_bob        = serializers.DecimalField(max_digits=18, decimal_places=2,
                                              min_value='0', default='0')
    pasivos_bob   = serializers.DecimalField(max_digits=18, decimal_places=2,
                                              min_value='0', default='0')
    tipo          = serializers.ChoiceField(choices=['CIERRE', 'MANUAL', 'APERTURA'],
                                            default='MANUAL')
    notas         = serializers.CharField(required=False, allow_blank=True, default='')


class CapitalEntryHistorySerializer(serializers.ModelSerializer):
    modificado_por_nombre = serializers.CharField(
        source='modificado_por.get_full_name', read_only=True
    )

    class Meta:
        model  = CapitalEntryHistory
        fields = [
            'id',
            'efectivo_bob_prev', 'qr_bob_prev', 'pasivos_bob_prev',
            'efectivo_bob_new',  'qr_bob_new',  'pasivos_bob_new',
            'motivo', 'modificado_por_nombre', 'created_at',
        ]


class CapitalManualEntrySerializer(serializers.ModelSerializer):
    registrado_por_nombre = serializers.CharField(
        source='registrado_por.get_full_name', read_only=True
    )
    branch_nombre = serializers.CharField(source='branch.name', read_only=True)
    history       = CapitalEntryHistorySerializer(many=True, read_only=True)

    class Meta:
        model  = CapitalManualEntry
        fields = [
            'id', 'branch', 'branch_nombre', 'fecha',
            'efectivo_bob', 'qr_bob', 'pasivos_bob', 'notas',
            'registrado_por_nombre', 'history',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class ActualizarCapitalEntrySerializer(serializers.Serializer):
    efectivo_bob = serializers.DecimalField(max_digits=18, decimal_places=2, min_value='0')
    qr_bob       = serializers.DecimalField(max_digits=18, decimal_places=2, min_value='0')
    pasivos_bob  = serializers.DecimalField(max_digits=18, decimal_places=2, min_value='0',
                                             default='0')
    notas        = serializers.CharField(required=False, allow_blank=True, default='')
    motivo       = serializers.CharField(required=False, allow_blank=True, default='')


# ── CapitalComposicion ────────────────────────────────────────────────────────

class CapitalComposicionHistorySerializer(serializers.ModelSerializer):
    modificado_por_nombre = serializers.CharField(
        source='modificado_por.get_full_name', read_only=True
    )

    class Meta:
        model  = CapitalComposicionHistory
        fields = ['id', 'snapshot_prev', 'snapshot_new', 'motivo',
                  'modificado_por_nombre', 'created_at']


class CapitalComposicionSerializer(serializers.ModelSerializer):
    registrado_por_nombre = serializers.CharField(
        source='registrado_por.get_full_name', read_only=True
    )
    branch_nombre   = serializers.CharField(source='branch.name', read_only=True)
    total_efectivo  = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_digital   = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_activos   = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    capital_neto_local = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    history         = CapitalComposicionHistorySerializer(many=True, read_only=True)

    class Meta:
        model  = CapitalComposicion
        fields = [
            'id', 'branch', 'branch_nombre', 'fecha',
            'fuertes', 'caja_chica', 'monedas', 'rotos', 'sueltos',
            'qr_transferencias', 'tarjetas_telefonicas', 'pasivos', 'notas',
            'total_efectivo', 'total_digital', 'total_activos', 'capital_neto_local',
            'registrado_por_nombre', 'history',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


# ── CashBOB ──────────────────────────────────────────────────────────────────

class CashBOBSerializer(serializers.ModelSerializer):
    """Serializer de lectura: incluye totales calculados."""
    branch_nombre      = serializers.CharField(source='branch.name', read_only=True)
    registrado_por_nombre = serializers.CharField(
        source='registrado_por.get_full_name', read_only=True
    )
    total_fuertes      = serializers.SerializerMethodField()
    total_sueltos      = serializers.SerializerMethodField()
    total_caja_chica   = serializers.SerializerMethodField()
    total_efectivo_fisico = serializers.SerializerMethodField()
    total_general_bob  = serializers.SerializerMethodField()

    class Meta:
        model  = CashBOB
        fields = [
            'id', 'branch', 'branch_nombre', 'fecha',
            # Fuertes
            'fuertes_200', 'fuertes_100', 'fuertes_50',
            # Sueltos
            'sueltos_20', 'sueltos_10',
            # Caja chica
            'caja_chica_200', 'caja_chica_100', 'caja_chica_50',
            'caja_chica_20', 'caja_chica_10',
            # Digital
            'qr_transferencias',
            # Calculados
            'total_fuertes', 'total_sueltos', 'total_caja_chica',
            'total_efectivo_fisico', 'total_general_bob',
            'registrado_por_nombre', 'updated_at', 'created_at',
        ]
        read_only_fields = ['updated_at', 'created_at']

    def get_total_fuertes(self, obj):
        return str(obj.total_fuertes())

    def get_total_sueltos(self, obj):
        return str(obj.total_sueltos())

    def get_total_caja_chica(self, obj):
        return str(obj.total_caja_chica())

    def get_total_efectivo_fisico(self, obj):
        return str(obj.total_efectivo_fisico())

    def get_total_general_bob(self, obj):
        return str(obj.total_general_bob())


class UpdateCashBOBSerializer(serializers.Serializer):
    """Serializer de escritura: valida conteos enteros y QR decimal."""
    _INT = {'min_value': 0, 'default': 0}
    _DEC = {'max_digits': 15, 'decimal_places': 2, 'min_value': '0', 'default': '0'}

    # Fuertes
    fuertes_200 = serializers.IntegerField(**_INT)
    fuertes_100 = serializers.IntegerField(**_INT)
    fuertes_50  = serializers.IntegerField(**_INT)
    # Sueltos
    sueltos_20  = serializers.IntegerField(**_INT)
    sueltos_10  = serializers.IntegerField(**_INT)
    # Caja chica
    caja_chica_200 = serializers.IntegerField(**_INT)
    caja_chica_100 = serializers.IntegerField(**_INT)
    caja_chica_50  = serializers.IntegerField(**_INT)
    caja_chica_20  = serializers.IntegerField(**_INT)
    caja_chica_10  = serializers.IntegerField(**_INT)
    # Digital
    qr_transferencias = serializers.DecimalField(**_DEC)
    # Auditoría
    motivo = serializers.CharField(required=False, allow_blank=True, default='')


class UpsertComposicionSerializer(serializers.Serializer):
    """Validación para crear/actualizar CapitalComposicion."""
    from decimal import Decimal as _D_
    _D = {'max_digits': 15, 'decimal_places': 2, 'min_value': _D_('0'), 'default': _D_('0')}

    fuertes              = serializers.DecimalField(**_D)
    caja_chica           = serializers.DecimalField(**_D)
    monedas              = serializers.DecimalField(**_D)
    rotos                = serializers.DecimalField(**_D)
    sueltos              = serializers.DecimalField(**_D)
    qr_transferencias    = serializers.DecimalField(**_D)
    tarjetas_telefonicas = serializers.DecimalField(**_D)
    pasivos              = serializers.DecimalField(**_D)
    notas                = serializers.CharField(required=False, allow_blank=True, default='')
    motivo               = serializers.CharField(required=False, allow_blank=True, default='')
