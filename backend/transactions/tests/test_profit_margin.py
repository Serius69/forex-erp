# transactions/tests/test_profit_margin.py
"""
Tests de Transaction.profit_margin con spread REAL.

Cubre las tres vías de cálculo:
  1. Snapshot de tasa paralela (parallel_rate_at_creation) — BUY y SELL,
     incluyendo margen negativo (operación a pérdida).
  2. Medio spread del ExchangeRate vigente de la divisa.
  3. Fallback legacy 0.3% cuando no hay datos de mercado.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from rates.models import Currency, ExchangeRate
from transactions.models import Transaction


def _make_currency(code='USD'):
    cur, _ = Currency.objects.get_or_create(
        code=code,
        defaults={
            'name_en': code, 'name_es': code,
            'symbol': code, 'is_active': True,
            'use_exchange_rate': True, 'is_base_currency': (code == 'BOB'),
        },
    )
    return cur


class ProfitMarginParallelSnapshotTests(TestCase):
    """Vía 1 — margen contra la tasa paralela capturada al crear."""

    @classmethod
    def setUpTestData(cls):
        cls.usd = _make_currency('USD')
        cls.bob = _make_currency('BOB')

    def _tx(self, **kwargs):
        """Instancia SIN guardar — profit_margin no necesita DB para la vía 1."""
        defaults = dict(
            transaction_type='BUY',
            currency_from=self.usd,
            currency_to=self.bob,
            amount_from=100,
            amount_to=690,
            exchange_rate=Decimal('6.9000'),
        )
        defaults.update(kwargs)
        return Transaction(**defaults)

    def test_buy_con_snapshot_paralelo(self):
        # Casa compra USD a 6.90 con mercado a 6.96 → gana 0.06/unidad
        tx = self._tx(parallel_rate_at_creation=Decimal('6.9600'))
        self.assertEqual(tx.profit_margin, Decimal('6.00'))

    def test_sell_con_snapshot_paralelo(self):
        # Casa vende USD a 6.97 con mercado a 6.92 → gana 0.05/unidad × 200
        tx = self._tx(
            transaction_type='SELL',
            currency_from=self.bob,
            currency_to=self.usd,
            amount_from=1394,
            amount_to=200,
            exchange_rate=Decimal('6.9700'),
            parallel_rate_at_creation=Decimal('6.9200'),
        )
        self.assertEqual(tx.profit_margin, Decimal('10.00'))

    def test_buy_a_perdida_es_negativo(self):
        # Casa compra a 6.90 con mercado a 6.85 → pierde 0.05/unidad
        tx = self._tx(parallel_rate_at_creation=Decimal('6.8500'))
        self.assertEqual(tx.profit_margin, Decimal('-5.00'))

    def test_sin_exchange_rate_devuelve_cero(self):
        tx = self._tx(exchange_rate=None)
        self.assertEqual(tx.profit_margin, Decimal('0.00'))


class ProfitMarginActiveRateTests(TestCase):
    """Vía 2 — medio spread del ExchangeRate vigente (sin snapshot)."""

    @classmethod
    def setUpTestData(cls):
        cls.usd = _make_currency('USD')
        cls.bob = _make_currency('BOB')
        ExchangeRate.objects.create(
            currency_from=cls.usd,
            currency_to=cls.bob,
            market_type='paralelo_digital',
            official_rate=Decimal('6.9000'),
            buy_rate=Decimal('6.8500'),
            sell_rate=Decimal('6.9500'),
            avg_rate=Decimal('6.9000'),
            is_primary=True,
            valid_from=timezone.now(),
            source='TEST',
            source_method='MANUAL',
        )

    def test_buy_usa_medio_spread_vigente(self):
        # Spread 0.10 → medio spread 0.05/unidad × 100 = 5.00
        tx = Transaction(
            transaction_type='BUY',
            currency_from=self.usd,
            currency_to=self.bob,
            amount_from=100,
            amount_to=690,
            exchange_rate=Decimal('6.9000'),
        )
        self.assertEqual(tx.profit_margin, Decimal('5.00'))

    def test_sell_usa_unidades_de_amount_to(self):
        # SELL: unidades de divisa están en amount_to (50 × 0.05 = 2.50)
        tx = Transaction(
            transaction_type='SELL',
            currency_from=self.bob,
            currency_to=self.usd,
            amount_from=348,
            amount_to=50,
            exchange_rate=Decimal('6.9500'),
        )
        self.assertEqual(tx.profit_margin, Decimal('2.50'))


class ProfitMarginFallbackTests(TestCase):
    """Vía 3 — fallback legacy 0.3% sin snapshot ni tasa vigente."""

    @classmethod
    def setUpTestData(cls):
        cls.eur = _make_currency('EUR')   # sin ExchangeRate activo
        cls.bob = _make_currency('BOB')

    def test_fallback_legacy_03_por_ciento(self):
        tx = Transaction(
            transaction_type='BUY',
            currency_from=self.eur,
            currency_to=self.bob,
            amount_from=100,
            amount_to=800,
            exchange_rate=Decimal('8.0000'),
        )
        # 8.0 × 0.003 × 100 = 2.40
        self.assertEqual(tx.profit_margin, Decimal('2.40'))
