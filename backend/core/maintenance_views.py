"""
Endpoints de mantenimiento del sistema Kapitalya.
Solo accesibles por ADMIN.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache

from .maintenance import (
    is_maintenance_active, get_maintenance_info,
    activate_maintenance, deactivate_maintenance,
    clear_all_caches, recalculate_system,
)


def _require_admin(user):
    return getattr(user, 'role', None) == 'ADMIN'


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def maintenance_status(request):
    """GET /api/maintenance/ — estado actual del sistema."""
    from django.utils import timezone
    info = get_maintenance_info()
    return Response({
        'maintenance_active': bool(info),
        'info':               info,
        'server_time':        timezone.now().isoformat(),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def maintenance_toggle(request):
    """
    POST /api/maintenance/toggle/
    Body: {"action": "activate"|"deactivate", "reason": "..."}
    """
    if not _require_admin(request.user):
        return Response({'error': 'Solo administradores'}, status=403)

    action = request.data.get('action')
    reason = request.data.get('reason', '').strip()

    if action == 'activate':
        if not reason:
            return Response({'error': 'Debe indicar el motivo del mantenimiento'}, status=400)
        info = activate_maintenance(request.user.username, reason)
        return Response({'success': True, 'maintenance': info})

    elif action == 'deactivate':
        deactivate_maintenance()
        return Response({'success': True, 'maintenance_active': False})

    return Response({'error': 'action debe ser activate o deactivate'}, status=400)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def maintenance_clear_cache(request):
    """POST /api/maintenance/clear-cache/ — vaciar todas las cachés."""
    if not _require_admin(request.user):
        return Response({'error': 'Solo administradores'}, status=403)

    results = clear_all_caches()
    return Response({'success': True, 'results': results})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def maintenance_recalculate(request):
    """
    POST /api/maintenance/recalculate/
    Recalcula WAC de inventario y verifica consistencia.
    Operación pesada — ejecutar solo en horarios de baja carga.
    """
    if not _require_admin(request.user):
        return Response({'error': 'Solo administradores'}, status=403)

    branch = request.user.branch if request.user.role != 'ADMIN' else None
    results = recalculate_system(branch=branch)
    return Response(results, status=200 if results['success'] else 207)
