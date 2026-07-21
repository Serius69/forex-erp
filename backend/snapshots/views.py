# snapshots/views.py
"""
API de snapshots del sistema.

Endpoints:
  GET  /api/snapshots/              — lista paginada (sin data_json)
  GET  /api/snapshots/{id}/         — detalle completo con data_json
  POST /api/snapshots/              — crear snapshot on-demand
  GET  /api/snapshots/compare/      — diff entre dos snapshots (?id1=&id2=)
  GET  /api/snapshots/latest/       — último snapshot de cada módulo
  POST /api/snapshots/{id}/verify/  — verificar integridad del checksum

Filtros disponibles para el listado:
  ?module=forex|tarjetas|capital|gastos|caja_bob|inventory|manual|system
  ?action=create|update|delete|transaction|apertura|cierre|on_demand
  ?branch_id=<int>
  ?date_from=YYYY-MM-DD
  ?date_to=YYYY-MM-DD
  ?user_id=<int>
"""
import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils.dateparse import parse_date
from django.utils import timezone

from .models import SystemSnapshot
from .serializers import (
    SystemSnapshotListSerializer,
    SystemSnapshotDetailSerializer,
    SnapshotOnDemandSerializer,
)
from .services import SnapshotService
from .comparison import SnapshotComparisonEngine
from users.permissions import IsAdminOrSupervisor

log = logging.getLogger('snapshots')


class SystemSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de snapshots del sistema.

    Lectura: cualquier usuario autenticado.
    Creación on-demand: ADMIN o SUPERVISOR solamente.
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = SystemSnapshot.objects.select_related('user', 'branch').all()

        user = self.request.user
        if getattr(user, 'company_id', None):
            qs = qs.filter(branch__company_id=user.company_id)
        if user.role != 'ADMIN':
            branch = getattr(user, 'branch', None)
            if branch:
                qs = qs.filter(branch=branch)

        # Parámetros de filtrado
        params = self.request.query_params

        module    = params.get('module')
        action_p  = params.get('action')
        branch_id = params.get('branch_id')
        date_from = params.get('date_from')
        date_to   = params.get('date_to')
        user_id   = params.get('user_id')

        if module:
            qs = qs.filter(module=module)
        if action_p:
            qs = qs.filter(action=action_p)
        if branch_id and user.role == 'ADMIN':
            qs = qs.filter(branch_id=branch_id)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if date_from:
            d = parse_date(str(date_from))
            if d:
                qs = qs.filter(timestamp__date__gte=d)
        if date_to:
            d = parse_date(str(date_to))
            if d:
                qs = qs.filter(timestamp__date__lte=d)

        return qs.order_by('-timestamp')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return SystemSnapshotDetailSerializer
        return SystemSnapshotListSerializer

    # ── POST /api/snapshots/  — snapshot on-demand ────────────────────────────

    def create(self, request, *args, **kwargs):
        """
        POST /api/snapshots/

        Crea un snapshot del estado actual del sistema de forma inmediata.
        Requiere rol ADMIN o SUPERVISOR.

        Body (opcional):
          { "module": "manual", "notas": "Cierre de quincena" }
        """
        if request.user.role not in ('ADMIN', 'SUPERVISOR'):
            return Response(
                {'error': 'Solo ADMIN o SUPERVISOR pueden crear snapshots on-demand'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ser = SnapshotOnDemandSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data

        branch = request.user.branch if request.user.role != 'ADMIN' else None
        admin_branch_id = request.data.get('branch_id')
        if admin_branch_id and request.user.role == 'ADMIN':
            from users.models import Branch
            try:
                branch = Branch.objects.get(pk=admin_branch_id)
            except Branch.DoesNotExist:
                return Response({'error': 'Sucursal no encontrada'}, status=404)

        snap = SnapshotService.create(
            module   = vd.get('module', 'manual'),
            action   = 'on_demand',
            user     = request.user,
            branch   = branch,
            metadata = {
                'notas':         vd.get('notas', ''),
                'requested_by':  request.user.username,
                'triggered_at':  timezone.now().isoformat(),
            },
            force    = True,  # On-demand nunca es debounced
        )

        if snap is None:
            return Response(
                {'error': 'No se pudo crear el snapshot. Revise los logs.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        log.info(
            'SNAPSHOT_ON_DEMAND id=%s by=%s branch=%s',
            snap.id, request.user.username,
            branch.code if branch else 'ALL',
        )
        return Response(
            SystemSnapshotDetailSerializer(snap).data,
            status=status.HTTP_201_CREATED,
        )

    # ── GET /api/snapshots/compare/ ───────────────────────────────────────────

    @action(detail=False, methods=['GET'], url_path='compare')
    def compare(self, request):
        """
        GET /api/snapshots/compare/?id1=<int>&id2=<int>

        Compara dos snapshots con análisis completo de capital y detección
        de anomalías.  El orden de id1/id2 no importa — se ordenan
        automáticamente por timestamp (más antiguo = snap1).

        Response:
        {
          "id1": int, "id2": int,
          "timestamp1": str, "timestamp2": str,
          "diff": { ... },           ← deep diff recursivo de data_json

          "capital_diff": {
            "total_bob":    { before, after, delta, delta_pct, changed },
            "efectivo_bob": { ... },
            "divisas": {
              "USD": { before_stock, after_stock, delta_stock, delta_stock_pct,
                       before_valor_bob, after_valor_bob, delta_valor_bob,
                       tc_venta, changed },
            },
            "tarjetas": { "TIGO 10": { ... }, ... },
            "gather_errors_snap1": null | [...],
            "gather_errors_snap2": null | [...],
          },

          "alerts": [
            {
              "type": "LOSS_DETECTED",
              "severity": "CRITICAL",
              "message": "...",
              "field": "capital.total_bob",
              "before": "190000.00",
              "after": "185000.00",
              "delta": "-5000.00",
              "delta_pct": "-2.63",
              "currency": "BOB",
              "amount": "-5000.00"
            }
          ],

          "summary": {
            "modules_changed": [...],
            "total_fields_changed": int,
            "time_delta_seconds": float,
            "capital_delta_bob": "+5000.00",
            "integrity_ok_1": true,
            "integrity_ok_2": true,
            "has_critical_alerts": bool,
            "alert_count": int,
            "alert_types": [str, ...]
          }
        }

        Alert types
        -----------
        LOSS_DETECTED      — Capital total decreased beyond threshold
        NEGATIVE_BALANCE   — Any balance is < 0
        INVENTORY_MISMATCH — physical + digital ≠ total for a currency
        SUDDEN_SPIKE       — Capital increased unusually fast
        EFECTIVO_DROP      — Cash-on-hand fell beyond threshold
        CURRENCY_DROP      — Individual currency stock fell > threshold %
        INTEGRITY_FAILURE  — SHA-256 checksum mismatch
        """
        id1 = request.query_params.get('id1')
        id2 = request.query_params.get('id2')

        if not id1 or not id2:
            return Response(
                {'error': 'Se requieren los parámetros id1 e id2'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            id1, id2 = int(id1), int(id2)
        except ValueError:
            return Response(
                {'error': 'id1 e id2 deben ser enteros'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if id1 == id2:
            return Response(
                {'error': 'id1 e id2 no pueden ser el mismo snapshot'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = self.get_queryset()
        try:
            snap1 = qs.get(pk=id1)
            snap2 = qs.get(pk=id2)
        except SystemSnapshot.DoesNotExist:
            return Response(
                {'error': 'Uno o ambos snapshots no encontrados o sin acceso'},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = SnapshotComparisonEngine(snap1, snap2).run()
        return Response(result)

    # ── GET /api/snapshots/latest/ ────────────────────────────────────────────

    @action(detail=False, methods=['GET'], url_path='latest')
    def latest(self, request):
        """
        GET /api/snapshots/latest/

        Retorna el último snapshot de cada módulo.
        Útil para el dashboard de estado del sistema.

        Response:
        {
          "forex":    { id, timestamp, capital_total_bob, ... },
          "tarjetas": { ... },
          "capital":  { ... },
          ...
        }
        """
        result = {}
        modules = [m[0] for m in SystemSnapshot.MODULE_CHOICES]
        qs = self.get_queryset()

        for module in modules:
            snap = qs.filter(module=module).first()
            if snap:
                result[module] = SystemSnapshotListSerializer(snap).data

        return Response({
            'count':      len(result),
            'by_module':  result,
            'fetched_at': timezone.now().isoformat(),
        })

    # ── POST /api/snapshots/{id}/verify/ ─────────────────────────────────────

    @action(detail=True, methods=['POST'], url_path='verify',
            permission_classes=[IsAdminOrSupervisor])
    def verify(self, request, pk=None):
        """
        POST /api/snapshots/{id}/verify/

        Verifica la integridad del snapshot comparando el checksum almacenado
        contra el SHA-256 calculado del data_json actual.

        Response:
        {
          "id": int,
          "checksum_stored": "abc...",
          "checksum_computed": "abc...",
          "integrity_ok": true
        }
        """
        snap = self.get_object()
        computed = SystemSnapshot._compute_checksum(snap.data_json)
        integrity_ok = snap.checksum == computed

        if not integrity_ok:
            log.critical(
                'SNAPSHOT_INTEGRITY_FAIL id=%s stored=%s computed=%s',
                snap.id, snap.checksum, computed,
            )

        return Response({
            'id':               snap.id,
            'checksum_stored':  snap.checksum,
            'checksum_computed': computed,
            'integrity_ok':     integrity_ok,
            'message': (
                'Snapshot íntegro — data_json no fue modificado.'
                if integrity_ok else
                '⚠ INTEGRIDAD COMPROMETIDA — el checksum no coincide.'
            ),
        })

    # ── Deshabilitar update/delete (snapshots son inmutables) ─────────────────

    def update(self, request, *args, **kwargs):
        return Response({'error': 'Los snapshots son inmutables'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response({'error': 'Los snapshots son inmutables'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response({'error': 'Los snapshots no pueden eliminarse'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)
