"""Tests del módulo de simulación Monte Carlo/VaR (predictions/simulation.py)."""
from datetime import timedelta
from decimal import Decimal

import numpy as np
from django.test import TestCase
from django.utils import timezone

from predictions.models import TrainingData
from predictions.simulation import (
    SimulationError, load_series, position_var, simulate_paths,
)


def _seed_series(pair='USD/BOB', market='web', days=200, start_rate=10.0,
                 daily_drift=0.0005, daily_vol=0.008, seed=7):
    """Siembra una serie diaria realista en TrainingData."""
    rng = np.random.default_rng(seed)
    now = timezone.now()
    rate = start_rate
    rows = []
    for i in range(days):
        rate *= float(np.exp(daily_drift + daily_vol * rng.standard_normal()))
        rows.append(TrainingData(
            currency_pair=pair, market=market,
            date=now - timedelta(days=days - i),
            rate=Decimal(str(round(rate, 4))), source=market,
        ))
    TrainingData.objects.bulk_create(rows)
    return rate


class LoadSeriesTest(TestCase):
    def test_calibra_con_historia_suficiente(self):
        last = _seed_series()
        s = load_series('USD/BOB', 'web')
        self.assertEqual(s.n_days, 200)
        self.assertAlmostEqual(s.last_rate, last, places=3)
        self.assertGreater(s.sigma_daily, 0)

    def test_historia_insuficiente_lanza(self):
        _seed_series(days=20)
        with self.assertRaises(SimulationError):
            load_series('USD/BOB', 'web')

    def test_market_separado(self):
        _seed_series(market='web')
        with self.assertRaises(SimulationError):
            load_series('USD/BOB', 'competencia')


class SimulatePathsTest(TestCase):
    def setUp(self):
        _seed_series()
        self.series = load_series('USD/BOB', 'web')

    def test_bootstrap_bandas_coherentes(self):
        r = simulate_paths(self.series, horizon_days=30, n_paths=500, seed=1)
        self.assertEqual(len(r['bands']['p50']), 30)
        # las bandas deben estar ordenadas p5 <= p50 <= p95 en todos los días
        for d in range(30):
            self.assertLessEqual(r['bands']['p5'][d], r['bands']['p50'][d])
            self.assertLessEqual(r['bands']['p50'][d], r['bands']['p95'][d])
        fd = r['final_distribution']
        self.assertLessEqual(fd['p5'], fd['p95'])
        self.assertGreater(fd['mean'], 0)

    def test_gbm_reproducible_con_seed(self):
        a = simulate_paths(self.series, horizon_days=10, n_paths=300,
                           method='gbm', seed=42)
        b = simulate_paths(self.series, horizon_days=10, n_paths=300,
                           method='gbm', seed=42)
        self.assertEqual(a['bands']['p50'], b['bands']['p50'])

    def test_shock_devaluacion_desplaza_distribucion(self):
        base  = simulate_paths(self.series, horizon_days=5, n_paths=1000, seed=3)
        shock = simulate_paths(self.series, horizon_days=5, n_paths=1000,
                               seed=3, shock_pct=15)
        # un shock +15% el día 1 debe subir la mediana final ~15%
        ratio = shock['final_distribution']['p50'] / base['final_distribution']['p50']
        self.assertAlmostEqual(ratio, 1.15, delta=0.02)

    def test_parametros_invalidos(self):
        for kwargs in ({'horizon_days': 0}, {'n_paths': 50},
                       {'method': 'magia'}, {'shock_pct': 500}):
            with self.assertRaises(SimulationError):
                simulate_paths(self.series, **kwargs)


class PositionVarTest(TestCase):
    def setUp(self):
        _seed_series()
        self.series = load_series('USD/BOB', 'web')
        self.sim = simulate_paths(self.series, horizon_days=30,
                                  n_paths=2000, seed=5)

    def test_var_positivo_y_es_mayor(self):
        r = position_var(self.sim, position_amount=10_000, confidence=0.95)
        self.assertGreaterEqual(r['var_bob'], 0)
        # ES captura la cola más allá del VaR → siempre >= VaR
        self.assertGreaterEqual(r['expected_shortfall_bob'], r['var_bob'])
        self.assertEqual(r['position_amount'], 10_000)
        self.assertGreater(r['valuation_bob'], 0)

    def test_posicion_cero(self):
        r = position_var(self.sim, position_amount=0)
        self.assertEqual(r['var_bob'], 0)

    def test_posicion_negativa_lanza(self):
        with self.assertRaises(SimulationError):
            position_var(self.sim, position_amount=-5)
