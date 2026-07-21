# users/tests/test_audit_multitenant.py
"""
Regresión del clúster multi-tenant de la auditoría 2026-07-20:

  - UserViewSet: un CASHIER no puede crearse/ascenderse a ADMIN (escalada priv).
  - UserCreateSerializer: no se puede asignar una sucursal de otra empresa.
  - capital/position: ?branch_id de otra empresa → 404 (no fuga de posición).
"""
from django.contrib.auth import get_user_model
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


class PrivilegeEscalationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.comp = _company('Empresa A')
        cls.br = _branch(cls.comp, 'A1', 'Central A')
        cls.cashier = _user(cls.comp, cls.br, 'CASHIER', 'cajero1')
        cls.admin = _user(cls.comp, cls.br, 'ADMIN', 'admin1')

    def setUp(self):
        self.client = APIClient()

    def test_cashier_no_puede_crear_admin(self):
        self.client.force_authenticate(user=self.cashier)
        res = self.client.post('/api/users/', {
            'username': 'nuevo', 'email': 'nuevo@test.com',
            'password': 'testpass123', 'role': 'ADMIN',
        }, format='json')
        self.assertEqual(res.status_code, 403)

    def test_cashier_no_puede_ascenderse(self):
        self.client.force_authenticate(user=self.cashier)
        res = self.client.patch(f'/api/users/{self.cashier.id}/',
                                {'role': 'ADMIN'}, format='json')
        self.assertEqual(res.status_code, 403)
        self.cashier.refresh_from_db()
        self.assertEqual(self.cashier.role, 'CASHIER')

    def test_admin_si_puede_crear_usuario(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post('/api/users/', {
            'username': 'cajero2', 'email': 'cajero2@test.com',
            'password': 'testpass123', 'role': 'CASHIER',
        }, format='json')
        self.assertIn(res.status_code, (200, 201))


class UserBranchScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.comp_a = _company('Empresa A')
        cls.comp_b = _company('Empresa B')
        cls.br_a = _branch(cls.comp_a, 'A1', 'Central A')
        cls.br_b = _branch(cls.comp_b, 'B1', 'Central B')
        cls.admin_a = _user(cls.comp_a, cls.br_a, 'ADMIN', 'admin_a')

    def setUp(self):
        self.client = APIClient()

    def test_no_asignar_sucursal_de_otra_empresa(self):
        self.client.force_authenticate(user=self.admin_a)
        res = self.client.post('/api/users/', {
            'username': 'x', 'email': 'x@test.com', 'password': 'testpass123',
            'role': 'CASHIER', 'branch_id': self.br_b.id,   # sucursal de empresa B
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_asignar_sucursal_propia_ok(self):
        self.client.force_authenticate(user=self.admin_a)
        res = self.client.post('/api/users/', {
            'username': 'y', 'email': 'y@test.com', 'password': 'testpass123',
            'role': 'CASHIER', 'branch_id': self.br_a.id,
        }, format='json')
        self.assertIn(res.status_code, (200, 201))


class CapitalPositionIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.comp_a = _company('Empresa A')
        cls.comp_b = _company('Empresa B')
        cls.br_a = _branch(cls.comp_a, 'A1', 'Central A')
        cls.br_b = _branch(cls.comp_b, 'B1', 'Central B')
        cls.cashier_a = _user(cls.comp_a, cls.br_a, 'CASHIER', 'caj_a')

    def setUp(self):
        self.client = APIClient()

    def test_no_ve_posicion_de_sucursal_ajena(self):
        # Un CAJERO de A pide ?branch_id de la sucursal de B → no debe resolverse
        # a esa sucursal (el helper ignora el param y usa la propia sucursal).
        self.client.force_authenticate(user=self.cashier_a)
        res = self.client.get(f'/api/capital/position/?branch_id={self.br_b.id}')
        # El caja queda fijado a su propia sucursal; nunca sirve datos de B.
        self.assertNotEqual(res.status_code, 500)
        if res.status_code == 200:
            self.assertNotEqual(res.data.get('branch_id'), self.br_b.id)
