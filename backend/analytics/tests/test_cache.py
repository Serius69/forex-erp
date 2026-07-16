# analytics/tests/test_cache.py
"""
Regresión de caché en los endpoints de analytics (P2).

`analytics_overview` y `analytics_pnl` recalculaban Sum/Count/Avg en CADA request
pese a existir KPI_CACHE_TTL. Ahora cachean 5 min por (sucursal, rango/fecha):
la segunda llamada se sirve desde caché SIN tocar la base de datos.

En modo test la caché es LocMem aislada (ver core/settings/development.py), así que
estos tests no tocan la caché viva de producción.
"""
from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.core.cache import cache
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


def _make_company(name='TestCoCache'):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_admin(company, username='admin_cache'):
    # ADMIN SIN sucursal → _branch(request) devuelve None sin query FK,
    # de modo que un warm-hit puede alcanzar 0 queries.
    user = User.objects.create_user(
        username=username, password='testpass123', email=f'{username}@test.com',
    )
    user.company = company
    user.role    = 'ADMIN'
    user.is_active = True
    user.save()
    return user


class AnalyticsCacheTests(TestCase):

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.company = _make_company()
        self.admin   = _make_admin(self.company)
        self.client.force_authenticate(user=self.admin)

    def _warm_then_hit(self, url):
        with CaptureQueriesContext(connection) as cold:
            r1 = self.client.get(url)
        self.assertEqual(r1.status_code, 200, r1.content)
        with CaptureQueriesContext(connection) as warm:
            r2 = self.client.get(url)
        self.assertEqual(r2.status_code, 200, r2.content)
        return r1, r2, len(cold.captured_queries), len(warm.captured_queries)

    def test_overview_second_call_served_from_cache(self):
        r1, r2, n_cold, n_warm = self._warm_then_hit('/api/analytics/overview/')
        self.assertGreater(n_cold, 0, 'La primera llamada debería consultar la BD.')
        self.assertEqual(n_warm, 0, f'Warm hit debería ser 0 queries, fue {n_warm}.')
        self.assertEqual(r1.json(), r2.json(), 'La respuesta cacheada debe ser idéntica.')

    def test_pnl_second_call_served_from_cache(self):
        r1, r2, n_cold, n_warm = self._warm_then_hit('/api/analytics/pnl/')
        self.assertGreater(n_cold, 0, 'La primera llamada debería consultar la BD.')
        self.assertEqual(n_warm, 0, f'Warm hit debería ser 0 queries, fue {n_warm}.')
        self.assertEqual(r1.json(), r2.json(), 'La respuesta cacheada debe ser idéntica.')
