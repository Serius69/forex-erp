# transactions/tests/test_rate_limits.py
"""
Tests del rate limiting extendido (ROADMAP v1.2) y del fix multi-tenant
en /customers/search/.

Notas:
  - Los límites por usuario usan claves de cache únicas por user id, y cada
    corrida crea usuarios nuevos → sin interferencia entre corridas aunque el
    cache sea Redis compartido.
  - El límite de verify-pin (10/min) protege el PIN de 4-6 dígitos contra
    fuerza bruta con sesión robada.
"""
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from core.ratelimit import check_rate_limit

User = get_user_model()


def _make_company(name):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_branch(company, code):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code,
                                 name=f'Sucursal {code}', is_active=True)


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


class RateLimitCoreTests(TestCase):
    """El contador central corta exactamente en el límite."""

    def test_check_rate_limit_corta_en_el_limite(self):
        ident = f'test:{uuid.uuid4()}'
        for i in range(5):
            exceeded, remaining = check_rate_limit(ident, requests=5, window=60)
            self.assertFalse(exceeded, f'no debió cortar en la petición {i + 1}')
        exceeded, remaining = check_rate_limit(ident, requests=5, window=60)
        self.assertTrue(exceeded)
        self.assertEqual(remaining, 0)


class VerifyPinThrottleTests(TestCase):
    """verify-pin: 10/min por usuario — anti fuerza bruta del PIN."""

    def setUp(self):
        self.company = _make_company(f'CasaRL-{uuid.uuid4().hex[:8]}')
        self.branch = _make_branch(self.company, 'RL01')
        # username único por corrida → clave de rate limit única (user id nuevo)
        self.user = _make_user(self.company, self.branch, 'CASHIER',
                               f'cajero_rl_{uuid.uuid4().hex[:8]}')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_pin_incorrecto_se_bloquea_tras_10_intentos(self):
        for i in range(10):
            res = self.client.post('/api/users/verify-pin/', {'pin': '0000'})
            self.assertEqual(res.status_code, 401,
                             f'intento {i + 1} debió ser 401 (PIN incorrecto)')
        res = self.client.post('/api/users/verify-pin/', {'pin': '0000'})
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data['code'], 'RATE_LIMIT_EXCEEDED')
        self.assertIn('Retry-After', res.headers)


class CustomerSearchTests(TestCase):
    """search: aislamiento multi-tenant (antes filtraba clientes de otras
    empresas) + rate limit configurado."""

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.company_a = _make_company(f'EmpresaA-{suffix}')
        self.company_b = _make_company(f'EmpresaB-{suffix}')
        self.branch_a = _make_branch(self.company_a, 'SA1')
        self.branch_b = _make_branch(self.company_b, 'SB1')
        self.user_a = _make_user(self.company_a, self.branch_a, 'CASHIER',
                                 f'cajero_a_{suffix}')

        from transactions.models import Customer
        self.doc_propio = f'11{suffix[:6]}'
        self.doc_ajeno  = f'22{suffix[:6]}'
        Customer.objects.create(
            company=self.company_a, document_type='CI',
            document_number=self.doc_propio, full_name='Cliente Propio',
        )
        Customer.objects.create(
            company=self.company_b, document_type='CI',
            document_number=self.doc_ajeno, full_name='Cliente Ajeno',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user_a)

    def test_encuentra_cliente_de_su_empresa(self):
        res = self.client.get(f'/api/customers/search/?document={self.doc_propio}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['full_name'], 'Cliente Propio')

    def test_no_ve_clientes_de_otra_empresa(self):
        res = self.client.get(f'/api/customers/search/?document={self.doc_ajeno}')
        self.assertEqual(res.status_code, 404)

    def test_mismo_documento_en_dos_empresas_no_rompe(self):
        # document_number es único POR empresa: el mismo número puede existir
        # en ambas; sin el filtro por company el .get() lanzaba
        # MultipleObjectsReturned (500).
        from transactions.models import Customer
        doc = f'33{uuid.uuid4().hex[:6]}'
        Customer.objects.create(
            company=self.company_a, document_type='CI',
            document_number=doc, full_name='Duplicado A',
        )
        Customer.objects.create(
            company=self.company_b, document_type='CI',
            document_number=doc, full_name='Duplicado B',
        )
        res = self.client.get(f'/api/customers/search/?document={doc}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['full_name'], 'Duplicado A')
