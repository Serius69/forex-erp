# transactions/tests/test_nplus1_list.py
"""
Regresión de N+1 en el listado de transacciones (GET /api/transactions/).

Antes:
  - El CustomerSerializer anidado caía a las @property transaction_count
    (.count()) y total_volume (.aggregate(Sum)) → 2 queries EXTRA por fila.
  - profit_margin (property) consultaba ExchangeRate cuando
    parallel_rate_at_creation era null → 1 query EXTRA por fila.
  → el nº de queries crecía con el nº de filas (N+1).

Ahora el nº de queries del listado es CONSTANTE (independiente del nº de filas):
  - customer anidado usa CustomerNestedSerializer (sin los campos calculados).
  - el listado usa TransactionListSerializer (sin profit_margin).
"""
from decimal import Decimal

from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


def _make_company(name='TestCo'):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_branch(company, code='SUC01', name='Sucursal Test'):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code, name=name, is_active=True)


def _make_user(company, branch, role='ADMIN', username='admin_nplus1'):
    user = User.objects.create_user(
        username=username, password='testpass123', email=f'{username}@test.com',
    )
    user.company = company
    user.branch  = branch
    user.role    = role
    user.is_active = True
    user.save()
    return user


def _make_currency(code='USD'):
    from rates.models import Currency
    cur, _ = Currency.objects.get_or_create(
        code=code,
        defaults={
            'name_en': code, 'name_es': code, 'symbol': code,
            'is_active': True, 'use_exchange_rate': True,
            'is_base_currency': (code == 'BOB'),
        },
    )
    return cur


def _make_exchange_rate(currency_from, currency_to):
    from rates.models import ExchangeRate
    from django.utils import timezone
    return ExchangeRate.objects.create(
        currency_from=currency_from, currency_to=currency_to,
        market_type='paralelo_digital',
        official_rate=Decimal('6.90'), buy_rate=Decimal('6.85'),
        sell_rate=Decimal('6.95'), avg_rate=Decimal('6.90'),
        is_primary=True, valid_from=timezone.now(),
        source='TEST', source_method='MANUAL',
    )


class TransactionListNPlusOneTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.company = _make_company('CompanyN')
        self.branch  = _make_branch(self.company, 'N001')
        self.admin   = _make_user(self.company, self.branch, 'ADMIN')
        self.usd = _make_currency('USD')
        self.bob = _make_currency('BOB')
        # Tasa activa: sin la corrección, profit_margin la consultaría por fila.
        _make_exchange_rate(self.usd, self.bob)
        self.client.force_authenticate(user=self.admin)
        # Pre-cargar user.branch en la instancia reutilizada → no contamina el conteo.
        _ = self.admin.branch

    def _make_txs(self, start, count):
        # bulk_create evita el post_save de efectos de caja (que exigiría saldo
        # BOB) — aquí solo interesa la ruta de LECTURA/serialización del listado.
        from transactions.models import Transaction, Customer
        txs = []
        for i in range(start, start + count):
            customer = Customer.objects.create(
                company=self.company, document_type='CI',
                document_number=f'CI-{i:04d}', full_name=f'Cliente {i}',
            )
            txs.append(Transaction(
                transaction_number=f'N{i:08d}',
                transaction_type='BUY', transaction_category='REPORTABLE',
                currency_from=self.usd, currency_to=self.bob,
                amount_from=100, amount_to=690, exchange_rate=Decimal('6.90'),
                payment_method='CASH', cashier=self.admin, branch=self.branch,
                customer=customer, status='COMPLETED',
            ))
        Transaction.objects.bulk_create(txs)

    def _count_list_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get('/api/transactions/')
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.json().get('results', [])
        return len(ctx.captured_queries), len(results)

    def test_list_query_count_is_constant_regardless_of_rows(self):
        # Warm-up: descarta queries one-shot (content types, etc.) para medir limpio.
        self._make_txs(1, 2)
        self.client.get('/api/transactions/')

        # 2 filas
        q_two, n_two = self._count_list_queries()
        self.assertEqual(n_two, 2, 'El listado debería serializar 2 filas.')

        # 4 filas — el conteo NO debe crecer si el N+1 está eliminado.
        self._make_txs(3, 2)
        q_four, n_four = self._count_list_queries()
        self.assertEqual(n_four, 4, 'El listado debería serializar 4 filas.')

        self.assertEqual(
            q_two, q_four,
            f'N+1 detectado: 2 filas={q_two} queries, 4 filas={q_four} queries '
            f'(debería ser constante).',
        )
        # Cota superior defensiva: el listado no debe requerir muchas queries.
        self.assertLessEqual(
            q_four, 12,
            f'Listado usa {q_four} queries (>12); revisar select_related/prefetch.',
        )
