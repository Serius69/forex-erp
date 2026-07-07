# tarjetas/views.py
import logging
from decimal import Decimal
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q
from django.utils import timezone

from django.core.cache import cache
from .models import TipoTarjeta, LoteCompra, VentaTarjeta, MovimientoTarjeta, AlertaInventarioTarjeta
from .serializers import (
    TipoTarjetaSerializer, LoteCompraSerializer, VentaTarjetaSerializer,
    RegistrarLoteSerializer, RegistrarVentaSerializer,
    ComprarTarjetaSerializer, VenderTarjetaSerializer,
    MovimientoTarjetaSerializer, LoteAPICreateSerializer,
)
from .services import TarjetaService
from users.permissions import IsAdminOrSupervisor
from core.ratelimit import rate_limit

log = logging.getLogger('tarjetas')


class TipoTarjetaViewSet(viewsets.ModelViewSet):
    """CRUD de tipos de tarjeta + inventario en tiempo real."""
    queryset           = TipoTarjeta.objects.filter(is_active=True)
    serializer_class   = TipoTarjetaSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['GET'], url_path='inventario')
    def inventario(self, request):
        """Snapshot del inventario de tarjetas con stock y valores."""
        data = TarjetaService.inventario_completo()
        return Response(data)

    @action(detail=True, methods=['POST'], url_path='registrar-lote',
            permission_classes=[IsAdminOrSupervisor])
    @rate_limit(requests=20, window=60, scope='user')
    def registrar_lote(self, request, pk=None):
        """Registra un lote de compra de tarjetas para este tipo."""
        tipo = self.get_object()
        ser  = RegistrarLoteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd   = ser.validated_data

        lote = TarjetaService.registrar_lote(
            tipo_tarjeta   = tipo,
            cantidad       = vd['cantidad'],
            precio_costo   = vd['precio_costo'],
            registrado_por = request.user,
            proveedor      = vd.get('proveedor', 'Proveedor'),
            numero_factura = vd.get('numero_factura', ''),
            notas          = vd.get('notas', ''),
            fecha_compra   = vd.get('fecha_compra'),
        )
        return Response(LoteCompraSerializer(lote).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['POST'], url_path='vender')
    @rate_limit(requests=30, window=60, scope='user')
    def vender(self, request, pk=None):
        """Registra la venta de tarjetas de este tipo (FIFO)."""
        tipo = self.get_object()
        ser  = RegistrarVentaSerializer(data={**request.data, 'tipo_tarjeta_id': tipo.pk})
        ser.is_valid(raise_exception=True)
        vd   = ser.validated_data

        if not getattr(request.user, 'branch', None):
            return Response(
                {'error': 'Usuario sin sucursal asignada'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            venta = TarjetaService.registrar_venta(
                tipo_tarjeta   = tipo,
                cantidad       = vd['cantidad'],
                precio_venta   = vd['precio_venta'],
                cajero         = request.user,
                branch         = request.user.branch,
                medio_pago     = vd.get('medio_pago', 'CASH'),
                cliente_nombre = vd.get('cliente_nombre', ''),
                cliente_tel    = vd.get('cliente_tel', ''),
                notas          = vd.get('notas', ''),
                comision_bob   = vd.get('comision_bob', Decimal('0')),
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Response exactamente según spec de API
        return Response({
            'venta_id':     venta.id,
            'numero_venta': venta.numero_venta,
            'cantidad':     venta.cantidad,
            'total_bob':    str(venta.total_bob),
            'costo_fifo_bob': str(venta.costo_fifo_bob),
            'ganancia_bob': str(venta.ganancia_bob),
        }, status=status.HTTP_201_CREATED)


class LoteCompraViewSet(viewsets.ModelViewSet):
    """
    Lotes de compra de tarjetas.

    GET  /api/tarjetas/lotes/      — lista de lotes
    POST /api/tarjetas/lotes/      — registrar nuevo lote (ADMIN/SUPERVISOR)
    GET  /api/tarjetas/lotes/{id}/ — detalle de lote
    """
    queryset           = LoteCompra.objects.select_related('tipo_tarjeta', 'registrado_por').all()
    serializer_class   = LoteCompraSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        tipo_id   = self.request.query_params.get('tipo_tarjeta')
        is_active = self.request.query_params.get('activos')
        if tipo_id:
            qs = qs.filter(tipo_tarjeta_id=tipo_id)
        if is_active == 'true':
            qs = qs.filter(is_active=True, cantidad_restante__gt=0)
        return qs.order_by('fecha_compra')

    def create(self, request, *args, **kwargs):
        """
        POST /api/tarjetas/lotes/

        Acepta el formato del API spec:
          { tipo_tarjeta, proveedor, cantidad_total, precio_costo,
            numero_factura, fecha_compra }
        Solo ADMIN o SUPERVISOR pueden registrar lotes.
        """
        if request.user.role not in ('ADMIN', 'SUPERVISOR'):
            return Response(
                {'error': 'Solo ADMIN o SUPERVISOR pueden registrar lotes'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ser = LoteAPICreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd  = ser.validated_data

        lote = TarjetaService.registrar_lote(
            tipo_tarjeta   = vd['tipo_tarjeta'],
            cantidad       = vd['cantidad_total'],
            precio_costo   = vd['precio_costo'],
            registrado_por = request.user,
            proveedor      = vd.get('proveedor', 'Proveedor'),
            numero_factura = vd.get('numero_factura', ''),
            notas          = vd.get('notas', ''),
            fecha_compra   = vd.get('fecha_compra'),
            branch         = getattr(request.user, 'branch', None),
        )
        log.info(
            'LOTE_CREATED id=%s tipo=%s cantidad=%s by=%s',
            lote.id, vd['tipo_tarjeta'], vd['cantidad_total'], request.user.username,
        )
        return Response(LoteCompraSerializer(lote).data, status=status.HTTP_201_CREATED)

    # Deshabilitar update y delete — lotes son inmutables una vez registrados
    def update(self, request, *args, **kwargs):
        return Response({'error': 'Los lotes no pueden modificarse'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response({'error': 'Los lotes no pueden eliminarse'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


class VentaTarjetaViewSet(viewsets.GenericViewSet,
                          viewsets.mixins.ListModelMixin,
                          viewsets.mixins.RetrieveModelMixin):
    """Consulta de ventas de tarjetas + resumen de ganancias + anulación."""
    queryset           = VentaTarjeta.objects.select_related(
        'tipo_tarjeta', 'cajero', 'branch'
    ).prefetch_related('detalles_lote__lote').all()
    serializer_class   = VentaTarjetaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(user, 'company_id', None):
            qs = qs.filter(branch__company_id=user.company_id)
        if user.role != 'ADMIN':
            qs = qs.filter(branch=user.branch)

        tipo_id   = self.request.query_params.get('tipo_tarjeta')
        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        if tipo_id:
            qs = qs.filter(tipo_tarjeta_id=tipo_id)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs.order_by('-created_at')

    @action(detail=False, methods=['GET'], url_path='resumen')
    def resumen(self, request):
        """Resumen de ventas y ganancias de tarjetas por período."""
        date_from = request.query_params.get('date_from', str(timezone.localdate()))
        date_to   = request.query_params.get('date_to',   str(timezone.localdate()))

        qs = self.get_queryset().filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )

        agg = qs.aggregate(
            total_ventas    = Count('id'),
            total_unidades  = Sum('cantidad'),
            total_ingresos  = Sum('total_bob'),
            total_costo     = Sum('costo_fifo_bob'),
            total_ganancia  = Sum('ganancia_bob'),
        )

        por_tipo = list(qs.values(
            'tipo_tarjeta__nombre',
            'tipo_tarjeta__operadora',
        ).annotate(
            ventas   = Count('id'),
            unidades = Sum('cantidad'),
            ingresos = Sum('total_bob'),
            ganancia = Sum('ganancia_bob'),
        ).order_by('-ganancia'))

        return Response({
            'periodo':    {'desde': date_from, 'hasta': date_to},
            'totales':    agg,
            'por_tipo':   por_tipo,
        })

    @action(detail=True, methods=['POST'], url_path='anular',
            permission_classes=[IsAdminOrSupervisor])
    @rate_limit(requests=10, window=60, scope='user')
    def anular(self, request, pk=None):
        """POST /api/tarjetas/ventas/{id}/anular/ — anula la venta con motivo."""
        venta = self.get_object()
        motivo = request.data.get('motivo', '').strip()
        if not motivo:
            return Response(
                {'error': 'El campo motivo es obligatorio.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            venta = TarjetaService.anular_venta(venta, motivo, request.user)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(VentaTarjetaSerializer(venta).data)


# ══════════════════════════════════════════════════════════════════════════════
# Top-level endpoints: /api/tarjetas/comprar/ · /vender/ · /inventario/
# ══════════════════════════════════════════════════════════════════════════════

class ComprarTarjetaView(GenericAPIView):
    """
    POST /api/tarjetas/comprar/

    Registra la compra de un lote de tarjetas (aumenta stock).
    Requiere rol ADMIN o SUPERVISOR.

    Ejemplo:
        POST /api/tarjetas/comprar/
        {
            "tipo_tarjeta_id": 1,
            "cantidad": 100,
            "precio_costo": "4.50",
            "proveedor": "Distribuidora Tigo S.A.",
            "numero_factura": "FAC-2026-0042",
            "fecha_compra": "2026-04-12",
            "notas": "Lote mensual"
        }
    """
    serializer_class   = ComprarTarjetaSerializer
    permission_classes = [IsAdminOrSupervisor]

    @rate_limit(requests=30, window=60, scope='user')
    def post(self, request):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd  = ser.validated_data

        lote = TarjetaService.registrar_lote(
            tipo_tarjeta   = vd['tipo_tarjeta'],
            cantidad       = vd['cantidad'],
            precio_costo   = vd['precio_costo'],
            registrado_por = request.user,
            proveedor      = vd.get('proveedor', 'Proveedor'),
            numero_factura = vd.get('numero_factura', ''),
            notas          = vd.get('notas', ''),
            fecha_compra   = vd.get('fecha_compra'),
            branch         = getattr(request.user, 'branch', None),
        )
        return Response(LoteCompraSerializer(lote).data, status=status.HTTP_201_CREATED)


class VenderTarjetaView(GenericAPIView):
    """
    POST /api/tarjetas/vender/

    Registra la venta de tarjetas a un cliente (FIFO, disminuye stock).
    Cualquier cajero autenticado puede vender.

    Ejemplo:
        POST /api/tarjetas/vender/
        {
            "tipo_tarjeta_id": 1,
            "cantidad": 3,
            "precio_venta": "6.00",
            "comision_bob": "0",
            "medio_pago": "CASH",
            "cliente_nombre": "Juan Mamani",
            "cliente_tel": "71234567"
        }
    """
    serializer_class   = VenderTarjetaSerializer
    permission_classes = [IsAuthenticated]

    @rate_limit(requests=30, window=60, scope='user')
    def post(self, request):
        if not getattr(request.user, 'branch', None):
            return Response(
                {'error': 'Usuario sin sucursal asignada.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd  = ser.validated_data

        try:
            venta = TarjetaService.registrar_venta(
                tipo_tarjeta   = vd['tipo_tarjeta'],
                cantidad       = vd['cantidad'],
                precio_venta   = vd['precio_venta'],
                cajero         = request.user,
                branch         = request.user.branch,
                medio_pago     = vd.get('medio_pago', 'CASH'),
                cliente_nombre = vd.get('cliente_nombre', ''),
                cliente_tel    = vd.get('cliente_tel', ''),
                notas          = vd.get('notas', ''),
                comision_bob   = vd.get('comision_bob', Decimal('0')),
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(VentaTarjetaSerializer(venta).data, status=status.HTTP_201_CREATED)


class InventarioTarjetaView(GenericAPIView):
    """
    GET /api/tarjetas/inventario/

    Snapshot completo del inventario de tarjetas con stock, costo promedio
    (ponderado FIFO), valor total en BOB y resumen de ganancias del día.

    Parámetros opcionales:
        ?operadora=TIGO          — filtrar por operadora
        ?con_stock=true          — solo tipos con stock > 0
        ?date_from=YYYY-MM-DD    — para incluir ganancias del período
        ?date_to=YYYY-MM-DD
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        hoy       = timezone.localdate()
        date_from = request.query_params.get('date_from', str(hoy))
        date_to   = request.query_params.get('date_to',   str(hoy))
        operadora = request.query_params.get('operadora')
        con_stock = request.query_params.get('con_stock') == 'true'

        tipos_qs = TipoTarjeta.objects.filter(is_active=True).prefetch_related('lotes')
        if operadora:
            tipos_qs = tipos_qs.filter(operadora=operadora.upper())

        inventario = []
        total_stock   = 0
        total_valor   = Decimal('0')

        for t in tipos_qs:
            stock = t.stock_actual
            if con_stock and stock == 0:
                continue

            # Ganancias del período para este tipo
            ganancia_periodo = (
                VentaTarjeta.objects
                .filter(
                    tipo_tarjeta=t,
                    created_at__date__gte=date_from,
                    created_at__date__lte=date_to,
                )
                .aggregate(g=Sum('ganancia_bob'))['g'] or Decimal('0')
            )

            # Lotes activos para desglose
            lotes_activos = list(
                t.lotes.filter(is_active=True, cantidad_restante__gt=0)
                .values('id', 'precio_costo', 'cantidad_restante',
                        'proveedor', 'fecha_compra')
                .order_by('fecha_compra')
            )

            costo_prom = t.costo_promedio
            valor_inv  = t.valor_inventario_bob
            total_stock += stock
            total_valor += valor_inv

            inventario.append({
                'id':              t.id,
                'nombre':          t.nombre,
                'operadora':       t.operadora,
                'denominacion':    str(t.denominacion),
                'stock':           stock,
                'costo_promedio':  str(costo_prom),
                'valor_inventario': str(valor_inv),
                'ganancia_periodo': str(ganancia_periodo),
                'lotes_activos':   lotes_activos,
            })

        # Totales globales de ganancias del período
        ganancia_total = (
            VentaTarjeta.objects
            .filter(
                created_at__date__gte=date_from,
                created_at__date__lte=date_to,
            )
            .aggregate(g=Sum('ganancia_bob'))['g'] or Decimal('0')
        )
        ingresos_total = (
            VentaTarjeta.objects
            .filter(
                created_at__date__gte=date_from,
                created_at__date__lte=date_to,
            )
            .aggregate(i=Sum('total_bob'))['i'] or Decimal('0')
        )

        return Response({
            'periodo': {'desde': date_from, 'hasta': date_to},
            'resumen': {
                'total_tipos':         len(inventario),
                'total_unidades':      total_stock,
                'valor_inventario_bob': str(total_valor),
                'ingresos_periodo_bob': str(ingresos_total),
                'ganancia_periodo_bob': str(ganancia_total),
            },
            'inventario': inventario,
        })


class MovimientoTarjetaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/tarjetas/movimientos/

    Libro diario unificado: compras y ventas de tarjetas en una sola vista.
    Filtros: ?tipo_movimiento=COMPRA|VENTA  ?tipo_tarjeta=ID
             ?date_from=YYYY-MM-DD  ?date_to=YYYY-MM-DD
    """
    queryset           = MovimientoTarjeta.objects.select_related(
        'tipo_tarjeta', 'usuario', 'branch', 'lote_compra', 'venta_tarjeta',
    ).all()
    serializer_class   = MovimientoTarjetaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(user, 'company_id', None):
            qs = qs.filter(branch__company_id=user.company_id)
        if user.role != 'ADMIN':
            qs = qs.filter(branch=user.branch)

        tipo_mov  = self.request.query_params.get('tipo_movimiento')
        tipo_id   = self.request.query_params.get('tipo_tarjeta')
        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')

        if tipo_mov:
            qs = qs.filter(tipo_movimiento=tipo_mov.upper())
        if tipo_id:
            qs = qs.filter(tipo_tarjeta_id=tipo_id)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs.order_by('-created_at')

    @action(detail=False, methods=['GET'], url_path='profit')
    def profit(self, request):
        """
        GET /api/tarjetas/movimientos/profit/?date_from=…&date_to=…

        P&L de tarjetas: ingresos, costo FIFO, ganancia neta, margen %.
        Desglosado por operadora y tipo de tarjeta.
        """
        hoy       = str(timezone.localdate())
        date_from = request.query_params.get('date_from', hoy)
        date_to   = request.query_params.get('date_to',   hoy)

        ventas_qs = VentaTarjeta.objects.filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )
        compras_qs = LoteCompra.objects.filter(
            fecha_compra__gte=date_from,
            fecha_compra__lte=date_to,
        )

        # Totales de ventas
        v_agg = ventas_qs.aggregate(
            unidades_vendidas = Sum('cantidad'),
            ingresos_bob      = Sum('total_bob'),
            costo_fifo_bob    = Sum('costo_fifo_bob'),
            ganancia_bob      = Sum('ganancia_bob'),
        )
        # Totales de compras
        c_agg = compras_qs.aggregate(
            unidades_compradas = Sum('cantidad_total'),
            invertido_bob      = Sum('precio_costo'),
        )

        ingresos  = v_agg['ingresos_bob']  or Decimal('0')
        costo     = v_agg['costo_fifo_bob'] or Decimal('0')
        ganancia  = v_agg['ganancia_bob']  or Decimal('0')
        margen_pct = round(float(ganancia / ingresos * 100), 2) if ingresos else 0

        # Por operadora
        por_operadora = list(
            ventas_qs.values('tipo_tarjeta__operadora')
            .annotate(
                ingresos = Sum('total_bob'),
                costo    = Sum('costo_fifo_bob'),
                ganancia = Sum('ganancia_bob'),
                unidades = Sum('cantidad'),
            ).order_by('-ganancia')
        )

        # Por tipo de tarjeta
        por_tipo = list(
            ventas_qs.values('tipo_tarjeta__nombre', 'tipo_tarjeta__operadora')
            .annotate(
                ingresos = Sum('total_bob'),
                costo    = Sum('costo_fifo_bob'),
                ganancia = Sum('ganancia_bob'),
                unidades = Sum('cantidad'),
            ).order_by('-ganancia')
        )

        return Response({
            'periodo': {'desde': date_from, 'hasta': date_to},
            'ventas': {
                'unidades_vendidas':  v_agg['unidades_vendidas'] or 0,
                'ingresos_bob':       str(ingresos),
                'costo_fifo_bob':     str(costo),
                'ganancia_neta_bob':  str(ganancia),
                'margen_pct':         margen_pct,
            },
            'compras': {
                'unidades_compradas': c_agg['unidades_compradas'] or 0,
                'invertido_bob':      str(c_agg['invertido_bob'] or Decimal('0')),
            },
            'por_operadora': por_operadora,
            'por_tipo':      por_tipo,
        })


# ══════════════════════════════════════════════════════════════════════════════
# Nuevos endpoints de inventario avanzado
# ══════════════════════════════════════════════════════════════════════════════

CACHE_KEY_POSICION = 'tarjetas:posicion_inventario'
CACHE_TTL_POSICION = 30  # segundos


class PosicionInventarioView(GenericAPIView):
    """
    GET /api/tarjetas/inventario/posicion/

    Posición valorizada del inventario. Cacheada 30 s en Redis.
    ?refresh=true fuerza recálculo.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        force = request.query_params.get('refresh') == 'true'
        if not force:
            cached = cache.get(CACHE_KEY_POSICION)
            if cached is not None:
                return Response(cached)

        branch = getattr(request.user, 'branch', None) if request.user.role != 'ADMIN' else None
        data = TarjetaService.get_posicion_inventario(branch=branch)
        cache.set(CACHE_KEY_POSICION, data, CACHE_TTL_POSICION)
        return Response(data)


class AlertasInventarioView(GenericAPIView):
    """
    GET /api/tarjetas/inventario/alertas/

    Tipos de tarjeta con stock bajo (warning) o crítico.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch = getattr(request.user, 'branch', None) if request.user.role != 'ADMIN' else None
        posicion = TarjetaService.get_posicion_inventario(branch=branch)

        alertas = [
            item for item in posicion['items']
            if item['estado_stock'] in ('bajo', 'critico')
        ]
        return Response({
            'total_alertas': len(alertas),
            'alertas': alertas,
        })


class HistorialMovimientosView(GenericAPIView):
    """
    GET /api/tarjetas/inventario/historial_movimientos/

    Timeline unificado de ingresos y ventas.
    Parámetros: ?dias=30 (default 30) &tipo_tarjeta=ID
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        dias     = int(request.query_params.get('dias', 30))
        tipo_id  = request.query_params.get('tipo_tarjeta')
        desde    = timezone.now() - timezone.timedelta(days=dias)

        qs = MovimientoTarjeta.objects.select_related(
            'tipo_tarjeta', 'usuario', 'branch',
        ).filter(created_at__gte=desde)

        user = request.user
        if getattr(user, 'company_id', None):
            qs = qs.filter(branch__company_id=user.company_id)
        if user.role != 'ADMIN' and getattr(user, 'branch', None):
            qs = qs.filter(branch=user.branch)
        if tipo_id:
            qs = qs.filter(tipo_tarjeta_id=tipo_id)

        from .serializers import MovimientoTarjetaSerializer
        data = MovimientoTarjetaSerializer(qs.order_by('-created_at')[:200], many=True).data
        return Response({'dias': dias, 'movimientos': data})


class KPIsTarjetasView(GenericAPIView):
    """
    GET /api/tarjetas/inventario/kpis/

    KPIs del módulo para el dashboard principal.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        hoy = timezone.localdate()
        inicio_mes = hoy.replace(day=1)

        posicion = TarjetaService.get_posicion_inventario()

        ventas_mes = VentaTarjeta.objects.filter(
            created_at__date__gte=inicio_mes,
            created_at__date__lte=hoy,
            estado='COMPLETADA',
        )
        v_agg = ventas_mes.aggregate(
            total_ventas   = Count('id'),
            total_unidades = Sum('cantidad'),
            ingresos_bob   = Sum('total_bob'),
            ganancia_bob   = Sum('ganancia_bob'),
        )

        alertas_count = sum(
            1 for item in posicion['items']
            if item['estado_stock'] in ('bajo', 'critico')
        )

        return Response({
            'inventario': posicion['resumen'],
            'mes': {
                'desde': str(inicio_mes),
                'hasta': str(hoy),
                'total_ventas':    v_agg['total_ventas'] or 0,
                'total_unidades':  v_agg['total_unidades'] or 0,
                'ingresos_bob':    str(v_agg['ingresos_bob'] or Decimal('0')),
                'ganancia_bob':    str(v_agg['ganancia_bob'] or Decimal('0')),
            },
            'alertas_activas': alertas_count,
        })
