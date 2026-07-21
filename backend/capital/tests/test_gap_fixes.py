# capital/tests/test_gap_fixes.py
"""
Tests de los gaps reales detectados en la auditoría de paridad legado↔ERP
(2026-07-21). El .gs legado se usó SOLO como referencia (tiene bugs); estos
fixes son mejoras defendibles dentro del modelo del propio ERP.

  - resumen_financiero: los IngresoExtra ahora SUMAN al P&L, simétrico a los
    gastos. Antes el gasto bajaba la utilidad neta pero el ingreso extra no la
    subía (quedaba registrado pero invisible al resultado).
"""
import uuid
from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from capital.services import GananciaService

User = get_user_model()


def _make_company(name):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_branch(company, code='G001'):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code,
                                 name=f'Sucursal {code}', is_active=True)


def _make_user(company, branch, username):
    user = User.objects.create_user(
        username=username, password='testpass123',
        email=f'{username}@test.com',
    )
    user.company = company
    user.branch = branch
    user.role = 'ADMIN'
    user.save()
    return user


class IngresoExtraEnPnLTests(TestCase):
    def setUp(self):
        self.company = _make_company(f'CasaGap-{uuid.uuid4().hex[:8]}')
        self.branch  = _make_branch(self.company)
        self.admin   = _make_user(self.company, self.branch,
                                  f'gap_{uuid.uuid4().hex[:8]}')

    def _gasto(self, monto, fecha):
        from capital.models import Gasto
        return Gasto.objects.create(
            fecha=fecha, categoria='OTROS', monto_bob=Decimal(monto),
            medio_pago='EFECTIVO', branch=self.branch, registrado_por=self.admin,
        )

    def _ingreso(self, monto, fecha, tipo='Comisión'):
        from capital.models import IngresoExtra
        return IngresoExtra.objects.create(
            fecha=fecha, tipo=tipo, monto_bob=Decimal(monto),
            medio_pago='EFECTIVO', branch=self.branch, registrado_por=self.admin,
        )

    def test_ingreso_extra_sube_la_ganancia_neta(self):
        """Sin divisas ni tarjetas: bruta=0. Un gasto de 100 y un ingreso extra
        de 300 → neta = 0 - 100 + 300 = 200 (antes daba -100)."""
        d = date(2026, 6, 15)
        self._gasto('100.00', d)
        self._ingreso('300.00', d)

        res = GananciaService.resumen_financiero(d, d, branch=self.branch)

        self.assertEqual(res['ingresos_extra']['total'], '300.00')
        self.assertEqual(res['ingresos_extra']['count'], 1)
        self.assertEqual(res['gastos']['total'], '100.00')
        self.assertEqual(res['ganancia_neta'], '200.00')

    def test_ingreso_extra_respeta_la_ventana_de_fechas(self):
        d_in  = date(2026, 6, 10)
        d_out = date(2026, 5, 1)
        self._ingreso('500.00', d_in)
        self._ingreso('999.00', d_out)   # fuera de ventana → no cuenta

        res = GananciaService.resumen_financiero(d_in, d_in, branch=self.branch)

        self.assertEqual(res['ingresos_extra']['total'], '500.00')
        self.assertEqual(res['ganancia_neta'], '500.00')

    def test_ingreso_extra_agrupa_por_tipo(self):
        d = date(2026, 6, 20)
        self._ingreso('120.00', d, tipo='Caiditas')
        self._ingreso('80.00', d, tipo='Caiditas')
        self._ingreso('50.00', d, tipo='Interés')

        res = GananciaService.resumen_financiero(d, d, branch=self.branch)

        self.assertEqual(res['ingresos_extra']['total'], '250.00')
        por_tipo = {i['tipo']: i['total'] for i in res['ingresos_extra']['por_tipo']}
        self.assertEqual(por_tipo['Caiditas'], '200.00')
        self.assertEqual(por_tipo['Interés'], '50.00')
