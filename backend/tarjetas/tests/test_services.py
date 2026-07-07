# tarjetas/tests/test_services.py
"""
Tests unitarios de TarjetaService (tarjetas/services.py).

Cubre:
  - registrar_lote: creación del lote + movimiento COMPRA en el libro diario
  - registrar_venta: costeo FIFO cruzando lotes, ganancia_bob, trazabilidad
    (DetalleVentaLote), numeración TVYYYYMMDDNNNN, comisión, stock insuficiente
  - anular_venta: restauración de stock a los lotes originales, validaciones
  - get_posicion_inventario: posición valorizada + estados de alerta de stock
  - inventario_completo: snapshot de inventario por tipo
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model

from tarjetas.models import (
    TipoTarjeta, LoteCompra, VentaTarjeta, DetalleVentaLote,
    MovimientoTarjeta, AlertaInventarioTarjeta,
)
from tarjetas.services import TarjetaService

User = get_user_model()

# ── Helpers para crear fixtures mínimas ───────────────────────────────────────

def _make_company(name='TestCo'):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_branch(company, code='SUC01', name='Sucursal Test'):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code, name=name, is_active=True)


def _make_user(company, branch, role='CASHIER', username=None):
    username = username or f'user_{role.lower()}_{branch.code}'
    user = User.objects.create_user(
        username=username, password='testpass123',
        email=f'{username}@test.com',
    )
    user.company  = company
    user.branch   = branch
    user.role     = role
    user.is_active = True
    user.save()
    return user


def _make_tipo(operadora='TIGO', nombre='Tigo 10 BOB', denominacion='10.00'):
    return TipoTarjeta.objects.create(
        operadora=operadora,
        nombre=nombre,
        denominacion=Decimal(denominacion),
    )


# ── Base ──────────────────────────────────────────────────────────────────────

class TarjetaServiceTestBase(TestCase):
    """Fixtures comunes: empresa, sucursal, admin/cajero y un tipo de tarjeta."""

    def setUp(self):
        self.company = _make_company('KapitalyaTest')
        self.branch  = _make_branch(self.company, 'LP01', 'Sucursal La Paz')
        self.admin   = _make_user(self.company, self.branch, 'ADMIN',   'admin_tarjetas')
        self.cajero  = _make_user(self.company, self.branch, 'CASHIER', 'cajero_tarjetas')
        self.tipo    = _make_tipo()

    def _lote(self, cantidad, costo, fecha=None):
        """Atajo: registra un lote vía el servicio."""
        return TarjetaService.registrar_lote(
            tipo_tarjeta=self.tipo,
            cantidad=cantidad,
            precio_costo=Decimal(str(costo)),
            registrado_por=self.admin,
            fecha_compra=fecha,
            branch=self.branch,
        )

    def _venta(self, cantidad, precio, **kwargs):
        """Atajo: registra una venta vía el servicio."""
        return TarjetaService.registrar_venta(
            tipo_tarjeta=self.tipo,
            cantidad=cantidad,
            precio_venta=Decimal(str(precio)),
            cajero=self.cajero,
            branch=self.branch,
            **kwargs,
        )


# ── registrar_lote ────────────────────────────────────────────────────────────

class RegistrarLoteTests(TarjetaServiceTestBase):

    def test_registrar_lote_crea_lote_y_stock(self):
        """El lote se crea con cantidad_restante completa y suma al stock."""
        lote = self._lote(50, '8.50')
        self.assertEqual(lote.cantidad_total, 50)
        self.assertEqual(lote.cantidad_restante, 50)
        self.assertEqual(lote.precio_costo, Decimal('8.50'))
        self.assertTrue(lote.is_active)
        self.assertEqual(self.tipo.stock_actual, 50)

    def test_registrar_lote_crea_movimiento_compra(self):
        """Cada compra escribe un movimiento COMPRA en el libro diario."""
        lote = self._lote(20, '8.00')
        mov = MovimientoTarjeta.objects.get(lote_compra=lote)
        self.assertEqual(mov.tipo_movimiento, 'COMPRA')
        self.assertEqual(mov.cantidad, 20)
        self.assertEqual(mov.precio_unitario, Decimal('8.00'))
        self.assertEqual(mov.total_bob, Decimal('160.00'))
        self.assertIsNone(mov.ganancia_bob)
        self.assertEqual(mov.usuario, self.admin)
        self.assertEqual(mov.branch, self.branch)


# ── registrar_venta (FIFO) ────────────────────────────────────────────────────

class RegistrarVentaFIFOTests(TarjetaServiceTestBase):

    def test_venta_un_solo_lote_calcula_costo_y_ganancia(self):
        """Venta dentro de un lote: costo = costo_unit × uds, ganancia = total − costo."""
        self._lote(10, '8.00')
        venta = self._venta(4, '10.00')

        self.assertEqual(venta.total_bob, Decimal('40.00'))
        self.assertEqual(venta.costo_fifo_bob, Decimal('32.0000'))
        self.assertEqual(venta.ganancia_bob, Decimal('8.00'))
        self.assertEqual(venta.estado, 'COMPLETADA')
        self.assertEqual(self.tipo.stock_actual, 6)

    def test_venta_cruza_lotes_costeo_fifo(self):
        """FIFO puro: consume primero el lote más antiguo aunque sea más barato/caro.

        Lote A (antiguo): 10 uds @ 8.00 · Lote B (nuevo): 10 uds @ 9.00.
        Venta de 15 uds @ 10.00:
          costo  = 10×8.00 + 5×9.00 = 125.00
          total  = 15×10.00        = 150.00
          ganancia = 150 − 125     = 25.00
        """
        lote_a = self._lote(10, '8.00', fecha=date(2026, 7, 1))
        lote_b = self._lote(10, '9.00', fecha=date(2026, 7, 5))

        venta = self._venta(15, '10.00')

        self.assertEqual(venta.costo_fifo_bob, Decimal('125.0000'))
        self.assertEqual(venta.ganancia_bob, Decimal('25.00'))

        # Lote antiguo agotado y desactivado; lote nuevo con remanente
        lote_a.refresh_from_db()
        lote_b.refresh_from_db()
        self.assertEqual(lote_a.cantidad_restante, 0)
        self.assertFalse(lote_a.is_active)
        self.assertEqual(lote_b.cantidad_restante, 5)
        self.assertTrue(lote_b.is_active)
        self.assertEqual(self.tipo.stock_actual, 5)

    def test_venta_registra_detalles_por_lote(self):
        """La trazabilidad FIFO queda en DetalleVentaLote con el costo de cada lote."""
        lote_a = self._lote(10, '8.00', fecha=date(2026, 7, 1))
        lote_b = self._lote(10, '9.00', fecha=date(2026, 7, 5))

        venta = self._venta(12, '10.00')
        detalles = list(venta.detalles_lote.order_by('lote__fecha_compra'))

        self.assertEqual(len(detalles), 2)
        self.assertEqual(detalles[0].lote, lote_a)
        self.assertEqual(detalles[0].cantidad_consumida, 10)
        self.assertEqual(detalles[0].costo_unitario, Decimal('8.00'))
        self.assertEqual(detalles[1].lote, lote_b)
        self.assertEqual(detalles[1].cantidad_consumida, 2)
        self.assertEqual(detalles[1].costo_unitario, Decimal('9.00'))

    def test_venta_crea_movimiento_venta_con_ganancia(self):
        """La venta escribe un movimiento VENTA en el libro diario con ganancia FIFO."""
        self._lote(10, '8.00')
        venta = self._venta(3, '10.00')

        mov = MovimientoTarjeta.objects.get(venta_tarjeta=venta)
        self.assertEqual(mov.tipo_movimiento, 'VENTA')
        self.assertEqual(mov.cantidad, 3)
        self.assertEqual(mov.total_bob, Decimal('30.00'))
        self.assertEqual(mov.ganancia_bob, Decimal('6.00'))
        self.assertEqual(mov.usuario, self.cajero)

    def test_numero_venta_secuencial_por_dia(self):
        """El número de venta usa prefijo TVYYYYMMDD y secuencia incremental."""
        from django.utils import timezone
        self._lote(10, '8.00')
        v1 = self._venta(1, '10.00')
        v2 = self._venta(1, '10.00')

        prefix = f"TV{timezone.localdate().strftime('%Y%m%d')}"
        self.assertTrue(v1.numero_venta.startswith(prefix))
        self.assertEqual(int(v2.numero_venta[-4:]), int(v1.numero_venta[-4:]) + 1)

    def test_venta_con_comision_no_altera_ganancia_fifo(self):
        """La comisión suma al total facturado pero la ganancia se calcula sobre total_bob."""
        self._lote(10, '8.00')
        venta = self._venta(2, '10.00', comision_bob=Decimal('1.50'))

        self.assertEqual(venta.total_bob, Decimal('20.00'))
        self.assertEqual(venta.comision_bob, Decimal('1.50'))
        self.assertEqual(venta.total_con_comision, Decimal('21.50'))
        self.assertEqual(venta.ganancia_bob, Decimal('4.00'))  # 20 − 2×8

    def test_venta_stock_insuficiente_lanza_error_y_no_deja_rastro(self):
        """Sin stock suficiente: ValueError y ningún registro creado ni lote tocado."""
        lote = self._lote(5, '8.00')

        with self.assertRaises(ValueError):
            self._venta(6, '10.00')

        lote.refresh_from_db()
        self.assertEqual(lote.cantidad_restante, 5)
        self.assertEqual(VentaTarjeta.objects.count(), 0)
        self.assertEqual(DetalleVentaLote.objects.count(), 0)
        self.assertFalse(
            MovimientoTarjeta.objects.filter(tipo_movimiento='VENTA').exists()
        )


# ── anular_venta ──────────────────────────────────────────────────────────────

class AnularVentaTests(TarjetaServiceTestBase):

    def test_anular_venta_restaura_stock_a_los_lotes(self):
        """La anulación devuelve las unidades a los lotes originales y los reactiva."""
        lote_a = self._lote(10, '8.00', fecha=date(2026, 7, 1))
        lote_b = self._lote(10, '9.00', fecha=date(2026, 7, 5))
        venta  = self._venta(15, '10.00')
        self.assertEqual(self.tipo.stock_actual, 5)

        anulada = TarjetaService.anular_venta(venta, 'Error de cajero', self.admin)

        self.assertEqual(anulada.estado, 'ANULADA')
        self.assertEqual(anulada.motivo_anulacion, 'Error de cajero')
        self.assertEqual(anulada.anulado_por, self.admin)
        self.assertIsNotNone(anulada.anulado_at)

        lote_a.refresh_from_db()
        lote_b.refresh_from_db()
        self.assertEqual(lote_a.cantidad_restante, 10)
        self.assertTrue(lote_a.is_active)  # estaba agotado → reactivado
        self.assertEqual(lote_b.cantidad_restante, 10)
        self.assertEqual(self.tipo.stock_actual, 20)

        # Movimiento de reversa (COMPRA) al costo FIFO original
        mov = MovimientoTarjeta.objects.filter(
            tipo_movimiento='COMPRA', lote_compra__isnull=True,
        ).get()
        self.assertEqual(mov.total_bob, venta.costo_fifo_bob)
        self.assertIn(venta.numero_venta, mov.notas)

    def test_anular_venta_sin_motivo_lanza_error(self):
        """El motivo de anulación es obligatorio."""
        self._lote(5, '8.00')
        venta = self._venta(2, '10.00')
        with self.assertRaises(ValueError):
            TarjetaService.anular_venta(venta, '   ', self.admin)
        venta.refresh_from_db()
        self.assertEqual(venta.estado, 'COMPLETADA')

    def test_anular_venta_ya_anulada_lanza_error(self):
        """No se puede anular dos veces la misma venta (evita duplicar stock)."""
        lote  = self._lote(5, '8.00')
        venta = self._venta(2, '10.00')
        TarjetaService.anular_venta(venta, 'Primera anulación', self.admin)

        with self.assertRaises(ValueError):
            TarjetaService.anular_venta(venta, 'Segunda anulación', self.admin)

        lote.refresh_from_db()
        self.assertEqual(lote.cantidad_restante, 5)  # stock restaurado una sola vez


# ── Consultas de inventario ───────────────────────────────────────────────────

class InventarioTests(TarjetaServiceTestBase):

    def test_get_posicion_inventario_valoriza_por_tipo(self):
        """Posición valorizada: stock, costo, valor venta y margen potencial."""
        self._lote(10, '8.00', fecha=date(2026, 7, 1))
        self._lote(10, '9.00', fecha=date(2026, 7, 5))

        pos  = TarjetaService.get_posicion_inventario()
        item = next(i for i in pos['items'] if i['id'] == self.tipo.id)

        self.assertEqual(item['stock'], 20)
        self.assertEqual(item['lotes_activos'], 2)
        self.assertEqual(item['costo_promedio'], '8.50')     # (10×8 + 10×9) / 20
        self.assertEqual(item['valor_costo_bob'], '170.00')
        self.assertEqual(item['valor_venta_bob'], '200.00')  # denominación 10 × 20
        self.assertEqual(item['margen_potencial'], '30.00')
        self.assertEqual(pos['resumen']['total_unidades'], 20)
        self.assertEqual(pos['resumen']['valor_costo_bob'], '170.00')

    def test_get_posicion_inventario_estados_de_alerta(self):
        """estado_stock respeta los umbrales: crítico ≤ 5 < bajo ≤ 20 < ok."""
        AlertaInventarioTarjeta.objects.create(
            tipo_tarjeta=self.tipo, branch=None,
            stock_minimo=20, stock_critico=5,
        )

        def _estado():
            pos = TarjetaService.get_posicion_inventario()
            return next(i for i in pos['items'] if i['id'] == self.tipo.id)['estado_stock']

        self._lote(3, '8.00')
        self.assertEqual(_estado(), 'critico')   # stock 3 ≤ 5

        self._lote(10, '8.00')
        self.assertEqual(_estado(), 'bajo')      # stock 13 ≤ 20

        self._lote(30, '8.00')
        self.assertEqual(_estado(), 'ok')        # stock 43

    def test_inventario_completo_snapshot(self):
        """Snapshot simple: stock, costo promedio ponderado y valor a costo."""
        self._lote(10, '8.00', fecha=date(2026, 7, 1))
        self._lote(10, '9.00', fecha=date(2026, 7, 5))
        self._venta(15, '10.00')  # quedan 5 uds del lote de 9.00

        inv  = TarjetaService.inventario_completo()
        item = next(i for i in inv if i['id'] == self.tipo.id)

        self.assertEqual(item['stock_actual'], 5)
        self.assertEqual(item['costo_promedio'], '9.00')
        self.assertEqual(item['valor_inventario_bob'], '45.00')
        self.assertEqual(item['operadora'], 'TIGO')
