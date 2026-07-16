# rates/tests/test_signals_coalesce.py
"""
Regresión del broadcast O(N²) al guardar tasas (P3).

Antes: el receiver post_save de ExchangeRate re-consultaba TODAS las tasas activas
y hacía un broadcast WS completo en CADA save. Una corrida de update guarda decenas
de filas → N broadcasts idénticos redundantes.

Ahora una ráfaga de saves se colapsa en UN solo broadcast, emitido en
transaction.on_commit con un flag de coalescencia en caché.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django.core.cache import cache


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


def _new_rate(currency_from, currency_to, market_type='paralelo_digital', sell='6.95'):
    from rates.models import ExchangeRate
    return ExchangeRate.objects.create(
        currency_from=currency_from, currency_to=currency_to,
        market_type=market_type,
        official_rate=Decimal('6.90'), buy_rate=Decimal('6.85'),
        sell_rate=Decimal(sell), avg_rate=Decimal('6.90'),
        is_primary=(market_type == 'paralelo_digital'),
        valid_from=timezone.now(), source='TEST', source_method='MANUAL',
    )


class BroadcastCoalesceTests(TestCase):

    def setUp(self):
        # La caché LocMem persiste entre tests (no se hace rollback); el flag de
        # coalescencia de otras corridas debe limpiarse para no suprimir el broadcast.
        cache.clear()
        self.usd = _make_currency('USD')
        self.eur = _make_currency('EUR')
        self.bob = _make_currency('BOB')

    def test_burst_of_saves_triggers_single_broadcast(self):
        cache.clear()
        with patch('rates.signals._do_broadcast_rates') as mock_bc:
            with self.captureOnCommitCallbacks(execute=True):
                # 4 saves de tasas ACTIVAS (valid_until IS NULL) en una ráfaga.
                r = _new_rate(self.usd, self.bob)
                r.sell_rate = Decimal('6.96'); r.save()
                r.sell_rate = Decimal('6.97'); r.save()
                _new_rate(self.eur, self.bob, market_type='official')
        # Pese a 4 saves, un único broadcast (coalescido en on_commit).
        self.assertEqual(
            mock_bc.call_count, 1,
            f'Se esperaba 1 broadcast coalescido, hubo {mock_bc.call_count}.',
        )

    def test_historical_rate_save_does_not_broadcast(self):
        cache.clear()
        from rates.models import ExchangeRate
        with patch('rates.signals._do_broadcast_rates') as mock_bc:
            with self.captureOnCommitCallbacks(execute=True):
                # Tasa histórica (valid_until != null) → NO debe emitir broadcast.
                ExchangeRate.objects.create(
                    currency_from=self.usd, currency_to=self.bob,
                    market_type='paralelo_digital',
                    official_rate=Decimal('6.90'), buy_rate=Decimal('6.85'),
                    sell_rate=Decimal('6.95'), avg_rate=Decimal('6.90'),
                    is_primary=False, valid_from=timezone.now(),
                    valid_until=timezone.now(), source='TEST', source_method='MANUAL',
                )
        self.assertEqual(mock_bc.call_count, 0)

    def test_broadcast_payload_shape_preserved(self):
        """El payload conserva el contrato del WS (mismas claves por divisa)."""
        cache.clear()
        _new_rate(self.usd, self.bob)
        from rates.signals import _collect_active_rates
        rates = _collect_active_rates()
        # La clave es f'{code}_{market_type}' (contrato preexistente del WS).
        self.assertIn('USD_paralelo_digital', rates)
        entry = rates['USD_paralelo_digital']
        for key in ('code', 'name', 'scale_factor', 'market_type', 'buy', 'sell', 'official'):
            self.assertIn(key, entry)
        self.assertEqual(entry['code'], 'USD')
