"""Tests que congelan los fixes de CONFIABILIDAD de la auditoría ML.

R1 — Frescura de datos por granularidad de serie (predictions/monitoring.py):
     una serie de cierre DIARIO ('competencia'/'empresa') con datos de <30h NO debe
     marcarse stale, pero la serie de tiempo real ('web') con >6h SÍ. Antes un umbral
     único de 4h disparaba DATA_STALE constante en las series diarias (fatiga → se
     perdía la señal real).

R2 — Ancho del intervalo conformal creciente con el horizonte
     (predictions/ensemble_forecaster.py + conformal.py): los residuos de calibración
     son de horizonte 24h, así que el intervalo se escala por sqrt(h/24) y el CI a 7d
     (168h) debe ser MÁS ANCHO que a 24h, en vez de recibir el mismo ancho de 24h.
"""
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from predictions.models import PredictionModel, Prediction, TrainingData
from predictions.monitoring import (
    ModelMonitor,
    DATA_STALENESS_THRESHOLDS_BY_MARKET,
)
from predictions.ensemble_forecaster import EnsembleForecaster

PAIR = 'USD/BOB'


class DataFreshnessByGranularityTests(TestCase):
    """R1 — el umbral de frescura depende de la granularidad de la serie."""

    def _seed_point(self, market, hours_ago, rate='6.90'):
        TrainingData.objects.create(
            currency_pair=PAIR, market=market,
            date=timezone.now() - timedelta(hours=hours_ago),
            rate=Decimal(rate), source='TEST',
        )

    def test_daily_series_under_30h_is_fresh(self):
        # 'competencia' es cierre DIARIO: 28h de antigüedad es NORMAL, no stale.
        self._seed_point('competencia', hours_ago=28)
        res = ModelMonitor()._data_freshness(PAIR, market='competencia')
        self.assertTrue(res['fresh'],
                        "serie diaria con 28h NO debe marcarse stale (umbral ~30h)")
        self.assertEqual(res['threshold_hours'],
                         DATA_STALENESS_THRESHOLDS_BY_MARKET['competencia'])

    def test_empresa_series_under_30h_is_fresh(self):
        self._seed_point('empresa', hours_ago=25)
        res = ModelMonitor()._data_freshness(PAIR, market='empresa')
        self.assertTrue(res['fresh'])
        self.assertEqual(res['threshold_hours'], 30)

    def test_realtime_web_series_over_6h_is_stale(self):
        # 'web' es tiempo real / horaria: 8h sin refrescar SÍ es señal de alerta.
        self._seed_point('web', hours_ago=8)
        res = ModelMonitor()._data_freshness(PAIR, market='web')
        self.assertFalse(res['fresh'],
                         "serie de tiempo real con 8h SÍ debe marcarse stale (umbral 6h)")
        self.assertEqual(res['threshold_hours'], 6)

    def test_web_fresh_under_6h(self):
        self._seed_point('web', hours_ago=2)
        res = ModelMonitor()._data_freshness(PAIR, market='web')
        self.assertTrue(res['fresh'])

    def test_same_age_classified_opposite_by_series(self):
        """El mismo 'hours_old' (~20h) es fresh para diaria y stale para web:
        prueba directa de que el umbral es POR granularidad, no global."""
        self._seed_point('competencia', hours_ago=20)
        self._seed_point('web', hours_ago=20)
        self.assertTrue(ModelMonitor()._data_freshness(PAIR, market='competencia')['fresh'])
        self.assertFalse(ModelMonitor()._data_freshness(PAIR, market='web')['fresh'])


class ConformalHorizonScalingTests(TestCase):
    """R2 — el intervalo conformal se ensancha con el horizonte."""

    N_RESIDUALS = 60   # > 39 → alpha/2=0.025 tiene cuantil finito; > MIN_CALIBRATION_SAMPLES

    def _seed_ensemble_residuals(self, market='web'):
        pm = PredictionModel.objects.create(
            name=f'ENSEMBLE {PAIR}', model_type='ENSEMBLE',
            currency_pair=PAIR, market=market, is_active=True,
        )
        now = timezone.now()
        # Residuos (actual - predicho) repartidos en [-0.05, 0.05]: cuantiles no triviales.
        for i in range(self.N_RESIDUALS):
            resid = (i - self.N_RESIDUALS / 2) * (0.10 / self.N_RESIDUALS)
            predicted = Decimal('6.9000')
            actual = predicted + Decimal(str(round(resid, 4)))
            Prediction.objects.create(
                model=pm, currency_pair=PAIR,
                prediction_date=now - timedelta(days=i + 1),
                predicted_rate=predicted,
                predicted_buy_rate=predicted, predicted_sell_rate=predicted,
                confidence_lower=predicted - Decimal('0.02'),
                confidence_upper=predicted + Decimal('0.02'),
                actual_rate=actual, error_percentage=abs(float(resid)) / 6.9 * 100,
            )
        return pm

    def test_7d_interval_wider_than_24h(self):
        self._seed_ensemble_residuals(market='web')
        now = timezone.now()
        preds = [
            {'prediction_date': now + timedelta(hours=24),  'rate': 6.90,
             'lower': 6.88, 'upper': 6.92, 'external_factors': {'model': 'ENSEMBLE'}},
            {'prediction_date': now + timedelta(hours=168), 'rate': 6.90,
             'lower': 6.88, 'upper': 6.92, 'external_factors': {'model': 'ENSEMBLE'}},
        ]
        ens = EnsembleForecaster(tempfile.gettempdir())
        out = ens.conformalize(preds, PAIR, market='web')

        # La calibración debe haberse aplicado (marca de procedencia).
        self.assertEqual(out[0]['external_factors'].get('interval_method'),
                         'split_conformal',
                         "con suficientes residuos la conformalización debe aplicarse")

        width_24h = out[0]['upper'] - out[0]['lower']
        width_7d = out[1]['upper'] - out[1]['lower']
        self.assertGreater(width_7d, width_24h,
                           "el intervalo a 7d (168h) debe ser MÁS ANCHO que a 24h")
        # Escala esperada ~ sqrt(168/24) = sqrt(7) ≈ 2.65 sobre el ancho de 24h.
        self.assertAlmostEqual(width_7d / width_24h, 7 ** 0.5, delta=0.15)

    def test_horizon_scale_recorded_in_factors(self):
        self._seed_ensemble_residuals(market='web')
        now = timezone.now()
        preds = [
            {'prediction_date': now + timedelta(hours=168), 'rate': 6.90,
             'lower': 6.88, 'upper': 6.92, 'external_factors': {'model': 'ENSEMBLE'}},
        ]
        out = EnsembleForecaster(tempfile.gettempdir()).conformalize(preds, PAIR, market='web')
        self.assertGreater(out[0]['external_factors'].get('horizon_scale', 0), 1.0)
