from datetime import date as dt
from django.http import FileResponse, Http404, HttpResponse
from core.utils import parse_date_range
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from users.permissions import IsAdminOrSupervisor
from core.ratelimit import rate_limit
from .models import (CashTransactionReport, SuspiciousActivityReport,
                      PEPRegistry, DailyOperationLog, GeneratedReport)
from .serializers import (RTESerializer, ROUESerializer, PEPSerializer,
                            DailyLogSerializer, GeneratedReportSerializer,
                            CreateROUESerializer, CreatePEPSerializer)

class GeneratedReportViewSet(viewsets.ReadOnlyModelViewSet):
    queryset           = GeneratedReport.objects.select_related('generated_by').order_by('-generated_at')
    serializer_class   = GeneratedReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.role != 'ADMIN':
            qs = qs.filter(generated_by=self.request.user)
        return qs

class RTEViewSet(viewsets.ReadOnlyModelViewSet):
    queryset          = CashTransactionReport.objects.select_related('transaction').all()
    serializer_class  = RTESerializer
    permission_classes= [IsAdminOrSupervisor]
    filterset_fields  = ['status', 'report_date', 'customer_is_pep']

    @action(detail=False, methods=['get'])
    @rate_limit(requests=10, window=60, scope='user')
    def monthly_report(self, request):
        year  = int(request.query_params.get('year',  dt.today().year))
        month = int(request.query_params.get('month', dt.today().month))
        from .services.asfi_service import ASFIReportService
        result = ASFIReportService.generate_rte_monthly(year, month, user=request.user)
        return Response(result)

    @action(detail=False, methods=['get'], url_path='download-excel')
    @rate_limit(requests=10, window=60, scope='user')
    def download_excel(self, request):
        year  = int(request.query_params.get('year',  dt.today().year))
        month = int(request.query_params.get('month', dt.today().month))
        from .services.asfi_service import ASFIReportService
        result = ASFIReportService.generate_rte_monthly(year, month, user=request.user)
        try:
            return FileResponse(open(result['excel_path'], 'rb'),
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                as_attachment=True,
                                filename=f'RTE_{year}{month:02d}.xlsx')
        except FileNotFoundError:
            raise Http404

    @action(detail=False, methods=['get'], url_path='download-pdf')
    @rate_limit(requests=10, window=60, scope='user')
    def download_pdf(self, request):
        year  = int(request.query_params.get('year',  dt.today().year))
        month = int(request.query_params.get('month', dt.today().month))
        from .services.asfi_service import ASFIReportService
        result = ASFIReportService.generate_rte_monthly(year, month, user=request.user)
        try:
            return FileResponse(open(result['pdf_path'], 'rb'),
                                content_type='application/pdf',
                                as_attachment=True,
                                filename=f'RTE_{year}{month:02d}.pdf')
        except FileNotFoundError:
            raise Http404

    @action(detail=False, methods=['get'], url_path='download-csv')
    @rate_limit(requests=10, window=60, scope='user')
    def download_csv(self, request):
        year  = int(request.query_params.get('year',  dt.today().year))
        month = int(request.query_params.get('month', dt.today().month))
        from .services.asfi_service import ASFIReportService
        path = ASFIReportService.generate_rte_csv(year, month, user=request.user)
        try:
            return FileResponse(open(path, 'rb'),
                                content_type='text/csv; charset=utf-8',
                                as_attachment=True,
                                filename=f'RTE_{year}{month:02d}.csv')
        except FileNotFoundError:
            raise Http404


class ROUEViewSet(viewsets.ModelViewSet):
    queryset          = SuspiciousActivityReport.objects.select_related('customer','detected_by').all()
    serializer_class  = ROUESerializer
    permission_classes= [IsAdminOrSupervisor]

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateROUESerializer
        return ROUESerializer

    @action(detail=True, methods=['get'], url_path='download-pdf')
    @rate_limit(requests=10, window=60, scope='user')
    def download_pdf(self, request, pk=None):
        from .services.asfi_service import ASFIReportService
        path = ASFIReportService.generate_roue_pdf(pk, user=request.user)
        try:
            sar = self.get_object()
            return FileResponse(open(path, 'rb'), content_type='application/pdf',
                                as_attachment=True,
                                filename=f'ROUE_{sar.report_number}.pdf')
        except FileNotFoundError:
            raise Http404


class PEPViewSet(viewsets.ModelViewSet):
    queryset          = PEPRegistry.objects.select_related('customer').all()
    serializer_class  = PEPSerializer
    permission_classes= [IsAdminOrSupervisor]

    def get_serializer_class(self):
        if self.action == 'create':
            return CreatePEPSerializer
        return PEPSerializer

    @action(detail=False, methods=['get'], url_path='download-excel')
    @rate_limit(requests=10, window=60, scope='user')
    def download_excel(self, request):
        year  = int(request.query_params.get('year',  dt.today().year))
        month = int(request.query_params.get('month', dt.today().month))
        from .services.asfi_service import ASFIReportService
        result = ASFIReportService.generate_pep_report(year=year, month=month, user=request.user)
        try:
            return FileResponse(open(result['excel_path'], 'rb'),
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                as_attachment=True,
                                filename=f'PEP_{year}{month:02d}.xlsx')
        except FileNotFoundError:
            raise Http404

    @action(detail=False, methods=['get'], url_path='download-pdf')
    @rate_limit(requests=10, window=60, scope='user')
    def download_pdf(self, request):
        year  = int(request.query_params.get('year',  dt.today().year))
        month = int(request.query_params.get('month', dt.today().month))
        from .services.asfi_service import ASFIReportService
        result = ASFIReportService.generate_pep_report(year=year, month=month, user=request.user)
        try:
            return FileResponse(open(result['pdf_path'], 'rb'),
                                content_type='application/pdf',
                                as_attachment=True,
                                filename=f'PEP_{year}{month:02d}.pdf')
        except FileNotFoundError:
            raise Http404


class DailyLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset          = DailyOperationLog.objects.select_related('branch', 'closed_by').all()
    serializer_class  = DailyLogSerializer
    permission_classes= [IsAdminOrSupervisor]

    @action(detail=False, methods=['post'], url_path='generate')
    @rate_limit(requests=10, window=60, scope='user')
    def generate(self, request):
        date_str  = request.data.get('date', str(dt.today()))
        # Default: sucursal del usuario (antes había un branch_id=1 fijo).
        branch_id = request.data.get('branch_id') or request.user.branch_id
        if not branch_id:
            return Response({'error': 'Debe indicar branch_id'}, status=400)

        # Aislamiento multi-tenant: la sucursal debe ser de la empresa del usuario.
        from users.models import Branch
        branch_qs = Branch.objects.all()
        if getattr(request.user, 'company_id', None):
            branch_qs = branch_qs.filter(company_id=request.user.company_id)
        if not branch_qs.filter(pk=branch_id).exists():
            return Response({'error': 'Sucursal no encontrada'}, status=404)

        from .services.asfi_service import ASFIReportService
        result = ASFIReportService.generate_daily_log(
            dt.fromisoformat(date_str), branch_id, user=request.user)
        return Response(result)

    @action(detail=True, methods=['get'], url_path='download-excel')
    @rate_limit(requests=10, window=60, scope='user')
    def download_excel(self, request, pk=None):
        log = self.get_object()
        return FileResponse(open(log.excel_file, 'rb'),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            as_attachment=True,
                            filename=f'LIBRO_DIARIO_{log.log_date}.xlsx')

    @action(detail=True, methods=['get'], url_path='download-pdf')
    @rate_limit(requests=10, window=60, scope='user')
    def download_pdf(self, request, pk=None):
        log = self.get_object()
        return FileResponse(open(log.pdf_file, 'rb'),
                            content_type='application/pdf',
                            as_attachment=True,
                            filename=f'LIBRO_DIARIO_{log.log_date}.pdf')

    @action(detail=True, methods=['get'], url_path='download-csv')
    @rate_limit(requests=10, window=60, scope='user')
    def download_csv(self, request, pk=None):
        # El CSV se genera al vuelo desde las transacciones del día del log
        # (mismo filtro visible_asfi que Excel/PDF).
        log = self.get_object()
        from .services.asfi_service import ASFIReportService
        path = ASFIReportService.generate_daily_log_csv(
            log.log_date, log.branch_id, user=request.user)
        return FileResponse(open(path, 'rb'),
                            content_type='text/csv; charset=utf-8',
                            as_attachment=True,
                            filename=f'LIBRO_DIARIO_{log.log_date}.csv')


class ManagementReportViewSet(viewsets.ViewSet):
    permission_classes = [IsAdminOrSupervisor]

    @action(detail=False, methods=['get'], url_path='pnl')
    @rate_limit(requests=20, window=60, scope='user')
    def pnl(self, request):
        date_from, date_to = parse_date_range(request, default_days=0)
        period = request.query_params.get('period', 'daily')
        fmt    = request.query_params.get('format', 'json')
        from .services.management_service import ManagementReportService
        result = ManagementReportService.generate_pnl(
            date_from, date_to, period=period, user=request.user)
        if fmt == 'excel':
            return FileResponse(open(result['excel_path'], 'rb'),
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                as_attachment=True, filename='PnG.xlsx')
        if fmt == 'pdf':
            return FileResponse(open(result['pdf_path'], 'rb'),
                                content_type='application/pdf',
                                as_attachment=True, filename='PnG.pdf')
        return Response(result)

    @action(detail=False, methods=['get'], url_path='profitability')
    @rate_limit(requests=20, window=60, scope='user')
    def profitability(self, request):
        date_from, date_to = parse_date_range(request, default_days=0)
        fmt = request.query_params.get('format', 'json')
        from .services.management_service import ManagementReportService
        result = ManagementReportService.generate_profitability(
            date_from, date_to, user=request.user)
        if fmt == 'excel':
            return FileResponse(open(result['excel_path'], 'rb'),
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                as_attachment=True, filename='Rentabilidad.xlsx')
        if fmt == 'pdf':
            return FileResponse(open(result['pdf_path'], 'rb'),
                                content_type='application/pdf',
                                as_attachment=True, filename='Rentabilidad.pdf')
        return Response(result)

    @action(detail=False, methods=['get'], url_path='client-ranking')
    @rate_limit(requests=20, window=60, scope='user')
    def client_ranking(self, request):
        date_from, date_to = parse_date_range(request, default_days=0)
        top_n = int(request.query_params.get('top_n', 20))
        fmt   = request.query_params.get('format', 'json')
        from .services.management_service import ManagementReportService
        result = ManagementReportService.generate_client_ranking(
            date_from, date_to, top_n=top_n, user=request.user)
        if fmt == 'excel':
            return FileResponse(open(result['excel_path'], 'rb'),
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                as_attachment=True, filename='RankingClientes.xlsx')
        if fmt == 'pdf':
            return FileResponse(open(result['pdf_path'], 'rb'),
                                content_type='application/pdf',
                                as_attachment=True, filename='RankingClientes.pdf')
        return Response(result)

    @action(detail=False, methods=['get'], url_path='comparative')
    @rate_limit(requests=20, window=60, scope='user')
    def comparative(self, request):
        date_from, date_to = parse_date_range(request, default_days=0)
        fmt = request.query_params.get('format', 'json')
        from .services.management_service import ManagementReportService
        result = ManagementReportService.generate_comparative(
            date_from, date_to, user=request.user)
        if fmt == 'excel':
            return FileResponse(open(result['excel_path'], 'rb'),
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                as_attachment=True, filename='Comparativo.xlsx')
        if fmt == 'pdf':
            return FileResponse(open(result['pdf_path'], 'rb'),
                                content_type='application/pdf',
                                as_attachment=True, filename='Comparativo.pdf')
        return Response(result)

    @action(detail=False, methods=['get'], url_path='cashflow')
    @rate_limit(requests=20, window=60, scope='user')
    def cashflow(self, request):
        base_date = dt.fromisoformat(
            request.query_params.get('base_date', str(dt.today())))
        days_ahead = int(request.query_params.get('days_ahead', 30))
        fmt = request.query_params.get('format', 'json')
        from .services.management_service import ManagementReportService
        result = ManagementReportService.generate_cashflow_projection(
            base_date, days_ahead=days_ahead, user=request.user)
        if fmt == 'excel':
            return FileResponse(open(result['excel_path'], 'rb'),
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                as_attachment=True, filename='FlujoCaja.xlsx')
        if fmt == 'pdf':
            return FileResponse(open(result['pdf_path'], 'rb'),
                                content_type='application/pdf',
                                as_attachment=True, filename='FlujoCaja.pdf')
        return Response(result)


# ── Vistas dedicadas ASFI (rutas explícitas, sin ambigüedad de router) ─────────

class RTEReportView(APIView):
    """
    GET /api/reports/asfi/rte/download-excel/?year=YYYY&month=MM
    GET /api/reports/asfi/rte/download-pdf/?year=YYYY&month=MM
    """
    permission_classes = [IsAdminOrSupervisor]

    @rate_limit(requests=10, window=60, scope='user')
    def get(self, request, fmt):
        year  = int(request.query_params.get('year',  dt.today().year))
        month = int(request.query_params.get('month', dt.today().month))

        from .services.asfi_service import ASFIReportService

        if fmt == 'csv':
            try:
                path = ASFIReportService.generate_rte_csv(year, month, user=request.user)
            except ValueError as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            try:
                with open(path, 'rb') as f:
                    data = f.read()
            except FileNotFoundError:
                return Response({'error': 'Archivo no encontrado'},
                                status=status.HTTP_404_NOT_FOUND)
            response = HttpResponse(data, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = (
                f'attachment; filename="RTE_{year}{month:02d}.csv"')
            return response

        try:
            result = ASFIReportService.generate_rte_monthly(year, month, user=request.user)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if fmt == 'excel':
            file_path    = result['excel_path']
            content_type = ('application/vnd.openxmlformats-officedocument'
                            '.spreadsheetml.sheet')
            filename     = f'RTE_{year}{month:02d}.xlsx'
        else:
            file_path    = result['pdf_path']
            content_type = 'application/pdf'
            filename     = f'RTE_{year}{month:02d}.pdf'

        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            return Response({'error': 'Archivo no encontrado'},
                            status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(data, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class PEPReportView(APIView):
    """
    GET /api/reports/asfi/pep/download-excel/?year=YYYY&month=MM
    GET /api/reports/asfi/pep/download-pdf/?year=YYYY&month=MM
    """
    permission_classes = [IsAdminOrSupervisor]

    @rate_limit(requests=10, window=60, scope='user')
    def get(self, request, fmt):
        year  = int(request.query_params.get('year',  dt.today().year))
        month = int(request.query_params.get('month', dt.today().month))

        from .services.asfi_service import ASFIReportService
        result = ASFIReportService.generate_pep_report(year=year, month=month,
                                                        user=request.user)

        if fmt == 'excel':
            file_path    = result['excel_path']
            content_type = ('application/vnd.openxmlformats-officedocument'
                            '.spreadsheetml.sheet')
            filename     = f'PEP_{year}{month:02d}.xlsx'
        else:
            file_path    = result['pdf_path']
            content_type = 'application/pdf'
            filename     = f'PEP_{year}{month:02d}.pdf'

        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            return Response({'error': 'Archivo no encontrado'},
                            status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(data, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response