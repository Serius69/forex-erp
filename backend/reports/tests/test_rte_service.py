# reports/tests/test_rte_service.py
"""
Tests del RTE automático (RTEService + señal transaction_rte_check).

Regla ASFI: transacción en efectivo con equivalente >= USD 1,000 genera
CashTransactionReport y una alerta push (AlertLog + WS).
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from reports.models import CashTransactionReport
from reports.services.rte_service import RTEService

User = get_user_model()


def _make_company(name):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_branch(company, code='SUC01'):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code,
                                 name=f'Sucursal {code}', is_active=True)


def _make_user(company, branch, role='CASHIER', username='cajero_rte'):
    user = User.objects.create_user(
        username=username, password='testpass123',
        email=f'{username}@test.com',
    )
    user.company = company
    user.branch = branch
    user.role = role
    user.save()
    return user


def _make_currency(code):
    from rates.models import Currency
    cur, _ = Currency.objects.get_or_create(
        code=code,
        defaults={
            'name_en': code, 'name_es': code,
            'symbol': code, 'is_active': True,
            'use_exchange_rate': True, 'is_base_currency': (code == 'BOB'),
        },
    )
    return cur


def _make_rate(cfrom, cto, buy, sell, market='paralelo_digital'):
    from rates.models import ExchangeRate
    return ExchangeRate.objects.create(
        currency_from=cfrom, currency_to=cto,
        market_type=market,
        official_rate=Decimal(str(sell)),
        buy_rate=Decimal(str(buy)), sell_rate=Decimal(str(sell)),
        avg_rate=Decimal(str((buy + sell) / 2)),
        is_primary=True, valid_from=timezone.now(),
        source='TEST', source_method='MANUAL',
    )


class RTEServiceTests(TestCase):

    def setUp(self):
        self.company = _make_company('CasaCambioRTE')
        self.branch  = _make_branch(self.company)
        self.cashier = _make_user(self.company, self.branch)
        self.bob = _make_currency('BOB')
        self.usd = _make_currency('USD')
        self.eur = _make_currency('EUR')
        _make_rate(self.usd, self.bob, 6.85, 6.95)   # mid 6.90

        from transactions.models import Customer
        self.customer = Customer.objects.create(
            company=self.company,
            document_type='CI', document_number='1234567',
            full_name='Juan Perez Reportable',
        )

    def _make_tx(self, amount_from, amount_to, currency_from, currency_to,
                 tx_type='BUY', payment='CASH', category='REPORTABLE',
                 customer=None):
        from transactions.models import Transaction
        return Transaction.objects.create(
            transaction_type=tx_type,
            transaction_category=category,
            currency_from=currency_from, currency_to=currency_to,
            amount_from=amount_from, amount_to=amount_to,
            exchange_rate=Decimal('6.90'),
            payment_method=payment,
            customer=customer if customer is not None else self.customer,
            cashier=self.cashier, branch=self.branch,
            status='COMPLETED',
        )

    # ── Creación automática vía señal ─────────────────────────────────────────

    def test_compra_usd_sobre_umbral_crea_rte(self):
        tx = self._make_tx(1500, 10350, self.usd, self.bob)
        rte = CashTransactionReport.objects.filter(transaction=tx).first()
        self.assertIsNotNone(rte, 'La señal debió crear el RTE automáticamente')
        self.assertEqual(rte.amount_usd_equiv, Decimal('1500.00'))
        self.assertEqual(rte.currency_code, 'USD')
        self.assertEqual(rte.customer_full_name, 'Juan Perez Reportable')
        self.assertTrue(rte.report_number.startswith('RTE'))

    def test_bajo_umbral_no_crea_rte(self):
        tx = self._make_tx(500, 3450, self.usd, self.bob)
        self.assertFalse(
            CashTransactionReport.objects.filter(transaction=tx).exists())

    def test_pago_no_efectivo_no_crea_rte(self):
        tx = self._make_tx(2000, 13800, self.usd, self.bob, payment='QR')
        self.assertFalse(
            CashTransactionReport.objects.filter(transaction=tx).exists())

    def test_venta_usd_usa_amount_to(self):
        # SELL: la casa entrega USD (amount_to), recibe BOB (amount_from).
        tx = self._make_tx(8280, 1200, self.bob, self.usd, tx_type='SELL')
        rte = CashTransactionReport.objects.filter(transaction=tx).first()
        self.assertIsNotNone(rte)
        self.assertEqual(rte.amount_usd_equiv, Decimal('1200.00'))

    def test_divisa_no_usd_convierte_con_tasa_paralela(self):
        # BUY 2000 EUR por 15,600 BOB → equiv = 15600 / 6.90 ≈ 2260.87 USD
        tx = self._make_tx(2000, 15600, self.eur, self.bob)
        rte = CashTransactionReport.objects.filter(transaction=tx).first()
        self.assertIsNotNone(rte)
        self.assertEqual(rte.currency_code, 'EUR')
        self.assertEqual(rte.original_amount, Decimal('2000.00'))
        self.assertAlmostEqual(float(rte.amount_usd_equiv), 15600 / 6.90, places=1)

    def test_idempotente(self):
        tx = self._make_tx(1500, 10350, self.usd, self.bob)
        self.assertIsNone(RTEService.evaluar_transaccion(tx))
        self.assertEqual(
            CashTransactionReport.objects.filter(transaction=tx).count(), 1)

    # ── Notificación push (AlertLog vía on_commit) ────────────────────────────

    def test_notificacion_alertlog_al_commit(self):
        from alerts.models import AlertLog
        with self.captureOnCommitCallbacks(execute=True):
            tx = self._make_tx(1500, 10350, self.usd, self.bob)
        alerta = AlertLog.objects.filter(alert_type='RTE_CREATED').first()
        self.assertIsNotNone(alerta, 'El RTE debió emitir una alerta global')
        self.assertIn(tx.transaction_number, alerta.message)
        self.assertEqual(alerta.severity, 'MEDIUM')

    def test_cliente_pep_severidad_alta(self):
        from alerts.models import AlertLog
        from transactions.models import Customer
        pep = Customer.objects.create(
            company=self.company, document_type='CI',
            document_number='7654321', full_name='Maria PEP', is_pep=True,
        )
        with self.captureOnCommitCallbacks(execute=True):
            self._make_tx(3000, 20700, self.usd, self.bob, customer=pep)
        alerta = AlertLog.objects.filter(alert_type='RTE_CREATED').first()
        self.assertIsNotNone(alerta)
        self.assertEqual(alerta.severity, 'HIGH')
        rte = CashTransactionReport.objects.get(customer_document_num='7654321')
        self.assertTrue(rte.customer_is_pep)
