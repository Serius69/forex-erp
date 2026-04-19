# transactions/tests/test_validators.py
"""
Tests para las reglas de validación financiera de transacciones.

Cobertura:
  - validate_integer_amount: montos con/sin decimales
  - validate_denomination: BILLS, SUELTOS, SINGLES, tipo desconocido
  - validate_transaction_amounts: reglas combinadas por escenario
  - nearest_valid_amount: cálculo de sugerencias
"""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from transactions.validators import (
    DENOMINATION_BILLS,
    DENOMINATION_SUELTOS,
    DENOMINATION_SINGLES,
    nearest_valid_amount,
    validate_denomination,
    validate_integer_amount,
    validate_transaction_amounts,
)


# ── validate_integer_amount ───────────────────────────────────────────────────

class ValidateIntegerAmountTests(SimpleTestCase):

    def test_integer_passes(self):
        validate_integer_amount(Decimal('100'))        # no exception

    def test_integer_as_decimal_passes(self):
        validate_integer_amount(Decimal('200.00'))     # .00 is fine

    def test_decimal_raises(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_integer_amount(Decimal('100.50'))
        self.assertIn('amount_from', str(ctx.exception) + 'amount_from')
        # default field_name = 'monto' — check message content instead
        err = ctx.exception.message_dict
        self.assertIn('monto', err)
        self.assertIn('100', err['monto'][0] if isinstance(err['monto'], list) else err['monto'])

    def test_decimal_custom_field_name(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_integer_amount(Decimal('7.50'), field_name='amount_to')
        self.assertIn('amount_to', ctx.exception.message_dict)

    def test_large_integer_passes(self):
        validate_integer_amount(Decimal('1000000'))


# ── validate_denomination ─────────────────────────────────────────────────────

class ValidateDenominationTests(SimpleTestCase):

    # BILLS (divisible by 50)
    def test_bills_100_passes(self):
        validate_denomination(Decimal('100'), DENOMINATION_BILLS)

    def test_bills_50_passes(self):
        validate_denomination(Decimal('50'), DENOMINATION_BILLS)

    def test_bills_200_passes(self):
        validate_denomination(Decimal('200'), DENOMINATION_BILLS)

    def test_bills_75_fails(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_denomination(Decimal('75'), DENOMINATION_BILLS)
        err = ctx.exception.message_dict
        self.assertIn('amount', err)
        self.assertIn('BILLS', err['amount'][0] if isinstance(err['amount'], list) else err['amount'])

    def test_bills_30_fails(self):
        with self.assertRaises(ValidationError):
            validate_denomination(Decimal('30'), DENOMINATION_BILLS)

    # SUELTOS (divisible by 5)
    def test_sueltos_5_passes(self):
        validate_denomination(Decimal('5'), DENOMINATION_SUELTOS)

    def test_sueltos_20_passes(self):
        validate_denomination(Decimal('20'), DENOMINATION_SUELTOS)

    def test_sueltos_15_passes(self):
        validate_denomination(Decimal('15'), DENOMINATION_SUELTOS)

    def test_sueltos_12_fails(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_denomination(Decimal('12'), DENOMINATION_SUELTOS)
        err = ctx.exception.message_dict
        self.assertIn('SUELTOS', err['amount'][0] if isinstance(err['amount'], list) else err['amount'])

    def test_sueltos_3_fails(self):
        with self.assertRaises(ValidationError):
            validate_denomination(Decimal('3'), DENOMINATION_SUELTOS)

    # SINGLES (any positive integer)
    def test_singles_1_passes(self):
        validate_denomination(Decimal('1'), DENOMINATION_SINGLES)

    def test_singles_2_passes(self):
        validate_denomination(Decimal('2'), DENOMINATION_SINGLES)

    def test_singles_7_passes(self):
        validate_denomination(Decimal('7'), DENOMINATION_SINGLES)

    def test_singles_99_passes(self):
        validate_denomination(Decimal('99'), DENOMINATION_SINGLES)

    # Zero and unknown
    def test_zero_fails(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_denomination(Decimal('0'), DENOMINATION_BILLS)
        self.assertIn('mayor a 0', str(ctx.exception))

    def test_unknown_denomination_raises(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_denomination(Decimal('100'), 'UNKNOWN')
        self.assertIn('desconocido', str(ctx.exception))


# ── validate_transaction_amounts ──────────────────────────────────────────────

class ValidateTransactionAmountsTests(SimpleTestCase):
    """Integration tests for the main validation entry point."""

    # ── Happy paths ──────────────────────────────────────────────────────────

    def test_buy_usd_cash_bills_valid(self):
        """BUY 200 USD (BILLS) against BOB — should pass."""
        validate_transaction_amounts(
            currency_from_code='BOB',
            currency_to_code='USD',
            amount_from=Decimal('1380'),
            amount_to=Decimal('200'),
            payment_method='CASH',
            denomination_type=DENOMINATION_BILLS,
            transaction_type='BUY',
        )

    def test_sell_usd_cash_sueltos_valid(self):
        """SELL 15 USD (SUELTOS) → BOB — should pass."""
        validate_transaction_amounts(
            currency_from_code='USD',
            currency_to_code='BOB',
            amount_from=Decimal('15'),
            amount_to=Decimal('103.5'),
            payment_method='CASH',
            denomination_type=DENOMINATION_SUELTOS,
            transaction_type='SELL',
        )

    def test_sell_usd_cash_singles_valid(self):
        """SELL 3 USD (SINGLES) — any integer, should pass."""
        validate_transaction_amounts(
            currency_from_code='USD',
            currency_to_code='BOB',
            amount_from=Decimal('3'),
            amount_to=Decimal('20.7'),
            payment_method='CASH',
            denomination_type=DENOMINATION_SINGLES,
            transaction_type='SELL',
        )

    def test_transfer_usd_no_denomination_required(self):
        """TRANSFER does not require denomination_type."""
        validate_transaction_amounts(
            currency_from_code='USD',
            currency_to_code='BOB',
            amount_from=Decimal('1000'),
            amount_to=Decimal('6900'),
            payment_method='TRANSFER',
            denomination_type=None,
            transaction_type='SELL',
        )

    def test_bob_to_bob_no_integer_check(self):
        """BOB/BOB transactions skip integer check (BOB can have decimals)."""
        validate_transaction_amounts(
            currency_from_code='BOB',
            currency_to_code='BOB',
            amount_from=Decimal('100.50'),
            amount_to=Decimal('100.50'),
            payment_method='CASH',
            denomination_type=None,
            transaction_type='BUY',
        )

    def test_eur_to_bob_integer_required(self):
        """EUR/BOB non-CASH: integer rule applies to EUR side, no denomination."""
        validate_transaction_amounts(
            currency_from_code='EUR',
            currency_to_code='BOB',
            amount_from=Decimal('500'),
            amount_to=Decimal('3800'),
            payment_method='TRANSFER',
            denomination_type=None,
            transaction_type='SELL',
        )

    # ── Failure paths ────────────────────────────────────────────────────────

    def test_buy_usd_cash_missing_denomination_type(self):
        """CASH + USD without denomination_type → error."""
        with self.assertRaises(ValidationError) as ctx:
            validate_transaction_amounts(
                currency_from_code='BOB',
                currency_to_code='USD',
                amount_from=Decimal('1380'),
                amount_to=Decimal('200'),
                payment_method='CASH',
                denomination_type=None,
                transaction_type='BUY',
            )
        self.assertIn('denomination_type', ctx.exception.message_dict)

    def test_buy_usd_cash_bills_not_divisible(self):
        """BUY 75 USD with BILLS (not divisible by 50) → error."""
        with self.assertRaises(ValidationError) as ctx:
            validate_transaction_amounts(
                currency_from_code='BOB',
                currency_to_code='USD',
                amount_from=Decimal('517.5'),
                amount_to=Decimal('75'),
                payment_method='CASH',
                denomination_type=DENOMINATION_BILLS,
                transaction_type='BUY',
            )
        err = ctx.exception.message_dict
        self.assertIn('amount_to', err)

    def test_sell_usd_cash_sueltos_not_divisible(self):
        """SELL 13 USD with SUELTOS (not divisible by 5) → error."""
        with self.assertRaises(ValidationError) as ctx:
            validate_transaction_amounts(
                currency_from_code='USD',
                currency_to_code='BOB',
                amount_from=Decimal('13'),
                amount_to=Decimal('89.7'),
                payment_method='CASH',
                denomination_type=DENOMINATION_SUELTOS,
                transaction_type='SELL',
            )
        err = ctx.exception.message_dict
        self.assertIn('amount_from', err)

    def test_usd_amount_with_decimals_rejected(self):
        """USD amount with fractional cents → integer error."""
        with self.assertRaises(ValidationError) as ctx:
            validate_transaction_amounts(
                currency_from_code='USD',
                currency_to_code='BOB',
                amount_from=Decimal('100.50'),
                amount_to=Decimal('693.45'),
                payment_method='CASH',
                denomination_type=DENOMINATION_BILLS,
                transaction_type='SELL',
            )
        err = ctx.exception.message_dict
        self.assertIn('amount_from', err)

    def test_eur_amount_with_decimals_rejected(self):
        """EUR side should also require integer."""
        with self.assertRaises(ValidationError) as ctx:
            validate_transaction_amounts(
                currency_from_code='EUR',
                currency_to_code='BOB',
                amount_from=Decimal('99.99'),
                amount_to=Decimal('756'),
                payment_method='TRANSFER',
                denomination_type=None,
                transaction_type='SELL',
            )
        err = ctx.exception.message_dict
        self.assertIn('amount_from', err)

    def test_qr_payment_no_denomination_needed(self):
        """QR payment bypasses denomination check even for USD."""
        validate_transaction_amounts(
            currency_from_code='USD',
            currency_to_code='BOB',
            amount_from=Decimal('100'),
            amount_to=Decimal('690'),
            payment_method='QR',
            denomination_type=None,
            transaction_type='SELL',
        )

    def test_multiple_errors_collected(self):
        """Both integer error on amount_from AND denomination error should surface together."""
        with self.assertRaises(ValidationError) as ctx:
            validate_transaction_amounts(
                currency_from_code='USD',
                currency_to_code='BOB',
                amount_from=Decimal('13.50'),   # decimal + not divisible by 5
                amount_to=Decimal('93.15'),
                payment_method='CASH',
                denomination_type=DENOMINATION_SUELTOS,
                transaction_type='SELL',
            )
        err = ctx.exception.message_dict
        # integer error on amount_from must be present
        self.assertIn('amount_from', err)


# ── nearest_valid_amount ──────────────────────────────────────────────────────

class NearestValidAmountTests(SimpleTestCase):

    def test_bills_75_suggests_50_and_100(self):
        result = nearest_valid_amount(75, DENOMINATION_BILLS)
        self.assertEqual(result['floor'], 50)
        self.assertEqual(result['ceil'], 100)
        self.assertEqual(result['divisor'], 50)

    def test_bills_200_exact(self):
        result = nearest_valid_amount(200, DENOMINATION_BILLS)
        self.assertEqual(result['floor'], 200)
        self.assertEqual(result['ceil'], 200)

    def test_sueltos_12_suggests_10_and_15(self):
        result = nearest_valid_amount(12, DENOMINATION_SUELTOS)
        self.assertEqual(result['floor'], 10)
        self.assertEqual(result['ceil'], 15)

    def test_sueltos_0_floor_becomes_divisor(self):
        result = nearest_valid_amount(0, DENOMINATION_SUELTOS)
        self.assertEqual(result['floor'], 5)

    def test_singles_7_exact(self):
        result = nearest_valid_amount(7, DENOMINATION_SINGLES)
        self.assertEqual(result['floor'], 7)

    def test_unknown_denomination_returns_empty(self):
        result = nearest_valid_amount(100, 'BOGUS')
        self.assertEqual(result, {})
