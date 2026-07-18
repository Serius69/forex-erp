# capital/views.py
import logging
from decimal import Decimal
from datetime import date
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Sum, Count
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import (Gasto, IngresoExtra, CapitalSnapshot, CapitalManualEntry,
                     CapitalEntryHistory, CapitalComposicion, CashBOB)
from .serializers import (
    GastoSerializer, CrearGastoSerializer,
    IngresoExtraSerializer, CrearIngresoExtraSerializer,
    CapitalSnapshotSerializer, CrearSnapshotSerializer,
    CapitalManualEntrySerializer, ActualizarCapitalEntrySerializer,
    CapitalEntryHistorySerializer,
    CapitalComposicionSerializer, UpsertComposicionSerializer,
    CashBOBSerializer, UpdateCashBOBSerializer,
)
from .services import CapitalService, GananciaService, CashBOBService, InsufficientCashError
from users.permissions import IsAdminOrSupervisor
from tenants.permissions import IsCompanyMember
from core.ratelimit import rate_limit
from django.db.models import Case, When, F, Value, DecimalField
from django.db.models.functions import Coalesce
from .models import Acreedor, MovimientoAcreedor, MovimientoCajaChica
from .serializers import (
    AcreedorSerializer, CrearAcreedorSerializer,
    MovimientoAcreedorSerializer, CrearMovimientoAcreedorSerializer,
    MovimientoCajaChicaSerializer, CrearMovimientoCajaChicaSerializer,
)

_SALDO_DF = DecimalField(max_digits=18, decimal_places=2)

log = logging.getLogger('capital')


def _company_branch_filter(qs, user, branch_field='branch'):
    """Apply tenant + branch isolation to any queryset."""
    if getattr(user, 'company_id', None):
        qs = qs.filter(**{f'{branch_field}__company_id': user.company_id})
    if user.role == 'CASHIER' and user.branch_id:
        qs = qs.filter(**{branch_field: user.branch_id})
    return qs


def _resolve_branch_scope(request):
    """
    Resuelve la sucursal a consultar según rol + query param.

    ADMIN puede pasar ?branch_id=N (selector de sucursal en la UI) o nada
    (None = todas las sucursales de su empresa). La sucursal siempre se
    valida contra la empresa del usuario (aislamiento multi-tenant).
    Otros roles quedan fijados a su propia sucursal.

    Retorna (branch, error_response) — error_response no-None si el
    branch_id es inválido o de otra empresa.
    """
    user = request.user
    if user.role != 'ADMIN':
        return user.branch, None

    branch_id = request.query_params.get('branch_id')
    if not branch_id:
        return None, None  # todas las sucursales

    from users.models import Branch
    try:
        qs = Branch.objects.all()
        if getattr(user, 'company_id', None):
            qs = qs.filter(company_id=user.company_id)
        return qs.get(pk=branch_id), None
    except (Branch.DoesNotExist, ValueError):
        return None, Response({'error': 'Sucursal no encontrada'}, status=404)


class GastoViewSet(viewsets.ModelViewSet):
    """CRUD de gastos operativos."""
    queryset           = Gasto.objects.select_related('branch', 'registrado_por').all()
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return CrearGastoSerializer
        return GastoSerializer

    def get_queryset(self):
        qs = _company_branch_filter(super().get_queryset(), self.request.user)

        fecha_desde = self.request.query_params.get('date_from')
        fecha_hasta = self.request.query_params.get('date_to')
        categoria   = self.request.query_params.get('categoria')

        if fecha_desde:
            qs = qs.filter(fecha__gte=fecha_desde)
        if fecha_hasta:
            qs = qs.filter(fecha__lte=fecha_hasta)
        if categoria:
            qs = qs.filter(categoria=categoria)

        return qs.order_by('-fecha', '-created_at')

    @action(detail=False, methods=['GET'], url_path='resumen')
    def resumen(self, request):
        """Resumen de gastos por categoría en el período."""
        date_from = request.query_params.get('date_from', str(timezone.localdate()))
        date_to   = request.query_params.get('date_to',   str(timezone.localdate()))

        qs = self.get_queryset().filter(fecha__gte=date_from, fecha__lte=date_to)
        agg = qs.aggregate(total=Sum('monto_bob'), count=Count('id'))
        por_categoria = list(
            qs.values('categoria')
            .annotate(total=Sum('monto_bob'), count=Count('id'))
            .order_by('-total')
        )
        return Response({
            'total_bob':      str(agg['total'] or 0),
            'total_gastos':   agg['count'] or 0,
            'por_categoria':  por_categoria,
        })


class IngresoExtraViewSet(viewsets.ModelViewSet):
    """CRUD de ingresos no cambiarios (ventas indirectas, comisiones, etc.)."""
    queryset           = IngresoExtra.objects.select_related('branch', 'registrado_por').all()
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return CrearIngresoExtraSerializer
        return IngresoExtraSerializer

    def get_queryset(self):
        qs = _company_branch_filter(super().get_queryset(), self.request.user)

        fecha_desde = self.request.query_params.get('date_from')
        fecha_hasta = self.request.query_params.get('date_to')
        tipo        = self.request.query_params.get('tipo')

        if fecha_desde:
            qs = qs.filter(fecha__gte=fecha_desde)
        if fecha_hasta:
            qs = qs.filter(fecha__lte=fecha_hasta)
        if tipo:
            qs = qs.filter(tipo__icontains=tipo)

        return qs.order_by('-fecha', '-created_at')

    @action(detail=False, methods=['GET'], url_path='resumen')
    def resumen(self, request):
        """Resumen de ingresos extra por tipo en el período."""
        date_from = request.query_params.get('date_from', str(timezone.localdate()))
        date_to   = request.query_params.get('date_to',   str(timezone.localdate()))

        qs = self.get_queryset().filter(fecha__gte=date_from, fecha__lte=date_to)
        agg = qs.aggregate(total=Sum('monto_bob'), count=Count('id'))
        por_tipo = list(
            qs.values('tipo')
            .annotate(total=Sum('monto_bob'), count=Count('id'))
            .order_by('-total')
        )
        return Response({
            'total_bob':      str(agg['total'] or 0),
            'total_ingresos': agg['count'] or 0,
            'por_tipo':       por_tipo,
        })


class CapitalSnapshotViewSet(viewsets.ModelViewSet):
    """
    Snapshots de capital.

    GET  /api/capital/snapshots/         — historial de snapshots
    POST /api/capital/snapshots/         — crear snapshot manual (API spec)
    GET  /api/capital/snapshots/{id}/    — detalle
    POST /api/capital/snapshots/generar/ — alias legacy (mismo comportamiento)
    """
    queryset           = CapitalSnapshot.objects.select_related(
        'branch', 'generado_por'
    ).all()
    serializer_class   = CapitalSnapshotSerializer
    permission_classes = [IsAdminOrSupervisor, IsCompanyMember]

    def get_queryset(self):
        qs = _company_branch_filter(super().get_queryset(), self.request.user)
        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(fecha__gte=date_from)
        if date_to:
            qs = qs.filter(fecha__lte=date_to)
        return qs.order_by('-fecha', '-created_at')

    def _crear_snapshot(self, request):
        """Lógica compartida entre create y generar."""
        ser = CrearSnapshotSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd  = ser.validated_data

        branch = request.user.branch
        if not branch:
            return Response(
                {'error': 'Usuario sin sucursal asignada'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                snap = CapitalService.guardar_snapshot(
                    branch       = branch,
                    generado_por = request.user,
                    tipo         = vd.get('tipo', 'MANUAL'),
                    efectivo_bob = vd.get('efectivo_bob'),
                    qr_bob       = vd.get('qr_bob'),
                    pasivos_bob  = vd.get('pasivos_bob'),
                    notas        = vd.get('notas', ''),
                )
            log.info(
                'CAPITAL_SNAPSHOT_CREATED id=%s tipo=%s branch=%s neto=%s by=%s',
                snap.id, snap.tipo, branch.code, snap.total_bob, request.user.username,
            )
            return Response(
                {
                    'status':       'ok',
                    'snapshot_id':  snap.id,
                    'total_assets': str(snap.total_bob),
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            log.exception(
                'CAPITAL_SNAPSHOT_ERROR branch=%s user=%s',
                branch.code, request.user.username,
            )
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request, *args, **kwargs):
        """POST /api/capital/snapshots/ — crear snapshot según API spec."""
        return self._crear_snapshot(request)

    @action(detail=False, methods=['POST'], url_path='generar')
    @rate_limit(requests=10, window=60, scope='user')
    def generar(self, request):
        """POST /api/capital/snapshots/generar/ — alias legacy."""
        return self._crear_snapshot(request)

    # Deshabilitar update y delete — snapshots son inmutables
    def update(self, request, *args, **kwargs):
        return Response({'error': 'Los snapshots no pueden modificarse'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response({'error': 'Los snapshots no pueden eliminarse'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)


class CapitalManualEntryViewSet(viewsets.ModelViewSet):
    """
    CRUD de entradas manuales de capital (efectivo, QR, pasivos).
    Editable como Excel con historial de cambios automático.

    GET    /api/capital/caja/         — entrada vigente de hoy
    POST   /api/capital/caja/         — crear entrada (si no existe hoy)
    PATCH  /api/capital/caja/{id}/    — editar con historial automático
    GET    /api/capital/caja/{id}/historia/ — ver historial de cambios
    """
    permission_classes = [IsAuthenticated, IsCompanyMember]
    serializer_class   = CapitalManualEntrySerializer

    def get_queryset(self):
        qs = CapitalManualEntry.objects.select_related(
            'branch', 'registrado_por'
        ).prefetch_related('history__modificado_por')

        qs = _company_branch_filter(qs, self.request.user)

        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(fecha__gte=date_from)
        if date_to:
            qs = qs.filter(fecha__lte=date_to)

        return qs.order_by('-fecha')

    def create(self, request, *args, **kwargs):
        ser = ActualizarCapitalEntrySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data

        branch = request.user.branch
        if not branch:
            return Response({'error': 'Usuario sin sucursal'}, status=400)

        today = timezone.localdate()
        entry, created = CapitalManualEntry.objects.get_or_create(
            branch=branch,
            fecha=today,
            defaults={
                'efectivo_bob':    vd['efectivo_bob'],
                'qr_bob':          vd['qr_bob'],
                'pasivos_bob':     vd.get('pasivos_bob', 0),
                'notas':           vd.get('notas', ''),
                'registrado_por':  request.user,
            },
        )

        if not created:
            # Ya existe → actualizar con historial
            return self._update_with_history(request, entry, vd)

        log.info(
            "CAPITAL_ENTRY_CREATED branch=%s fecha=%s efectivo=%s qr=%s",
            branch.code, today, entry.efectivo_bob, entry.qr_bob,
        )
        return Response(
            CapitalManualEntrySerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, pk=None):
        entry = self.get_object()
        ser   = ActualizarCapitalEntrySerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        return self._update_with_history(request, entry, ser.validated_data)

    update = partial_update  # PATCH y PUT idénticos

    def _update_with_history(self, request, entry, vd):
        """Actualiza la entrada y guarda el historial de cambios."""
        from django.db import transaction as db_tx
        with db_tx.atomic():
            # Guardar historial previo
            CapitalEntryHistory.objects.create(
                entry            = entry,
                efectivo_bob_prev= entry.efectivo_bob,
                qr_bob_prev      = entry.qr_bob,
                pasivos_bob_prev = entry.pasivos_bob,
                efectivo_bob_new = vd.get('efectivo_bob', entry.efectivo_bob),
                qr_bob_new       = vd.get('qr_bob', entry.qr_bob),
                pasivos_bob_new  = vd.get('pasivos_bob', entry.pasivos_bob),
                motivo           = vd.get('motivo', ''),
                modificado_por   = request.user,
            )
            # Aplicar cambios
            for field in ('efectivo_bob', 'qr_bob', 'pasivos_bob', 'notas'):
                if field in vd:
                    setattr(entry, field, vd[field])
            entry.save()

        log.info(
            "CAPITAL_ENTRY_UPDATED branch=%s fecha=%s by=%s",
            entry.branch.code, entry.fecha, request.user.username,
        )
        return Response(CapitalManualEntrySerializer(entry).data)

    @action(detail=False, methods=['GET'], url_path='hoy')
    def hoy(self, request):
        """GET /api/capital/caja/hoy/ — entrada vigente de hoy o vacía."""
        branch = request.user.branch
        if not branch:
            log.warning('capital_caja_hoy — usuario sin sucursal: %s', request.user.username)
            return Response({
                'id': None, 'fecha': str(timezone.localdate()),
                'efectivo_bob': '0.00', 'qr_bob': '0.00', 'pasivos_bob': '0.00',
                'notas': '', 'history': [],
            })
        try:
            entry = CapitalManualEntry.objects.prefetch_related('history').get(
                branch=branch, fecha=timezone.localdate()
            )
            return Response(CapitalManualEntrySerializer(entry).data)
        except CapitalManualEntry.DoesNotExist:
            return Response({
                'id': None, 'fecha': str(timezone.localdate()),
                'efectivo_bob': '0.00', 'qr_bob': '0.00', 'pasivos_bob': '0.00',
                'notas': '', 'history': [],
            })


# ── CapitalComposicion ViewSet ────────────────────────────────────────────────

class CapitalComposicionViewSet(viewsets.ModelViewSet):
    """
    CRUD de la composición detallada del efectivo en caja.

    GET    /api/capital/composicion/       — lista (con filtro fecha)
    POST   /api/capital/composicion/       — crear/actualizar hoy (upsert)
    PATCH  /api/capital/composicion/{id}/  — actualizar con historial
    GET    /api/capital/composicion/hoy/   — composición vigente de hoy

    Campos editables: fuertes, caja_chica, monedas, rotos, sueltos,
                      qr_transferencias, tarjetas_telefonicas, pasivos, notas
    """
    permission_classes = [IsAuthenticated, IsCompanyMember]
    serializer_class   = CapitalComposicionSerializer

    def get_queryset(self):
        qs = CapitalComposicion.objects.select_related(
            'branch', 'registrado_por'
        ).prefetch_related('history__modificado_por')

        qs = _company_branch_filter(qs, self.request.user)

        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(fecha__gte=date_from)
        if date_to:
            qs = qs.filter(fecha__lte=date_to)

        return qs.order_by('-fecha')

    def create(self, request, *args, **kwargs):
        """Upsert — crea o actualiza la composición del día actual."""
        ser = UpsertComposicionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data

        branch = request.user.branch
        if not branch:
            return Response({'error': 'Usuario sin sucursal asignada'}, status=400)

        motivo = vd.pop('motivo', '')
        comp   = CapitalService.upsert_composicion(branch, request.user, vd, motivo)

        return Response(
            CapitalComposicionSerializer(comp).data,
            status=status.HTTP_200_OK,
        )

    def partial_update(self, request, pk=None):
        """PATCH — actualiza campos específicos con historial."""
        comp = self.get_object()
        ser  = UpsertComposicionSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        vd   = ser.validated_data
        motivo = vd.pop('motivo', '')
        comp = CapitalService.upsert_composicion(
            comp.branch, request.user, vd, motivo
        )
        return Response(CapitalComposicionSerializer(comp).data)

    update = partial_update

    @action(detail=False, methods=['GET'], url_path='hoy')
    def hoy(self, request):
        """GET /api/capital/composicion/hoy/ — composición vigente de hoy."""
        branch = request.user.branch
        _empty = {
            'id': None, 'fecha': str(timezone.localdate()),
            'fuertes': '0.00', 'caja_chica': '0.00', 'monedas': '0.00',
            'rotos': '0.00', 'sueltos': '0.00',
            'qr_transferencias': '0.00', 'tarjetas_telefonicas': '0.00',
            'pasivos': '0.00', 'notas': '', 'history': [],
            'total_efectivo': '0.00', 'total_digital': '0.00',
            'total_activos': '0.00', 'capital_neto_local': '0.00',
        }
        if not branch:
            log.warning('composicion_hoy — usuario sin sucursal: %s', request.user.username)
            return Response(_empty)
        try:
            comp = (CapitalComposicion.objects
                    .prefetch_related('history')
                    .get(branch=branch, fecha=timezone.localdate()))
            return Response(CapitalComposicionSerializer(comp).data)
        except CapitalComposicion.DoesNotExist:
            return Response(_empty)


# ── CashBOB ViewSet ───────────────────────────────────────────────────────────

class CashBOBViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Denominación-level BOB cash management.

    GET  /api/capital/cash-bob/         — list (ADMIN only, all branches)
    GET  /api/capital/cash-bob/{id}/    — detail
    GET  /api/capital/cash-bob/hoy/     — today's breakdown (structured)
    POST /api/capital/cash-bob/update/  — manual update (upsert today)
    """
    serializer_class   = CashBOBSerializer
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get_queryset(self):
        qs = CashBOB.objects.select_related('branch', 'registrado_por').all()
        qs = _company_branch_filter(qs, self.request.user)
        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(fecha__gte=date_from)
        if date_to:
            qs = qs.filter(fecha__lte=date_to)
        return qs.order_by('-fecha')

    @action(detail=False, methods=['GET'], url_path='hoy')
    def hoy(self, request):
        """
        GET /api/capital/cash-bob/hoy/

        Returns:
        {
          "fuertes":    {"200": x, "100": x, "50": x, "total": x},
          "sueltos":    {"20": x, "10": x, "total": x},
          "caja_chica": {"200": x, ..., "10": x, "total": x},
          "qr":         x,
          "total_efectivo_fisico": x,
          "total_bob":  x
        }
        """
        branch = request.user.branch
        if not branch:
            return Response({'error': 'Usuario sin sucursal asignada'}, status=400)

        today = timezone.localdate()
        try:
            cash = CashBOB.objects.select_related('branch').get(
                branch=branch, fecha=today
            )
            return Response(CashBOBService.serialize_breakdown(cash))
        except CashBOB.DoesNotExist:
            return Response({
                'fecha':   str(today),
                'branch':  branch.id,
                'branch_nombre': branch.name,
                'fuertes':    {'200': 0, '100': 0, '50': 0, 'total': '0'},
                'sueltos':    {'20': 0, '10': 0, 'total': '0'},
                'caja_chica': {'200': 0, '100': 0, '50': 0, '20': 0, '10': 0, 'total': '0'},
                'qr':         '0.00',
                'total_efectivo_fisico': '0',
                'total_bob':  '0.00',
                'updated_at': None,
            })

    @action(detail=False, methods=['POST'], url_path='update',
            permission_classes=[IsAdminOrSupervisor])
    @rate_limit(requests=20, window=60, scope='user')
    def update_cash(self, request):
        """
        POST /api/capital/cash-bob/update/

        Body: denomination counts + qr_transferencias.
        Creates or fully replaces today's CashBOB record.
        Also syncs CapitalComposicion.
        """
        branch = request.user.branch
        if not branch:
            return Response({'error': 'Usuario sin sucursal asignada'}, status=400)

        ser = UpdateCashBOBSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data

        cash = CashBOBService.upsert(branch, request.user, vd)
        return Response(
            CashBOBService.serialize_breakdown(cash),
            status=status.HTTP_200_OK,
        )


# ── Endpoints de solo lectura (sin viewset) ───────────────────────────────────

def _format_capital_actual(capital: dict) -> dict:
    """
    Transforma el dict interno de CapitalService.calcular_capital()
    al formato exacto del API spec:

    {
      efectivo_bob, qr_bob, divisas_bob, tarjetas_bob,
      pasivos_bob, total_bob,
      detalle_divisas: {CODE: {stock, tc_venta, valor_bob}},
      detalle_tarjetas: {nombre: {stock, precio_venta_prom, valor_bob}},
      advertencias, calculado_en
    }
    """
    totales  = capital.get('totales', {})
    digital  = capital.get('digital', {})

    # detalle_divisas: simplificar claves internas
    detalle_divisas = {}
    for code, div in capital.get('divisas', {}).items():
        detalle_divisas[code] = {
            'stock':     div.get('stock', '0.00'),
            'tc_venta':  div.get('tc_venta_unit', '0.0000'),
            'valor_bob': div.get('valor_bob', '0.00'),
        }

    # detalle_tarjetas: renombrar precio_prom → precio_venta_prom
    detalle_tarjetas = {}
    for nombre, t in capital.get('tarjetas_modulo', {}).items():
        detalle_tarjetas[nombre] = {
            'stock':           t.get('stock', 0),
            'precio_venta_prom': t.get('precio_prom', '0.00'),
            'valor_bob':       t.get('valor_bob', '0.00'),
        }

    return {
        'efectivo_bob':    totales.get('efectivo_bob', '0.00'),
        'qr_bob':          digital.get('qr_transferencias', '0.00'),
        'divisas_bob':     totales.get('divisas_bob', '0.00'),
        'tarjetas_bob':    totales.get('tarjetas_bob', '0.00'),
        'pasivos_bob':     capital.get('total_pasivos', '0.00'),
        'total_bob':       capital.get('capital_neto', '0.00'),
        'detalle_divisas': detalle_divisas,
        'detalle_tarjetas': detalle_tarjetas,
        'advertencias':    capital.get('advertencias', []),
        'calculado_en':    capital.get('calculado_en', ''),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capital_actual(request):
    """
    Calcula el capital actual en tiempo real.
    GET /api/capital/actual/?branch_id=1

    Responde exactamente según el API spec:
      efectivo_bob, qr_bob, divisas_bob, tarjetas_bob, pasivos_bob,
      total_bob, detalle_divisas, detalle_tarjetas, advertencias, calculado_en
    """
    branch, error = _resolve_branch_scope(request)
    if error:
        return error

    capital = CapitalService.calcular_capital(branch=branch)
    return Response(_format_capital_actual(capital))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ganancias_divisas(request):
    """
    Ganancia por divisa en el período.
    GET /api/capital/ganancias/?date_from=2026-01-01&date_to=2026-01-31

    Respuesta: lista directa según API spec:
      [ { divisa, ops_compra, ops_venta, unidades_compradas, unidades_vendidas,
          costo_bob, ingreso_bob, ganancia_bob, tc_compra_prom, tc_venta_prom,
          spread_prom, margen_pct }, ... ]
    """
    date_from_str = request.query_params.get('date_from', str(timezone.localdate()))
    date_to_str   = request.query_params.get('date_to',   str(timezone.localdate()))
    currency_code = request.query_params.get('currency')

    try:
        date_from = date.fromisoformat(date_from_str)
        date_to   = date.fromisoformat(date_to_str)
    except ValueError:
        return Response({'error': 'Formato de fecha inválido (YYYY-MM-DD)'}, status=400)

    if date_from > date_to:
        return Response({'error': 'date_from no puede ser posterior a date_to'}, status=400)

    branch, error = _resolve_branch_scope(request)
    if error:
        return error

    ganancias = GananciaService.ganancia_por_divisa(
        date_from, date_to, branch=branch, currency_code=currency_code
    )
    # Retorna la lista directamente (API spec: array de objetos por divisa)
    return Response(ganancias)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def resumen_financiero(request):
    """
    Resumen financiero completo (P&G del período):
      divisas + tarjetas + gastos + ganancia neta.
    GET /api/capital/resumen/?date_from=2026-01-01&date_to=2026-01-31
    """
    date_from_str = request.query_params.get('date_from', str(timezone.localdate()))
    date_to_str   = request.query_params.get('date_to',   str(timezone.localdate()))

    try:
        date_from = date.fromisoformat(date_from_str)
        date_to   = date.fromisoformat(date_to_str)
    except ValueError:
        return Response({'error': 'Formato de fecha inválido (YYYY-MM-DD)'}, status=400)

    branch, error = _resolve_branch_scope(request)
    if error:
        return error
    resumen = GananciaService.resumen_financiero(date_from, date_to, branch=branch)
    return Response(resumen)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capital_resumen(request):
    """
    Composición completa del capital en tiempo real.

    GET /api/capital/resumen-capital/?branch_id=1

    Responde EXACTAMENTE:
    {
      capital_neto,
      total_activos,
      total_pasivos,
      divisas: { USD: {stock, tc_venta_unit, tc_venta_lote, valor_bob, ...}, ... },
      efectivo: { fuertes, caja_chica, monedas, rotos, sueltos, total },
      digital:  { qr_transferencias, tarjetas_telefonicas, total },
      tarjetas_modulo: { NombreTipo: {stock, precio_prom, valor_bob} },
      totales:  { divisas_bob, efectivo_bob, digital_bob, tarjetas_bob },
      desglose: { pct_divisas, pct_efectivo, pct_digital, pct_tarjetas },
      advertencias: [...],
      calculado_en: ISO,
    }
    """
    branch, error = _resolve_branch_scope(request)
    if error:
        return error

    capital = CapitalService.calcular_capital(branch=branch)

    # Calcular porcentajes para el desglose visual (pie chart)
    total = Decimal(capital['total_activos'] or '0')
    def pct(campo):
        val = Decimal(capital['totales'].get(campo, '0'))
        return str(round(val / total * 100, 2)) if total > 0 else '0.00'

    capital['desglose'] = {
        'pct_divisas':  pct('divisas_bob'),
        'pct_efectivo': pct('efectivo_bob'),
        'pct_digital':  pct('digital_bob'),
        'pct_tarjetas': pct('tarjetas_bob'),
    }

    return Response(capital)


# ── Time-travel: estado del sistema en una fecha pasada ───────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capital_at_date(request):
    """
    Retorna el estado completo del sistema en una fecha pasada consultando
    el snapshot más reciente anterior o igual a la fecha indicada.

    GET /api/capital/at-date/?date=YYYY-MM-DD[&branch_id=<int>][&module=forex]

    Parámetros
    ----------
    date      : (requerido) Fecha objetivo — devuelve el estado al cierre de ese día.
    branch_id : (solo ADMIN) Limita la búsqueda a una sucursal específica.
    module    : (opcional) Filtra por módulo de origen del snapshot
                (forex, tarjetas, capital, gastos, manual, system …).

    Respuesta
    ---------
    {
      "snapshot_id":        int,
      "snapshot_timestamp": ISO,
      "query_date":         "YYYY-MM-DD",
      "module":             str,
      "action":             str,
      "branch":             str | null,
      "integrity_ok":       bool,

      "capital":  { efectivo_bob, qr_bob, divisas_bob, tarjetas_bob,
                    pasivos_bob, total_bob,
                    detalle_divisas: {CODE: {stock, tc_venta, valor_bob}},
                    detalle_tarjetas: {nombre: {stock, precio_venta_prom, valor_bob}} },
      "caja":     { BRANCH_CODE: { denominaciones … } } | null,
      "divisas":  [ { currency, name, branch, physical, digital,
                      total, wac, low_stock, overstocked } … ],
      "tarjetas": { items: […], total_tipos: int, total_valor_bob: str }
    }

    Errores
    -------
    400 — date ausente o inválida, fecha futura
    404 — no existe ningún snapshot en la fecha indicada ni anterior
    """
    from snapshots.models import SystemSnapshot

    # ── Validar parámetro date ────────────────────────────────────────────────
    date_str = request.query_params.get('date', '').strip()
    if not date_str:
        return Response(
            {'error': 'Parámetro date requerido (YYYY-MM-DD)'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return Response(
            {'error': 'Formato de fecha inválido — use YYYY-MM-DD'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if target_date > timezone.localdate():
        return Response(
            {'error': 'No se puede consultar fechas futuras'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── Resolver sucursal ─────────────────────────────────────────────────────
    if request.user.role == 'ADMIN':
        branch_id = request.query_params.get('branch_id')
        if branch_id:
            from users.models import Branch
            try:
                branch = Branch.objects.get(pk=branch_id)
            except Branch.DoesNotExist:
                return Response({'error': 'Sucursal no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        else:
            branch = None  # Sin filtro → snapshots globales o cualquiera
    else:
        branch = request.user.branch

    # ── Construir queryset ────────────────────────────────────────────────────
    qs = (SystemSnapshot.objects
          .select_related('user', 'branch')
          .filter(timestamp__date__lte=target_date))

    if branch is not None:
        qs = qs.filter(branch=branch)
    elif request.user.role == 'ADMIN':
        # ADMIN sin sucursal: preferir snapshots globales (branch=NULL)
        # y caer en cualquier snapshot si no existen globales.
        global_qs = qs.filter(branch__isnull=True)
        if global_qs.exists():
            qs = global_qs
        # else: qs sin filtro de branch (toma cualquier sucursal)

    # Filtro opcional de módulo
    module_param = request.query_params.get('module')
    if module_param:
        qs = qs.filter(module=module_param)

    snap = qs.order_by('-timestamp').first()

    # ── 404 si no hay ningún snapshot previo a la fecha ───────────────────────
    if snap is None:
        msg = f'No hay snapshots para la fecha {target_date} o anteriores'
        if module_param:
            msg += f' (módulo: {module_param})'
        if branch is not None:
            msg += f' (sucursal: {branch.code})'
        return Response(
            {'error': msg, 'query_date': str(target_date)},
            status=status.HTTP_404_NOT_FOUND,
        )

    # ── Construir respuesta ───────────────────────────────────────────────────
    data = snap.data_json or {}

    log.info(
        'CAPITAL_AT_DATE query_date=%s snap_id=%s snap_ts=%s branch=%s user=%s',
        target_date, snap.id,
        snap.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        snap.branch.code if snap.branch_id else 'ALL',
        request.user.username,
    )

    return Response({
        'snapshot_id':        snap.id,
        'snapshot_timestamp': snap.timestamp.isoformat(),
        'query_date':         str(target_date),
        'module':             snap.module,
        'action':             snap.action,
        'branch':             snap.branch.code if snap.branch_id else None,
        'integrity_ok':       snap.verify_integrity(),

        'capital':  data.get('capital'),
        'caja':     data.get('caja_bob'),
        'divisas':  data.get('divisas'),
        'tarjetas': data.get('tarjetas'),
    })


# ════════════════════════════════════════════════════════════════════════════
# C3 / C4 / C6 — Posición de capital, P&L, historial, alertas y KPIs
# ════════════════════════════════════════════════════════════════════════════

def _resolve_branch_id(request):
    """Extrae branch_id del query param o del usuario autenticado."""
    bid = request.query_params.get('branch_id')
    if bid:
        try:
            return int(bid)
        except ValueError:
            return None
    return getattr(request.user, 'branch_id', None)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capital_position_view(request):
    """
    GET /api/capital/position/
    Posición en tiempo real (cache 30 s).
    """
    branch_id = _resolve_branch_id(request)
    if not branch_id:
        return Response({'error': 'branch_id requerido'}, status=status.HTTP_400_BAD_REQUEST)

    force = request.query_params.get('refresh', '').lower() in ('1', 'true')
    try:
        from capital.position_service import CapitalPositionService
        svc  = CapitalPositionService()
        snap = svc.get_real_time_position(branch_id, force=force)
        return Response(svc._serialize_snapshot(snap))
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
    except Exception as exc:
        log.error('CAPITAL_POSITION_ERR branch=%s err=%s', branch_id, exc, exc_info=True)
        return Response({'error': 'Error calculando posición'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capital_pnl_view(request):
    """
    GET /api/capital/pnl/?start=YYYY-MM-DD&end=YYYY-MM-DD
    P&L del período desaglosado.
    """
    branch_id = _resolve_branch_id(request)
    if not branch_id:
        return Response({'error': 'branch_id requerido'}, status=status.HTTP_400_BAD_REQUEST)

    start_str = request.query_params.get('start')
    end_str   = request.query_params.get('end')
    if not start_str or not end_str:
        return Response({'error': 'start y end requeridos (YYYY-MM-DD)'}, status=status.HTTP_400_BAD_REQUEST)

    start = parse_date(start_str)
    end   = parse_date(end_str)
    if not start or not end or start > end:
        return Response({'error': 'Fechas inválidas'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        from capital.position_service import CapitalPositionService
        svc = CapitalPositionService()
        pnl = svc.get_pnl_period(branch_id, start, end)
        return Response({
            'period_start':   pnl.period_start,
            'period_end':     pnl.period_end,
            'branch_id':      pnl.branch_id,
            'total_margin':   str(pnl.total_margin),
            'total_volume':   str(pnl.total_volume),
            'avg_margin_pct': str(pnl.avg_margin_pct),
            'by_currency':    pnl.by_currency,
            'by_cashier':     pnl.by_cashier,
        })
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
    except Exception as exc:
        log.error('CAPITAL_PNL_ERR err=%s', exc, exc_info=True)
        return Response({'error': 'Error calculando P&L'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capital_history_view(request):
    """
    GET /api/capital/history/?days=30&currency=USD
    Serie temporal de snapshots de posición diarios.
    """
    branch_id = _resolve_branch_id(request)
    if not branch_id:
        return Response({'error': 'branch_id requerido'}, status=status.HTTP_400_BAD_REQUEST)

    days = int(request.query_params.get('days', 30))
    currency_code = request.query_params.get('currency')
    since = timezone.localdate() - timezone.timedelta(days=days)

    try:
        from capital.models import CurrencyPositionHistory
        qs = CurrencyPositionHistory.objects.filter(
            position__branch_id=branch_id,
            fecha__gte=since,
        ).select_related('position__currency').order_by('fecha')

        if currency_code:
            qs = qs.filter(position__currency__code=currency_code)

        data = [
            {
                'fecha':                   str(h.fecha),
                'currency':                h.position.currency.code,
                'net_position':            str(h.net_position),
                'avg_acquisition_cost':    str(h.avg_acquisition_cost),
                'unrealized_pnl_parallel': str(h.unrealized_pnl_parallel),
                'unrealized_pnl_official': str(h.unrealized_pnl_official),
                'parallel_rate':           str(h.parallel_rate) if h.parallel_rate else None,
                'official_rate':           str(h.official_rate) if h.official_rate else None,
                'snapshot_type':           h.snapshot_type,
            }
            for h in qs
        ]
        return Response({'branch_id': branch_id, 'days': days, 'data': data})
    except Exception as exc:
        log.error('CAPITAL_HISTORY_ERR err=%s', exc, exc_info=True)
        return Response({'error': 'Error recuperando historial'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capital_alerts_view(request):
    """
    GET /api/capital/alerts/
    Alertas de capital activas: posición negativa, concentración, P&L negativo.
    Umbrales configurables desde settings.py:
      CAPITAL_MIN_BOB, CAPITAL_MAX_CONCENTRATION, CAPITAL_MIN_PNL_DAILY
    """
    branch_id = _resolve_branch_id(request)
    if not branch_id:
        return Response({'error': 'branch_id requerido'}, status=status.HTTP_400_BAD_REQUEST)

    from django.conf import settings as dj_settings
    alerts = []
    min_capital   = getattr(dj_settings, 'CAPITAL_MIN_BOB',           50_000)
    max_conc      = getattr(dj_settings, 'CAPITAL_MAX_CONCENTRATION',  0.60)
    min_pnl_daily = getattr(dj_settings, 'CAPITAL_MIN_PNL_DAILY',    -5_000)

    try:
        from capital.position_service import CapitalPositionService
        svc  = CapitalPositionService()
        snap = svc.get_real_time_position(branch_id)
        snap_dict = svc._serialize_snapshot(snap)

        net_par = float(snap_dict.get('net_capital_par', 0))
        if net_par < min_capital:
            alerts.append({
                'type': 'CAPITAL_MINIMO', 'severity': 'HIGH',
                'message': f'Capital neto Bs {net_par:,.2f} < mínimo Bs {min_capital:,.2f}',
            })

        total_foreign = float(snap_dict.get('total_foreign_par', 0))
        for cur in snap_dict.get('currencies', []):
            units = float(cur.get('net_units', 0))
            code  = cur.get('currency_code', '?')
            if units < 0:
                alerts.append({
                    'type': 'POSICION_NEGATIVA', 'severity': 'CRITICAL',
                    'message': f'Posición negativa en {code}: {units:,.4f}',
                    'currency': code,
                })
            if total_foreign > 0:
                val  = float(cur.get('value_parallel_bob', 0))
                conc = val / total_foreign
                if conc > max_conc:
                    alerts.append({
                        'type': 'CONCENTRACION_ALTA', 'severity': 'MEDIUM',
                        'message': f'Concentración {code}: {conc*100:.1f}% > {max_conc*100:.0f}%',
                        'currency': code, 'concentration_pct': round(conc * 100, 2),
                    })
    except Exception as exc:
        log.warning('CAPITAL_ALERTS_POSITION_ERR err=%s', exc)

    try:
        from rates.profitability import ProfitabilityAnalyzer
        from users.models import Branch
        branch = Branch.objects.get(pk=branch_id)
        today  = timezone.localdate()
        rpt    = ProfitabilityAnalyzer().analyze(
            company_id=branch.company_id,
            date_from=today,
            date_to=today,
            branch_id=branch_id,
        )
        margin = float(str(rpt.total_margin_bob))
        if margin < min_pnl_daily:
            alerts.append({
                'type': 'PNL_DIARIO_NEGATIVO', 'severity': 'HIGH',
                'message': f'P&L del día: Bs {margin:,.2f} < umbral Bs {min_pnl_daily:,.2f}',
            })
    except Exception as exc:
        log.warning('CAPITAL_ALERTS_PNL_ERR err=%s', exc)

    return Response({
        'branch_id': branch_id, 'alert_count': len(alerts),
        'alerts': alerts, 'checked_at': timezone.now().isoformat(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capital_kpis_view(request):
    """
    GET /api/capital/metrics/kpis/
    KPIs de negocio: ROE, rotación, WACC, break-even spread, etc.
    """
    branch_id = _resolve_branch_id(request)
    if not branch_id:
        return Response({'error': 'branch_id requerido'}, status=status.HTTP_400_BAD_REQUEST)

    force = request.query_params.get('refresh', '').lower() in ('1', 'true')
    try:
        from capital.metrics import CapitalKPIService
        kpis = CapitalKPIService().get_kpis(branch_id, force=force)
        return Response(kpis)
    except Exception as exc:
        log.error('CAPITAL_KPIS_ERR err=%s', exc, exc_info=True)
        return Response({'error': 'Error calculando KPIs'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Acreedores (cuentas por pagar) ──────────────────────────────────────────

# saldo por acreedor = Σ(CARGO) − Σ(ABONO), calculado por annotate (sin N+1).
_SALDO_ANNOT = Coalesce(
    Sum(Case(
        When(movimientos__tipo='CARGO', then=F('movimientos__monto_bob')),
        When(movimientos__tipo='ABONO', then=-F('movimientos__monto_bob')),
        output_field=_SALDO_DF,
    )),
    Value(Decimal('0'), output_field=_SALDO_DF),
)


class AcreedorViewSet(viewsets.ModelViewSet):
    """CRUD de acreedores (cuentas por pagar). El saldo se anota, no se guarda."""
    queryset           = Acreedor.objects.select_related('branch').all()
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return CrearAcreedorSerializer
        return AcreedorSerializer

    def get_queryset(self):
        qs = _company_branch_filter(super().get_queryset(), self.request.user)
        if self.request.query_params.get('activos') == 'true':
            qs = qs.filter(is_active=True)
        return qs.annotate(saldo_bob=_SALDO_ANNOT).order_by('nombre')

    @action(detail=False, methods=['GET'], url_path='resumen')
    def resumen(self, request):
        """Total adeudado (Σ saldos) y cantidad de acreedores con saldo > 0."""
        qs = self.get_queryset()
        con_saldo = [a for a in qs if (a.saldo_bob or 0) > 0]
        total = sum((a.saldo_bob or Decimal('0')) for a in con_saldo)
        return Response({
            'total_adeudado_bob': str(total),
            'acreedores_con_saldo': len(con_saldo),
            'acreedores_total': qs.count(),
        })


class MovimientoAcreedorViewSet(viewsets.ModelViewSet):
    """Ledger de cargos/abonos por acreedor."""
    queryset           = MovimientoAcreedor.objects.select_related(
        'acreedor', 'registrado_por').all()
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return CrearMovimientoAcreedorSerializer
        return MovimientoAcreedorSerializer

    def get_queryset(self):
        qs = _company_branch_filter(super().get_queryset(), self.request.user,
                                    branch_field='acreedor__branch')
        acreedor_id = self.request.query_params.get('acreedor')
        if acreedor_id:
            qs = qs.filter(acreedor_id=acreedor_id)
        return qs.order_by('-fecha', '-created_at')


# ── Caja chica ──────────────────────────────────────────────────────────────

class MovimientoCajaChicaViewSet(viewsets.ModelViewSet):
    """Ledger de caja chica. Saldo = Σ(APERTURA+INGRESO) − Σ(EGRESO)."""
    queryset           = MovimientoCajaChica.objects.select_related(
        'branch', 'registrado_por').all()
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return CrearMovimientoCajaChicaSerializer
        return MovimientoCajaChicaSerializer

    def get_queryset(self):
        qs = _company_branch_filter(super().get_queryset(), self.request.user)
        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(fecha__gte=date_from)
        if date_to:
            qs = qs.filter(fecha__lte=date_to)
        return qs.order_by('-fecha', '-created_at')

    @action(detail=False, methods=['GET'], url_path='saldo')
    def saldo(self, request):
        """Saldo vigente de caja chica del ámbito del usuario."""
        agg = self.get_queryset().aggregate(
            saldo=Coalesce(Sum(Case(
                When(tipo='EGRESO', then=-F('monto_bob')),
                default=F('monto_bob'),
                output_field=_SALDO_DF,
            )), Value(Decimal('0'), output_field=_SALDO_DF)))
        return Response({'saldo_bob': str(agg['saldo'])})


