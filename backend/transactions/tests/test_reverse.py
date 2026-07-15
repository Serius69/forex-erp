# transactions/tests/test_reverse.py
"""
Contrato de Transaction.reverse(): la reversión se aplica EXACTAMENTE UNA VEZ.

Bug histórico: reverse() revertía inventario y caja manualmente (pasos 1-2) y
LUEGO creaba la anti-transacción COMPLETED, cuyo post_save (transactions.signals
+ capital.signals) volvía a aplicar efectos de caja/posición, y el paso 4
(`_update_inventory(reversal)`) volvía a mover inventario → todo por partida
doble. Estos tests fijan el contrato correcto:

  · _reverse_inventory(original)          → exactamente 1 vez
  · reverse_transaction_effects(original) → exactamente 1 vez
  · apply_transaction_effects(reversal)   → NUNCA (señal suprimida)
  · _update_inventory(reversal)           → NUNCA (la reversión ya se aplicó)
  · la anti-transacción queda como registro contable y la original REVERSED
"""
import uuid
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

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


class ReverseSingleApplicationTest(TestCase):
    def setUp(self):
        self.company = _make_company(f'CasaRev-{uuid.uuid4().hex[:8]}')
        self.branch  = _make_branch(self.company, 'RV01')
        self.user    = _make_user(self.company, self.branch,
                                  f'rev_{uuid.uuid4().hex[:8]}')
        self.usd = _make_currency('USD')
        self.bob = _make_currency('BOB', is_base_currency=True)

    def _make_completed_tx(self):
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
        # evitar efectos colaterales de señales en el ALTA del fixture
        tx._effects_already_applied = True
        tx.save()
        tx.completed_at = timezone.now()
        tx.save(update_fields=['completed_at'])
        return tx

    def test_reverse_aplica_efectos_exactamente_una_vez(self):
        tx = self._make_completed_tx()

        with mock.patch('transactions.services.TransactionService._reverse_inventory') as m_rev_inv, \
             mock.patch('transactions.services.reverse_transaction_effects') as m_rev_cash, \
             mock.patch('transactions.services.TransactionService._update_inventory') as m_upd_inv, \
             mock.patch('transactions.services.apply_transaction_effects') as m_apply_cash:
            reversal = tx.reverse(self.user, 'test doble aplicación')

        # Reversión manual exacta: UNA vez cada una, sobre la original
        m_rev_inv.assert_called_once()
        self.assertIs(m_rev_inv.call_args[0][0], tx)
        m_rev_cash.assert_called_once()
        self.assertIs(m_rev_cash.call_args[0][0], tx)

        # La anti-transacción NO debe volver a mover inventario ni caja
        m_upd_inv.assert_not_called()
        m_apply_cash.assert_not_called()

        # Registro contable correcto
        self.assertEqual(reversal.status, 'COMPLETED')
        self.assertEqual(reversal.transaction_type, 'SELL')
        self.assertIn('REVERSA', reversal.notes)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'REVERSED')

    def test_señal_caja_respeta_flag_supresion(self):
        """transaction_post_save no aplica caja si _effects_already_applied."""
        from transactions.models import Transaction
        with mock.patch('transactions.services.apply_transaction_effects') as m_apply:
            tx = Transaction(
                transaction_type='SELL',
                currency_from=self.bob,
                currency_to=self.usd,
                amount_from=1050,
                amount_to=100,
                exchange_rate=Decimal('0.0952'),
                payment_method='CASH',
                cashier=self.user,
                branch=self.branch,
                status='COMPLETED',
            )
            tx._effects_already_applied = True
            tx.save()
        m_apply.assert_not_called()

    def test_señal_caja_sigue_aplicando_sin_flag(self):
        """Sin el flag, la señal sigue funcionando como siempre (regresión)."""
        from transactions.models import Transaction
        with mock.patch('transactions.services.apply_transaction_effects') as m_apply:
            Transaction.objects.create(
                transaction_type='BUY',
                currency_from=self.usd,
                currency_to=self.bob,
                amount_from=50,
                amount_to=525,
                exchange_rate=Decimal('10.50'),
                payment_method='CASH',
                cashier=self.user,
                branch=self.branch,
                status='COMPLETED',
            )
        m_apply.assert_called_once()
