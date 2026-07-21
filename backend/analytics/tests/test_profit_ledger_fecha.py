# analytics/tests/test_profit_ledger_fecha.py
"""
Gap real (auditoría 2026-07-21): ProfitEngine.record_transaction_profit escribía
`fecha = timezone.localdate()` (día de INSERCIÓN) en vez del día contable de la
transacción. Una tx cargada tarde contabilizaba su P&L en el día equivocado y
descuadraba el snapshot diario frente a las filas del backfill (que sí usan la
fecha real). Ahora usa el día calendario en La_Paz de `created_at`.
"""
import uuid
from datetime import datetime, date, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from analytics.services import ProfitEngine

User = get_user_model()


def _make_company(name):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_branch(company, code):
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
    user.role = 'MANAGER'
    user.save()
    return user


def _make_currency(code, **extra):
    from rates.models import Currency
    return Currency.objects.get_or_create(
        code=code, defaults={'name_en': code, 'symbol': code, **extra})[0]


class ProfitLedgerFechaTests(TestCase):
    def setUp(self):
        self.company = _make_company(f'CasaLed-{uuid.uuid4().hex[:8]}')
        self.branch  = _make_branch(self.company, 'LD01')
        self.user    = _make_user(self.company, self.branch,
                                  f'led_{uuid.uuid4().hex[:8]}')
        self.usd = _make_currency('USD')
        self.bob = _make_currency('BOB', is_base_currency=True)

    def _make_backdated_buy(self, created_at):
        from transactions.models import Transaction
        tx = Transaction(
            transaction_type='BUY',
            currency_from=self.usd,
            currency_to=self.bob,
            amount_from=100,
            amount_to=1050,
            exchange_rate=Decimal('10.50'),
            payment_method='CASH',
            cashier=self.user,
            branch=self.branch,
            status='COMPLETED',
        )
        tx._effects_already_applied = True
        tx.save()
        # created_at es auto_now_add → forzar la fecha por queryset
        Transaction.objects.filter(pk=tx.pk).update(created_at=created_at)
        tx.refresh_from_db()
        return tx

    def test_ledger_usa_fecha_de_la_transaccion_no_de_insercion(self):
        # 15:00 UTC → 11:00 La_Paz del MISMO día (La_Paz = UTC-4)
        created = datetime(2026, 6, 15, 15, 0, tzinfo=dt_timezone.utc)
        tx = self._make_backdated_buy(created)

        ledger = ProfitEngine.record_transaction_profit(tx)

        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.fecha, date(2026, 6, 15))
        self.assertNotEqual(ledger.fecha, timezone.localdate())

    def test_frontera_de_dia_se_resuelve_en_zona_la_paz(self):
        # 02:00 UTC del 16 → 22:00 La_Paz del 15 (día contable = 15, no 16)
        created = datetime(2026, 6, 16, 2, 0, tzinfo=dt_timezone.utc)
        tx = self._make_backdated_buy(created)

        ledger = ProfitEngine.record_transaction_profit(tx)

        self.assertEqual(ledger.fecha, date(2026, 6, 15))
