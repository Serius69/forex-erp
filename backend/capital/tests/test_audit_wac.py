# capital/tests/test_audit_wac.py
"""
Regresión del fix WAC en CurrencyPosition.apply_sell (auditoría 2026-07-20):
la venta debe consumir costo al WAC vigente (COGS) reduciendo total_cost_bob sin
alterar avg_acquisition_cost. Antes no reducía total_cost_bob → una compra
posterior inflaba el WAC de forma permanente.
"""
from decimal import Decimal

from django.test import TestCase


class WacApplySellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from tenants.models import Company
        from users.models import Branch
        from rates.models import Currency
        cls.comp = Company.objects.create(name='WAC Co', is_active=True)
        cls.branch = Branch.objects.create(company=cls.comp, code='W1', name='WAC', is_active=True)
        cls.usd, _ = Currency.objects.get_or_create(
            code='USD', defaults={'name_en': 'Dollar', 'name_es': 'Dólar', 'symbol': '$'})

    def _pos(self):
        from capital.models import CurrencyPosition
        return CurrencyPosition(
            branch=self.branch, currency=self.usd,
            net_position=Decimal('0'), total_cost_bob=Decimal('0'),
            total_bought=Decimal('0'), total_sold=Decimal('0'),
            avg_acquisition_cost=Decimal('0'),
        )

    def test_wac_estable_tras_venta_y_compra(self):
        pos = self._pos()
        pos.apply_buy(Decimal('100'), Decimal('7'))   # 100 @7 → cost 700, avg 7
        self.assertEqual(pos.avg_acquisition_cost, Decimal('7'))
        self.assertEqual(pos.total_cost_bob, Decimal('700'))

        pos.apply_sell(Decimal('50'), Decimal('10'))  # vende 50 → COGS 350
        self.assertEqual(pos.net_position, Decimal('50'))
        self.assertEqual(pos.total_cost_bob, Decimal('350'))   # 700 - 50*7
        self.assertEqual(pos.avg_acquisition_cost, Decimal('7'))  # WAC no cambia al vender

        pos.apply_buy(Decimal('50'), Decimal('9'))    # 50 @9 → cost 350+450=800, net 100
        self.assertEqual(pos.total_cost_bob, Decimal('800'))
        # WAC correcto = (50*7 + 50*9)/100 = 8.0 (antes daba 11.5 por el bug)
        self.assertEqual(pos.avg_acquisition_cost, Decimal('8'))
        # Invariante WAC: total_cost == net * avg
        self.assertEqual(pos.total_cost_bob, pos.net_position * pos.avg_acquisition_cost)
