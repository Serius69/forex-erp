from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import HttpResponse, FileResponse
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Report, ReportSchedule
from .serializers import ReportSerializer, ReportScheduleSerializer
from .generators import ReportGenerator
from .tasks import generate_scheduled_report

class ReportViewSet(viewsets.ModelViewSet):
    queryset = Report.objects.all()
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros
        report_type = self.request.query_params.get('type')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if report_type:
            queryset = queryset.filter(report_type=report_type)
        if start_date:
            queryset = queryset.filter(start_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(end_date__lte=end_date)
        
        return queryset.select_related('generated_by')
    
    @action(detail=False, methods=['POST'])
    def generate(self, request):
        """Genera un nuevo reporte"""
        report_type = request.data.get('report_type')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        branch_id = request.data.get('branch_id')
        
        if not all([report_type, start_date, end_date]):
            return Response(
                {'error': 'Faltan parámetros requeridos'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Convertir fechas
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            # Obtener sucursal si se especifica
            branch = None
            if branch_id:
                from users.models import Branch
                branch = Branch.objects.get(id=branch_id)
            
            # Generar reporte
            generator = ReportGenerator(
                start_date=start_date,
                end_date=end_date,
                branch=branch,
                user=request.user
            )
            
            if report_type == 'DAILY':
                report = generator.generate_daily_report()
            elif report_type == 'REGULATORY':
                report = generator.generate_regulatory_report()
            else:
                return Response(
                    {'error': 'Tipo de reporte no soportado'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            return Response(
                ReportSerializer(report).data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['GET'])
    def download_pdf(self, request, pk=None):
        """Descarga el PDF del reporte"""
        report = self.get_object()
        
        if not report.pdf_file:
            return Response(
                {'error': 'Este reporte no tiene PDF'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        response = FileResponse(
            report.pdf_file,
            as_attachment=True,
            filename=f"{report.report_type}_{report.start_date}_{report.end_date}.pdf"
        )
        return response
    
    @action(detail=True, methods=['GET'])
    def download_excel(self, request, pk=None):
        """Descarga el Excel del reporte"""
        report = self.get_object()
        
        if not report.excel_file:
            return Response(
                {'error': 'Este reporte no tiene Excel'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        response = FileResponse(
            report.excel_file,
            as_attachment=True,
            filename=f"{report.report_type}_{report.start_date}_{report.end_date}.xlsx"
        )
        return response
    
    @action(detail=False, methods=['GET'])
    def available_types(self, request):
        """Obtiene tipos de reportes disponibles"""
        types = []
        
        for code, name in Report.REPORT_TYPES:
            types.append({
                'code': code,
                'name': name,
                'description': self._get_report_description(code),
                'parameters': self._get_report_parameters(code)
            })
        
        return Response(types)
    
    def _get_report_description(self, report_type):
        """Obtiene descripción del tipo de reporte"""
        descriptions = {
            'DAILY': 'Reporte diario de operaciones, incluye transacciones, inventario y análisis de rentabilidad',
            'WEEKLY': 'Resumen semanal con tendencias y comparativas',
            'MONTHLY': 'Reporte mensual completo con análisis detallado',
            'CUSTOM': 'Reporte personalizado según parámetros específicos',
            'REGULATORY': 'Reporte para cumplimiento regulatorio (UIF)',
            'TAX': 'Reporte fiscal para declaraciones impositivas'
        }
        return descriptions.get(report_type, '')
    
    def _get_report_parameters(self, report_type):
        """Obtiene parámetros requeridos para cada tipo de reporte"""
        base_params = [
            {'name': 'start_date', 'type': 'date', 'required': True},
            {'name': 'end_date', 'type': 'date', 'required': True},
            {'name': 'branch_id', 'type': 'integer', 'required': False}
        ]
        
        if report_type == 'REGULATORY':
            base_params.append({
                'name': 'include_pep',
                'type': 'boolean',
                'required': False,
                'default': True
            })
        
        return base_params

class ReportScheduleViewSet(viewsets.ModelViewSet):
    queryset = ReportSchedule.objects.all()
    serializer_class = ReportScheduleSerializer
    permission_classes = [IsAuthenticated]
    
    def create(self, request):
        """Crea una nueva programación de reporte"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Establecer usuario creador
        schedule = serializer.save(created_by=request.user)
        
        # Calcular próxima ejecución
        from .tasks import calculate_next_run
        schedule.next_run = calculate_next_run(schedule)
        schedule.save()
        
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['POST'])
    def run_now(self, request, pk=None):
        """Ejecuta un reporte programado inmediatamente"""
        schedule = self.get_object()
        
        try:
            generate_scheduled_report(schedule)
            
            return Response({'success': True})
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['POST'])
    def toggle_active(self, request, pk=None):
        """Activa/desactiva una programación"""
        schedule = self.get_object()
        schedule.is_active = not schedule.is_active
        schedule.save()
        
        return Response({
            'is_active': schedule.is_active
        })