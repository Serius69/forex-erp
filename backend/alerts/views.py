"""
AlertLogViewSet — API REST para gestión de alertas.

Endpoints
---------
GET  /api/alerts/                      → lista paginada (filtros: severity, source, is_acknowledged)
GET  /api/alerts/{id}/                 → detalle de alerta
POST /api/alerts/{id}/acknowledge/     → reconocer alerta individual
POST /api/alerts/acknowledge_all/      → reconocer todas las alertas activas
GET  /api/alerts/summary/              → conteos por severidad/fuente + últimas 5
POST /api/alerts/generar/              → ejecutar motor de alertas para la sucursal
"""
import logging

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import AlertLog
from .serializers import AlertLogSerializer, AlertSummarySerializer
from tenants.permissions import IsCompanyMember

log = logging.getLogger('kapitalya.alerts')

# Queryset base reutilizable (select_related previene N+1)
_BASE_QS = AlertLog.objects.select_related(
    'branch', 'triggered_by', 'acknowledged_by',
)


class AlertLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API de sólo lectura + acciones de reconocimiento.
    No se crean ni eliminan alertas desde aquí — sólo el backend las genera.
    """
    permission_classes = [IsAuthenticated, IsCompanyMember]
    serializer_class   = AlertLogSerializer
    filter_backends    = [DjangoFilterBackend]
    filterset_fields   = ['severity', 'source', 'is_acknowledged']

    def get_queryset(self):
        user = self.request.user
        qs   = _BASE_QS.order_by('-created_at')

        # Tenant isolation
        if getattr(user, 'company_id', None):
            qs = qs.filter(branch__company_id=user.company_id)

        # Branch isolation for CASHIER
        if user.role == 'CASHIER' and user.branch_id:
            qs = qs.filter(branch_id=user.branch_id)

        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        # parse_date guards against frontend sending "null", "undefined", or
        # malformed strings that would cause a DB DataError → 500.
        if date_from:
            parsed_from = parse_date(str(date_from))
            if parsed_from:
                qs = qs.filter(created_at__date__gte=parsed_from)
        if date_to:
            parsed_to = parse_date(str(date_to))
            if parsed_to:
                qs = qs.filter(created_at__date__lte=parsed_to)

        return qs

    def list(self, request, *args, **kwargs):
        """Override to return structured JSON on DB errors instead of HTML 500."""
        try:
            return super().list(request, *args, **kwargs)
        except Exception as exc:
            log.exception('ALERTS_LIST_FAILED err=%s', exc)
            return Response(
                {'error': 'Error al obtener alertas', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ── POST /api/alerts/{id}/acknowledge/ ───────────────────────────────────

    @action(detail=True, methods=['post'], url_path='acknowledge')
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        if alert.is_acknowledged:
            return Response({'detail': 'Ya reconocida.'}, status=status.HTTP_200_OK)

        alert.acknowledge(user=request.user)
        return Response(AlertLogSerializer(alert).data)

    # ── POST /api/alerts/acknowledge_all/ ────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='acknowledge_all')
    def acknowledge_all(self, request):
        now    = timezone.now()
        source = request.data.get('source')

        qs = AlertLog.objects.filter(is_acknowledged=False)
        if source:
            qs = qs.filter(source=source)

        count = qs.update(
            is_acknowledged = True,
            acknowledged_by = request.user,
            acknowledged_at = now,
        )
        return Response({'acknowledged': count})

    # ── GET /api/alerts/summary/ ─────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        """
        Retorna conteos por severidad, por fuente y las últimas 5 alertas.
        Usa 3 queries optimizadas en lugar de iterar con Python.
        """
        try:
            active_qs = AlertLog.objects.filter(is_acknowledged=False)

            # Conteo por severidad — 1 query con GROUP BY
            sev_rows  = active_qs.values('severity').annotate(count=Count('id'))
            by_severity = {s: 0 for s in ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')}
            for row in sev_rows:
                by_severity[row['severity']] = row['count']

            # Conteo por fuente — 1 query con GROUP BY
            src_rows  = active_qs.values('source').annotate(count=Count('id'))
            by_source: dict = {}
            for row in src_rows:
                by_source[row['source']] = row['count']

            # Total activas — reusa el conteo acumulado (sin query extra)
            total_active = sum(by_severity.values())

            # Últimas 5 alertas — 1 query con select_related
            latest = _BASE_QS.order_by('-created_at')[:5]

            data = {
                'total_active': total_active,
                'by_severity':  by_severity,
                'by_source':    by_source,
                'latest':       AlertLogSerializer(latest, many=True).data,
            }
            return Response(data)

        except Exception as exc:
            log.exception('ALERT_SUMMARY_FAILED err=%s', exc)
            return Response(
                {'error': 'Error al obtener resumen de alertas', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ── POST /api/alerts/generar/ ────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='generar')
    def generar(self, request):
        """
        Ejecuta el motor de alertas para la sucursal del usuario.

        Body (opcional):
            currency: str  — evalúa solo esa divisa; omitir para todas

        Retorna:
            { alertas: [...], total: N, por_nivel: {CRITICAL: N, WARNING: N, INFO: N} }
        """
        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response(
                {'error': 'Usuario sin sucursal asignada'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        currency = (
            request.data.get('currency') or
            request.query_params.get('currency')
        )

        try:
            from .services import AlertGenerator
            alertas = AlertGenerator.generar_alertas(branch, currency=currency)
        except Exception as exc:
            log.exception('ALERT_GENERATOR_FAILED branch=%s err=%s', branch, exc)
            return Response(
                {'error': 'Error al generar alertas', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        conteos = {'CRITICAL': 0, 'WARNING': 0, 'INFO': 0}
        for a in alertas:
            nivel = a.get('nivel', 'INFO')
            conteos[nivel] = conteos.get(nivel, 0) + 1

        return Response({
            'alertas':   alertas,
            'total':     len(alertas),
            'por_nivel': conteos,
        })
