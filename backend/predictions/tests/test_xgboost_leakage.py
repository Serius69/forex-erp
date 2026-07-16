"""A3 — Tests que congelan la ausencia de data leakage en XGBoost.

El bug: features en la fila t + target = rate[t] de la MISMA fila. Como los
technicals (ma/ema/rsi/bb/volatility...) se calculan con ventanas que terminan
en t (incluyen rate[t]), el modelo aprendía la identidad ma≈rate → MAPE
artificialmente bajo → XGBoost sobre-ponderado. El fix desplaza el target a
rate[t+1] (build_supervised). No requiere xgboost instalado: prueba la
construcción supervisada, que es donde vivía la fuga.
"""
import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from predictions.xgboost_forecaster import build_supervised


def _synthetic_df(n=60):
    idx = pd.date_range('2026-01-01', periods=n, freq='h', tz='UTC')
    rate = pd.Series(np.linspace(6.90, 7.20, n), index=idx)
    df = pd.DataFrame({'rate': rate}, index=idx)
    # Technicals causales que TERMINAN en t (incluyen rate[t]) — reproducen el
    # patrón del pipeline que originaba la fuga.
    df['ma_7'] = rate.rolling(7, min_periods=1).mean()
    df['ma_30'] = rate.rolling(30, min_periods=1).mean()
    df['lag_1'] = rate.shift(1)
    return df


class XGBoostNoLeakageTests(SimpleTestCase):

    def test_target_is_next_step_not_contemporaneous(self):
        """El target de la fila t debe ser rate[t+1], nunca rate[t]."""
        df = _synthetic_df()
        features = ['ma_7', 'ma_30', 'lag_1']
        X, y, data = build_supervised(df, features)

        # Para cada fila alineada, target == rate del SIGUIENTE timestamp.
        rate = df['rate']
        for ts, target in zip(data.index, y):
            pos = rate.index.get_loc(ts)
            self.assertLess(pos + 1, len(rate),
                            "no debería quedar la última fila (sin t+1)")
            self.assertAlmostEqual(
                float(target), float(rate.iloc[pos + 1]), places=5,
                msg="target debe ser rate[t+1] (causal, sin fuga)")
            # Y NO el rate contemporáneo (salvo coincidencia numérica improbable).
            self.assertNotAlmostEqual(
                float(target), float(rate.iloc[pos]), places=5,
                msg="target NO debe ser rate[t] (eso era la fuga)")

    def test_features_do_not_include_future_target_column(self):
        """La matriz X no contiene la columna 'target' ni 'rate' contemporáneo."""
        df = _synthetic_df()
        features = ['ma_7', 'ma_30', 'lag_1']
        _, _, data = build_supervised(df, features)
        self.assertNotIn('rate', features)
        self.assertIn('target', data.columns)
        # X se construye SOLO desde `features`; 'target' queda fuera de X.
        self.assertEqual(list(features), ['ma_7', 'ma_30', 'lag_1'])

    def test_last_row_dropped(self):
        """La última fila (sin rate[t+1]) se descarta — no se inventa target."""
        df = _synthetic_df(n=40)
        X, y, data = build_supervised(df, ['ma_7', 'lag_1'])
        self.assertNotIn(df.index[-1], data.index)
        self.assertEqual(len(X), len(y))
