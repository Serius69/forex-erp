# inventory/tests.py
"""
Tests de CurrencyInventory: WAC, transferencias entre sucursales y ajustes.

Cubren los fixes de concurrencia de 2026-07: transfer_to_branch y
adjust_inventory ahora son atómicos con select_for_update (antes un remove+add
sin lock podía perder movimientos o dejar transferencias a medias).
"""
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory.models import CurrencyInventory, InventoryMovement, InventoryTransfer

User = get_user_model()


def _mk_company(name):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _mk_branch(company, code):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code,
                                 name=f'Sucursal {code}', is_active=True)


def _mk_user(company, branch, username):
    u = User.objects.create_user(username=username, password='x',
                                 email=f'{username}@t.co')
    u.company, u.branch, u.role = company, branch, 'MANAGER'
    u.save()
    return u


def _mk_currency(code):
    from rates.models import Currency
    return Currency.objects.get_or_create(
        code=code, defaults={'name_en': code, 'symbol': code})[0]


class InventoryBaseTest(TestCase):
    def setUp(self):
        suf = uuid.uuid4().hex[:6]
        self.company = _mk_company(f'CasaInv-{suf}')
        self.b1 = _mk_branch(self.company, f'I1{suf[:2]}')
        self.b2 = _mk_branch(self.company, f'I2{suf[:2]}')
        self.user = _mk_user(self.company, self.b1, f'inv_{suf}')
        self.usd = _mk_currency('USD')
        self.inv = CurrencyInventory.objects.create(
            currency=self.usd, branch=self.b1,
            physical_balance=Decimal('1000'), digital_balance=Decimal('500'),
            minimum_stock=Decimal('100'), maximum_stock=Decimal('10000'),
            weighted_average_cost=Decimal('10.00'),
        )


class WacTest(InventoryBaseTest):
    def test_add_currency_actualiza_wac(self):
        # WAC pondera el balance FÍSICO (las compras entran a caja física):
        # 1000 fís. @10.00 + 500 @12.00 → (1000*10 + 500*12) / 1500 = 10.6667
        self.inv.add_currency(Decimal('500'), Decimal('12.00'), self.user)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.total_balance, Decimal('2000'))   # 1500 fís. + 500 dig.
        self.assertAlmostEqual(float(self.inv.weighted_average_cost), 10.6667, places=3)

    def test_remove_currency_no_toca_wac(self):
        self.inv.remove_currency(Decimal('300'), self.user)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.total_balance, Decimal('1200'))
        self.assertEqual(self.inv.weighted_average_cost, Decimal('10.00'))


class TransferTest(InventoryBaseTest):
    def test_transfer_mueve_saldo_y_registra(self):
        self.inv.transfer_to_branch(self.b2, Decimal('400'), self.user)

        self.inv.refresh_from_db()
        dest = CurrencyInventory.objects.get(currency=self.usd, branch=self.b2)
        self.assertEqual(self.inv.total_balance, Decimal('1100'))   # 1500 - 400
        self.assertEqual(dest.total_balance, Decimal('400'))
        # el destino hereda el costo del origen
        self.assertEqual(dest.weighted_average_cost, Decimal('10.00'))

        t = InventoryTransfer.objects.get(source_branch=self.b1, target_branch=self.b2)
        self.assertEqual(t.amount, Decimal('400'))
        self.assertEqual(t.status, 'COMPLETED')

    def test_transfer_saldo_insuficiente_lanza_y_no_muta(self):
        with self.assertRaises(ValueError):
            self.inv.transfer_to_branch(self.b2, Decimal('99999'), self.user)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.total_balance, Decimal('1500'))
        self.assertFalse(
            CurrencyInventory.objects.filter(branch=self.b2).exists())

    def test_transfer_usa_saldo_fresco_de_bd(self):
        """El chequeo de saldo relee bajo lock — una instancia vieja no engaña."""
        stale = CurrencyInventory.objects.get(pk=self.inv.pk)
        # otro proceso retira casi todo
        self.inv.remove_currency(Decimal('1400'), self.user)
        # la instancia vieja cree tener 1500; el lock relee 100 → debe fallar
        with self.assertRaises(ValueError):
            stale.transfer_to_branch(self.b2, Decimal('500'), self.user)


class AdjustTest(InventoryBaseTest):
    def test_ajuste_registra_movimiento_y_actualiza(self):
        self.inv.adjust_inventory(Decimal('950'), Decimal('500'),
                                  self.user, 'conteo físico')
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.physical_balance, Decimal('950'))
        self.assertEqual(self.inv.digital_balance, Decimal('500'))
        mv = InventoryMovement.objects.filter(
            inventory=self.inv, movement_type='ADJUSTMENT').latest('id')
        self.assertEqual(mv.amount, Decimal('50'))
        self.assertIn('conteo físico', mv.notes)

    def test_ajuste_sin_diferencia_no_registra(self):
        before = InventoryMovement.objects.count()
        self.inv.adjust_inventory(Decimal('1000'), Decimal('500'),
                                  self.user, 'sin cambios')
        self.assertEqual(InventoryMovement.objects.count(), before)

    def test_ajuste_parte_de_balances_frescos(self):
        """El diff se calcula contra la BD bajo lock, no contra la instancia."""
        stale = CurrencyInventory.objects.get(pk=self.inv.pk)
        self.inv.add_currency(Decimal('200'), Decimal('10.00'), self.user)  # BD: 1200 fís.
        # la instancia vieja cree que hay 1000 físico; el conteo dice 1200 →
        # con balances frescos el diff es 0 y NO debe registrar ajuste
        before = InventoryMovement.objects.filter(movement_type='ADJUSTMENT').count()
        stale.adjust_inventory(Decimal('1200'), Decimal('500'),
                               self.user, 'conteo coincide con BD real')
        after = InventoryMovement.objects.filter(movement_type='ADJUSTMENT').count()
        self.assertEqual(after, before)
