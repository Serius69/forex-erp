# users/tests/test_security_fixes.py
"""
Regresión de 3 fixes de seguridad (auditoría multi-agente 2026-07-20):

  1. dashboard_stats — fuga cross-tenant de capital: un ADMIN (branch=None)
     veía el CapitalSnapshot más reciente de CUALQUIER empresa.
  2. set-pin — permitía cambiar el PIN sin conocer el actual si se omitía current_pin.
  3. Branch.code — era único GLOBAL en vez de por empresa (rompía alta multi-tenant).
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


def _company(name):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _branch(company, code, name='Sucursal'):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code, name=name, is_active=True)


def _user(company, branch, role, username):
    u = User.objects.create_user(username=username, password='testpass123',
                                 email=f'{username}@test.com')
    u.company = company
    u.branch = branch
    u.role = role
    u.save()
    return u


class DashboardStatsTenantIsolationTests(TestCase):
    """El ADMIN de una empresa nunca debe ver el capital de otra."""

    @classmethod
    def setUpTestData(cls):
        cls.comp_a = _company('Empresa A')
        cls.comp_b = _company('Empresa B')
        cls.br_a = _branch(cls.comp_a, 'A1', 'Central A')
        cls.br_b = _branch(cls.comp_b, 'B1', 'Central B')
        cls.admin_a = _user(cls.comp_a, None, 'ADMIN', 'admin_a')  # branch=None (ADMIN típico)

    def setUp(self):
        self.client = APIClient()

    def test_admin_no_ve_capital_de_otra_empresa(self):
        from capital.models import CapitalSnapshot
        today = date.today()
        # Snapshot propio (Empresa A) = 1.000
        CapitalSnapshot.objects.create(
            branch=self.br_a, fecha=today, total_bob=Decimal('1000'),
            generado_por=self.admin_a)
        # Snapshot AJENO (Empresa B) más grande y creado DESPUÉS → más reciente:
        # sin aislamiento por empresa, el ADMIN de A lo tomaría como "capital actual".
        CapitalSnapshot.objects.create(
            branch=self.br_b, fecha=today, total_bob=Decimal('999999'),
            generado_por=self.admin_a)

        self.client.force_authenticate(user=self.admin_a)
        res = self.client.get('/api/dashboard/stats/')
        self.assertEqual(res.status_code, 200)
        # Debe ver SOLO el de su empresa (1.000), jamás el ajeno (999.999).
        self.assertEqual(float(res.data['current_capital']), 1000.0)


class SetPinTests(TestCase):
    """set-pin exige el PIN actual cuando ya existe uno."""

    @classmethod
    def setUpTestData(cls):
        cls.comp = _company('Empresa PIN')
        cls.br = _branch(cls.comp, 'P1', 'Central P')

    def setUp(self):
        self.client = APIClient()

    def test_alta_inicial_sin_pin_previo(self):
        u = _user(self.comp, self.br, 'CASHIER', 'pin_new')
        self.client.force_authenticate(user=u)
        res = self.client.post('/api/users/set-pin/', {'pin': '1234'}, format='json')
        self.assertEqual(res.status_code, 200)
        u.refresh_from_db()
        self.assertTrue(u.check_pin('1234'))

    def test_cambio_sin_current_pin_rechazado(self):
        u = _user(self.comp, self.br, 'CASHIER', 'pin_exist')
        u.set_pin('1111')
        self.client.force_authenticate(user=u)
        # Omitir current_pin ya NO debe permitir el cambio.
        res = self.client.post('/api/users/set-pin/', {'pin': '2222'}, format='json')
        self.assertEqual(res.status_code, 400)
        u.refresh_from_db()
        self.assertTrue(u.check_pin('1111'))   # PIN intacto

    def test_cambio_con_current_pin_incorrecto_rechazado(self):
        u = _user(self.comp, self.br, 'CASHIER', 'pin_wrong')
        u.set_pin('1111')
        self.client.force_authenticate(user=u)
        res = self.client.post('/api/users/set-pin/',
                               {'pin': '2222', 'current_pin': '0000'}, format='json')
        self.assertEqual(res.status_code, 400)
        u.refresh_from_db()
        self.assertTrue(u.check_pin('1111'))

    def test_cambio_con_current_pin_correcto_ok(self):
        u = _user(self.comp, self.br, 'CASHIER', 'pin_ok')
        u.set_pin('1111')
        self.client.force_authenticate(user=u)
        res = self.client.post('/api/users/set-pin/',
                               {'pin': '2222', 'current_pin': '1111'}, format='json')
        self.assertEqual(res.status_code, 200)
        u.refresh_from_db()
        self.assertTrue(u.check_pin('2222'))


class BranchCodeUniquePerCompanyTests(TestCase):
    """El código de sucursal es único por empresa, no globalmente."""

    @classmethod
    def setUpTestData(cls):
        cls.comp_a = _company('Empresa A')
        cls.comp_b = _company('Empresa B')
        cls.admin_a = _user(cls.comp_a, None, 'ADMIN', 'badmin_a')
        cls.admin_b = _user(cls.comp_b, None, 'ADMIN', 'badmin_b')

    def setUp(self):
        self.client = APIClient()

    def _crear(self, admin, code):
        self.client.force_authenticate(user=admin)
        return self.client.post('/api/users/branches/', {
            'name': f'Sucursal {code}', 'code': code,
            'address': 'Calle Falsa 123', 'phone': '77712345',
        }, format='json')

    def test_dos_empresas_pueden_usar_el_mismo_code(self):
        r1 = self._crear(self.admin_a, 'MAT')
        self.assertIn(r1.status_code, (200, 201))
        r2 = self._crear(self.admin_b, 'MAT')   # otra empresa, mismo code → permitido
        self.assertIn(r2.status_code, (200, 201))

    def test_misma_empresa_no_repite_code(self):
        self._crear(self.admin_a, 'DUP')
        r = self._crear(self.admin_a, 'DUP')    # misma empresa, code repetido → 400
        self.assertEqual(r.status_code, 400)

    def test_constraint_a_nivel_db(self):
        from users.models import Branch
        Branch.objects.create(company=self.comp_a, code='ZZ', name='x')
        Branch.objects.create(company=self.comp_b, code='ZZ', name='y')  # ok: otra empresa
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Branch.objects.create(company=self.comp_a, code='ZZ', name='dup')
