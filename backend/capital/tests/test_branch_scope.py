# capital/tests/test_branch_scope.py
"""
Tests del selector de sucursal (?branch_id=) en los endpoints de capital.

Reglas de _resolve_branch_scope:
  - ADMIN sin branch_id           → todas las sucursales de su empresa.
  - ADMIN con branch_id propio    → esa sucursal.
  - ADMIN con branch_id de OTRA empresa → 404 (aislamiento multi-tenant).
  - No-ADMIN                      → siempre su propia sucursal (param ignorado).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


def _make_company(name):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_branch(company, code, name):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code, name=name, is_active=True)


def _make_user(company, branch, role, username):
    user = User.objects.create_user(
        username=username, password='testpass123',
        email=f'{username}@test.com',
    )
    user.company = company
    user.branch = branch
    user.role = role
    user.save()
    return user


class BranchScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.company_a = _make_company('Empresa A')
        cls.company_b = _make_company('Empresa B')
        cls.branch_a1 = _make_branch(cls.company_a, 'A1', 'Central A')
        cls.branch_a2 = _make_branch(cls.company_a, 'A2', 'Sucursal A2')
        cls.branch_b1 = _make_branch(cls.company_b, 'B1', 'Central B')

        cls.admin_a = _make_user(cls.company_a, cls.branch_a1, 'ADMIN', 'admin_a')
        cls.cashier_a = _make_user(cls.company_a, cls.branch_a1, 'CASHIER', 'cashier_a')

    def setUp(self):
        self.client = APIClient()

    def test_admin_sin_branch_id_ve_todas(self):
        self.client.force_authenticate(user=self.admin_a)
        res = self.client.get('/api/capital/actual/')
        self.assertEqual(res.status_code, 200)

    def test_admin_con_branch_id_propio(self):
        self.client.force_authenticate(user=self.admin_a)
        res = self.client.get(f'/api/capital/actual/?branch_id={self.branch_a2.id}')
        self.assertEqual(res.status_code, 200)

    def test_admin_no_puede_ver_sucursal_de_otra_empresa(self):
        self.client.force_authenticate(user=self.admin_a)
        res = self.client.get(f'/api/capital/actual/?branch_id={self.branch_b1.id}')
        self.assertEqual(res.status_code, 404)

    def test_branch_id_invalido_devuelve_404(self):
        self.client.force_authenticate(user=self.admin_a)
        res = self.client.get('/api/capital/actual/?branch_id=999999')
        self.assertEqual(res.status_code, 404)

    def test_ganancias_y_resumen_aceptan_branch_id_admin(self):
        self.client.force_authenticate(user=self.admin_a)
        for url in ('/api/capital/ganancias/', '/api/capital/resumen/'):
            res = self.client.get(f'{url}?branch_id={self.branch_a2.id}')
            self.assertEqual(res.status_code, 200, url)
            res = self.client.get(f'{url}?branch_id={self.branch_b1.id}')
            self.assertEqual(res.status_code, 404, url)

    def test_cashier_ignora_branch_id_ajeno(self):
        # Para no-ADMIN el param se ignora: siempre su propia sucursal (200).
        self.client.force_authenticate(user=self.cashier_a)
        res = self.client.get(f'/api/capital/actual/?branch_id={self.branch_b1.id}')
        self.assertEqual(res.status_code, 200)
