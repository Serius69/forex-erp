"""Tests del módulo macro: modelo, parsers (con respuestas simuladas) y API."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from macro.fetchers import persist_points
from macro.models import MacroIndicator


class MacroIndicatorModelTest(TestCase):
    def test_upsert_idempotente(self):
        pts = [('inflacion_yoy', date(2025, 12, 31), Decimal('5.2'), '%', 'WB')]
        self.assertEqual(persist_points(pts), 1)
        # segundo upsert actualiza, no duplica
        pts2 = [('inflacion_yoy', date(2025, 12, 31), Decimal('6.0'), '%', 'WB')]
        self.assertEqual(persist_points(pts2), 1)
        self.assertEqual(MacroIndicator.objects.count(), 1)
        self.assertEqual(MacroIndicator.latest('inflacion_yoy').value, Decimal('6.000000'))

    def test_latest_value_map(self):
        persist_points([
            ('inflacion_yoy', date(2024, 12, 31), Decimal('4.0'), '%', 'WB'),
            ('inflacion_yoy', date(2025, 12, 31), Decimal('5.0'), '%', 'WB'),
            ('usd_internacional', date(2026, 7, 14), Decimal('10.08'), 'BOB/USD', 'er-api'),
        ])
        m = MacroIndicator.latest_value_map()
        self.assertEqual(m['inflacion_yoy'], Decimal('5.000000'))
        self.assertIn('usd_internacional', m)


class WorldBankParserTest(TestCase):
    @mock.patch('macro.fetchers.requests.get')
    def test_parsea_respuesta_wb(self, mget):
        mget.return_value.json.return_value = [
            {'page': 1},
            [
                {'date': '2025', 'value': 12.5},
                {'date': '2024', 'value': None},   # nulos se descartan
                {'date': '2023', 'value': 2.6},
            ],
        ]
        mget.return_value.raise_for_status = lambda: None
        from macro.fetchers import fetch_world_bank
        pts = fetch_world_bank()
        # 2 puntos válidos × 6 indicadores (misma respuesta simulada para todos)
        self.assertEqual(len(pts), 12)
        series_2025 = [p for p in pts if p[1] == date(2025, 12, 31)]
        self.assertTrue(all(p[2] == Decimal('12.5') for p in series_2025))


class BrechaTest(TestCase):
    def test_brecha_con_tasas_reales(self):
        from rates.models import Currency, ExchangeRate
        usd = Currency.objects.create(code='USD', name_en='US Dollar', symbol='$')
        bob = Currency.objects.create(code='BOB', name_en='Boliviano', symbol='Bs',
                                      is_base_currency=True)
        from django.utils import timezone
        common = dict(currency_from=usd, currency_to=bob,
                      official_rate=Decimal('10'), source='test',
                      valid_from=timezone.now())
        ExchangeRate.objects.create(market_type='official',
                                    buy_rate=Decimal('10.0'), sell_rate=Decimal('10.0'),
                                    **common)
        ExchangeRate.objects.create(market_type='paralelo_digital',
                                    buy_rate=Decimal('10.9'), sell_rate=Decimal('11.1'),
                                    **common)
        from macro.fetchers import compute_brecha_oficial
        pts = compute_brecha_oficial()
        self.assertEqual(len(pts), 1)
        # paralelo mid 11.0 vs oficial 10.0 → brecha 10%
        self.assertEqual(pts[0][2], Decimal('10.0000'))

    def test_brecha_sin_oficial_no_emite(self):
        from macro.fetchers import compute_brecha_oficial
        self.assertEqual(compute_brecha_oficial(), [])


class MacroAPITest(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user(
            username='macro_test', password='x', email='m@t.co')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        persist_points([
            ('brecha_oficial_pct', date(2026, 7, 14), Decimal('3.5'), '%', 'interna'),
            ('inflacion_yoy', date(2025, 12, 31), Decimal('12.1'), '%', 'WB'),
        ])

    def test_summary(self):
        r = self.client.get('/api/macro/indicators/summary/')
        self.assertEqual(r.status_code, 200)
        series = {i['series'] for i in r.data['indicators']}
        self.assertEqual(series, {'brecha_oficial_pct', 'inflacion_yoy'})

    def test_series_endpoint_valida(self):
        r = self.client.get('/api/macro/indicators/series/?series=inflacion_yoy')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['points']), 1)
        r400 = self.client.get('/api/macro/indicators/series/?series=nope')
        self.assertEqual(r400.status_code, 400)

    def test_requiere_auth(self):
        r = APIClient().get('/api/macro/indicators/summary/')
        self.assertIn(r.status_code, (401, 403))
