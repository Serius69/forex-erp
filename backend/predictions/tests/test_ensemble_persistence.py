"""A2 — Tests que congelan la persistencia de predicciones de modelos BASE.

Bug: _persist_ensemble_predictions solo guardaba filas del modelo ENSEMBLE, así
que evaluate_predictions nunca poblaba actual_rate de XGBOOST/ARIMA/BILSTM/PROPHET
→ compute_weights caía siempre al _fallback_weight (pesos inertes) y
train_meta_learner no hallaba filas por model_type.

Estos tests verifican que:
  1. _persist_ensemble_predictions crea filas Prediction por CADA modelo base
     (con su model_type), no solo ENSEMBLE.
  2. Con esas filas evaluadas (actual_rate + error_percentage), compute_weights
     usa el MAPE reciente REAL por model_type en vez del fallback.
"""
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from predictions.models import PredictionModel, Prediction
from predictions.ensemble_forecaster import EnsembleForecaster
from predictions.tasks import _persist_ensemble_predictions

PAIR = 'USD/BOB'
MARKET = 'web'


class _FakeEngine:
    """Engine mínimo: reproduce el contrato de engine.predict() que consume
    _persist_ensemble_predictions (dict con 'predictions' + 'components')."""

    def predict(self, pair, horizon_key='24h', use_cache=True, market='web'):
        now = timezone.now()
        preds = []
        for i in range(3):
            preds.append({
                'datetime': now + timedelta(hours=i + 1),
                'rate':  6.90 + 0.01 * i,
                'lower': 6.80,
                'upper': 7.00,
                'components': {
                    'XGBOOST': 6.91 + 0.01 * i,
                    'ARIMA':   6.89 + 0.01 * i,
                },
            })
        return {'predictions': preds}


class EnsembleBasePersistenceTests(TestCase):

    def _seed_models(self):
        for mt in ('ENSEMBLE', 'XGBOOST', 'ARIMA'):
            PredictionModel.objects.create(
                name=f'{mt} {PAIR}', model_type=mt,
                currency_pair=PAIR, market=MARKET, is_active=True,
            )

    def test_persists_one_row_per_base_model(self):
        self._seed_models()
        _persist_ensemble_predictions(_FakeEngine(), PAIR, MARKET)

        # ENSEMBLE + una fila por cada modelo base presente en components.
        self.assertEqual(
            Prediction.objects.filter(model__model_type='ENSEMBLE',
                                      currency_pair=PAIR).count(), 3)
        self.assertEqual(
            Prediction.objects.filter(model__model_type='XGBOOST',
                                      currency_pair=PAIR).count(), 3,
            "las predicciones base XGBOOST deben persistirse (A2)")
        self.assertEqual(
            Prediction.objects.filter(model__model_type='ARIMA',
                                      currency_pair=PAIR).count(), 3,
            "las predicciones base ARIMA deben persistirse (A2)")

        # El predicted_rate base viene del rate individual de components.
        xgb_first = (Prediction.objects
                     .filter(model__model_type='XGBOOST', currency_pair=PAIR)
                     .order_by('prediction_date').first())
        self.assertAlmostEqual(float(xgb_first.predicted_rate), 6.91, places=2)

    def test_compute_weights_uses_real_mape_per_model_type(self):
        self._seed_models()
        _persist_ensemble_predictions(_FakeEngine(), PAIR, MARKET)

        # Simular evaluate_predictions: poblar actual_rate + error_percentage.
        # XGBOOST más preciso (MAPE 1%) que ARIMA (MAPE 4%).
        for mt, err in (('XGBOOST', 1.0), ('ARIMA', 4.0)):
            (Prediction.objects
             .filter(model__model_type=mt, currency_pair=PAIR)
             .update(actual_rate=Decimal('6.90'), error_percentage=err))

        ens = EnsembleForecaster(tempfile.gettempdir())
        weights = ens.compute_weights(PAIR, market=MARKET)

        # Ambos con peso REAL (1/MAPE), no el fallback; XGBOOST > ARIMA.
        self.assertGreater(weights['XGBOOST'], 0.0)
        self.assertGreater(weights['ARIMA'], 0.0)
        self.assertGreater(weights['XGBOOST'], weights['ARIMA'])
        # PROPHET/BILSTM sin filas ni modelo → fallback 0.0 (no contaminan).
        self.assertEqual(weights['PROPHET'], 0.0)
        self.assertEqual(weights['BILSTM'], 0.0)

    def test_meta_learner_finds_rows_by_model_type(self):
        """train_meta_learner debe encontrar filas por model_type tras el fix
        (aunque falle luego por pocos timestamps comunes, NO por 'sin datos')."""
        self._seed_models()
        _persist_ensemble_predictions(_FakeEngine(), PAIR, MARKET)
        Prediction.objects.filter(currency_pair=PAIR).update(
            actual_rate=Decimal('6.90'))

        ens = EnsembleForecaster(tempfile.gettempdir())
        # Con solo 3 timestamps no alcanza para el split (>=20) → ValueError de
        # "Insuficientes timestamps", NO el "Sin datos suficientes" de filas 0.
        with self.assertRaises(ValueError) as ctx:
            ens.train_meta_learner(PAIR, market=MARKET)
        self.assertIn('timestamps', str(ctx.exception).lower())
