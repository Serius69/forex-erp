# capital/tests/test_fixes.py
"""
Tests de los fixes de sesión 2026-07-07 (parte 2):

  - deducir_bob con backtracking: encuentra cambio exacto donde el greedy
    puro fallaba (documentado antes en test_services.py como limitación).
  - _serialize_resultado recursivo: el early-return sin divisa BOB ya no
    deja Decimals anidados sin serializar.
  - resumen_financiero excluye ventas de tarjetas ANULADAS del P&L.
"""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from capital.services import CapitalService, CashBOBService, GananciaService

User = get_user_model()


def _make_company(name):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_branch(company, code='F001'):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code,
                                 name=f'Sucursal {code}', is_active=True)


def _make_user(company, branch, role='ADMIN', username='admin_fixes'):
    user = User.objects.create_user(
        username=username, password='testpass123',
        email=f'{username}@test.com',
    )
    user.company = company
    user.branch = branch
    user.role = role
    user.save()
    return user


class DeducirBobBacktrackingTests(TestCase):

    def setUp(self):
        self.company = _make_company('CasaFixes')
        self.branch  = _make_branch(self.company)
        self.admin   = _make_user(self.company, self.branch)

    def _make_cash(self, **kwargs):
        from capital.models import CashBOB
        return CashBOB.objects.create(
            branch=self.branch, registrado_por=self.admin, **kwargs,
        )

    def test_backtracking_resuelve_caso_donde_greedy_fallaba(self):
        """50 Bs con 10×4 + 20×2: el greedy tomaba 10×4 y quedaba sin cambio
        para los 10 restantes; el backtracking encuentra 10×3 + 20×1."""
        self._make_cash(caja_chica_10=4, caja_chica_20=2)  # 40 + 40 = 80

        resultado = CashBOBService.deducir_bob(self.branch, Decimal('50'))

        total = sum(op['monto_bob'] for op in resultado['operations'])
        self.assertEqual(total, 50)
        self.assertEqual(resultado['saldo_nuevo'], '30')

        from capital.models import CashBOB
        cash = CashBOB.objects.get(branch=self.branch)
        self.assertEqual(cash.total_efectivo_fisico(), Decimal('30'))

    def test_backtracking_cruza_grupos(self):
        """60 Bs con caja_chica 50×1 + fuertes 10... no existe: usa
        caja_chica_50 + sueltos_10 (greedy antiguo también podía, pero
        verificamos que el orden de prioridad se mantiene)."""
        self._make_cash(caja_chica_50=1, sueltos_10=3)  # 50 + 30

        resultado = CashBOBService.deducir_bob(self.branch, Decimal('60'))
        grupos = [op['grupo'] for op in resultado['operations']]
        self.assertEqual(grupos, ['caja_chica', 'sueltos'])
        self.assertEqual(resultado['saldo_nuevo'], '20')

    def test_sin_solucion_sigue_lanzando_error(self):
        from capital.services import InsufficientCashError
        self._make_cash(fuertes_200=2)  # 400 disponibles
        with self.assertRaises(InsufficientCashError):
            CashBOBService.deducir_bob(self.branch, Decimal('300'))


class SerializeResultadoTests(TestCase):

    def test_early_return_sin_bob_es_json_serializable(self):
        """Sin divisa BOB en DB, calcular_capital retorna por el early-return;
        antes dejaba Decimals anidados que rompían la respuesta JSON."""
        resultado = CapitalService.calcular_capital()
        self.assertIn('Divisa BOB no encontrada en DB', resultado['advertencias'])
        # json.dumps lanza TypeError si queda algún Decimal anidado
        json.dumps(resultado)
        self.assertEqual(resultado['efectivo']['fuertes'], '0.00')
        self.assertEqual(resultado['totales']['divisas_bob'], '0.00')


class ResumenExcluyeAnuladasTests(TestCase):

    def setUp(self):
        self.company = _make_company('CasaAnuladas')
        self.branch  = _make_branch(self.company, 'F002')
        self.admin   = _make_user(self.company, self.branch, 'ADMIN', 'admin_anul')

    def test_venta_anulada_no_cuenta_en_pnl(self):
        from tarjetas.models import TipoTarjeta
        from tarjetas.services import TarjetaService

        tipo = TipoTarjeta.objects.create(
            nombre='Tigo 10', operadora='TIGO',
            denominacion=Decimal('10.00'), is_active=True,
        )
        TarjetaService.registrar_lote(
            tipo_tarjeta=tipo, cantidad=10, precio_costo=Decimal('8.00'),
            registrado_por=self.admin, branch=self.branch,
        )
        venta_ok = TarjetaService.registrar_venta(
            tipo_tarjeta=tipo, cantidad=2, precio_venta=Decimal('10.00'),
            cajero=self.admin, branch=self.branch,
        )
        venta_anulada = TarjetaService.registrar_venta(
            tipo_tarjeta=tipo, cantidad=3, precio_venta=Decimal('10.00'),
            cajero=self.admin, branch=self.branch,
        )
        TarjetaService.anular_venta(venta_anulada, 'Error de registro', self.admin)

        hoy = timezone.localdate()
        resumen = GananciaService.resumen_financiero(hoy, hoy, branch=self.branch)

        # Solo la venta vigente: 2 × (10 − 8) = 4.00 de ganancia
        self.assertEqual(resumen['ganancias_tarjetas']['ventas'], 1)
        self.assertEqual(resumen['ganancias_tarjetas']['total'],
                         str(venta_ok.ganancia_bob))
        self.assertEqual(Decimal(resumen['ganancias_tarjetas']['total']),
                         Decimal('4.00'))
