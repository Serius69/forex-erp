# tarjetas/tests/test_numero_venta.py
"""
Tests del reintento de numero_venta ante colisión.

El select_for_update sobre un aggregate NO bloqueaba filas: dos ventas
concurrentes podían calcular el mismo Max y chocar contra el unique=True.
Ahora la colisión se absorbe con savepoint + reintento de secuencia.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tarjetas.models import TipoTarjeta, VentaTarjeta
from tarjetas.services import TarjetaService

User = get_user_model()


class NumeroVentaRetryTests(TestCase):

    def setUp(self):
        from tenants.models import Company
        from users.models import Branch
        self.company = Company.objects.create(name='CasaNumVenta', is_active=True)
        self.branch = Branch.objects.create(
            company=self.company, code='NV01', name='Sucursal NV', is_active=True)
        self.cajero = User.objects.create_user(
            username='cajero_nv', password='testpass123', email='nv@test.com')
        self.cajero.company = self.company
        self.cajero.branch = self.branch
        self.cajero.save()

        self.tipo = TipoTarjeta.objects.create(
            nombre='Entel 10', operadora='ENTEL',
            denominacion=Decimal('10.00'), is_active=True,
        )
        TarjetaService.registrar_lote(
            tipo_tarjeta=self.tipo, cantidad=50, precio_costo=Decimal('8.00'),
            registrado_por=self.cajero, branch=self.branch,
        )

    def _vender(self, cantidad=1):
        return TarjetaService.registrar_venta(
            tipo_tarjeta=self.tipo, cantidad=cantidad,
            precio_venta=Decimal('10.00'),
            cajero=self.cajero, branch=self.branch,
        )

    def test_secuencia_normal(self):
        prefix = f"TV{timezone.localdate().strftime('%Y%m%d')}"
        v1 = self._vender()
        v2 = self._vender()
        self.assertEqual(v1.numero_venta, f'{prefix}0001')
        self.assertEqual(v2.numero_venta, f'{prefix}0002')

    def test_colision_reintenta_con_siguiente_secuencia(self):
        """Simula el race: el Max calculado está desactualizado (otra venta
        ya tomó ese número) → IntegrityError → reintento con la siguiente."""
        v1 = self._vender()  # ocupa ...0001

        real_filter = VentaTarjeta.objects.filter

        def filter_con_max_viejo(*args, **kwargs):
            if 'numero_venta__startswith' in kwargs:
                class _StaleQS:
                    def aggregate(self, **agg):
                        return {'m': None}   # como si no existiera ...0001
                return _StaleQS()
            return real_filter(*args, **kwargs)

        with mock.patch.object(VentaTarjeta.objects, 'filter',
                               side_effect=filter_con_max_viejo):
            v2 = self._vender()

        prefix = f"TV{timezone.localdate().strftime('%Y%m%d')}"
        self.assertEqual(v1.numero_venta, f'{prefix}0001')
        # Intentó 0001 (colisión), reintentó y quedó 0002
        self.assertEqual(v2.numero_venta, f'{prefix}0002')
        self.assertEqual(v2.estado, 'COMPLETADA')
        self.assertEqual(v2.cantidad, 1)
        # La venta colisionada no dejó basura: solo 2 ventas en total
        self.assertEqual(VentaTarjeta.objects.count(), 2)
