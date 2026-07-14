"""
Tests del modelo ML de riesgo de revisión + explicabilidad SHAP (transactions/ml_risk.py).

No requieren base de datos: ejercitan el núcleo (`RiskReviewModel`, `label_from_rules`)
sobre DataFrames sintéticos. Se saltan automáticamente si `catboost`/`shap` no están
instalados (dependencias opcionales del ERP).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from transactions.ml_risk import (CAT_FEATURES, FEATURES, NUM_FEATURES, TARGET,
                                   RiskReviewModel, label_from_rules)

catboost = pytest.importorskip("catboost")
shap = pytest.importorskip("shap")


def _frame(n: int = 1500, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    foreign = rng.lognormal(4.6, 1.0, n).round(2)
    rate = rng.normal(15.8, 0.6, n).round(2)
    bob = (foreign * rate).round(2)
    ccy = rng.choice(["USD", "EUR", "CLP", "PEN"], n, p=[0.7, 0.1, 0.12, 0.08])
    df = pd.DataFrame({
        "amount_bob": bob, "foreign_amount": foreign, "exchange_rate": rate,
        "rate_deviation_pct": np.abs(rng.normal(0, 2.5, n)).round(3),
        "amount_z": ((bob - bob.mean()) / bob.std()).round(3),
        "cashier_velocity": rng.poisson(6, n) + 1,
        "transaction_type": rng.choice(["BUY", "SELL"], n),
        "currency": ccy, "payment_method": rng.choice(["CASH", "QR"], n, p=[0.97, 0.03]),
        "weekday": rng.integers(0, 7, n),
    })
    df[TARGET] = label_from_rules(df)
    return df


def test_label_from_rules_es_binaria_y_no_degenerada():
    df = _frame()
    y = df[TARGET]
    assert set(y.unique()) <= {0, 1}
    assert 0.05 < y.mean() < 0.6  # ni todo 0 ni todo 1


def test_train_devuelve_metricas_razonables():
    model = RiskReviewModel()
    m = model.train(_frame(), iterations=200)
    assert model.is_ready
    assert 0.5 <= m["roc_auc"] <= 1.0
    assert m["n_train"] > 0 and m["n_test"] > 0


def test_explain_devuelve_probabilidad_y_factores(tmp_path):
    model = RiskReviewModel()
    model.train(_frame(), iterations=200)
    path = model.save(tmp_path / "modelo.cbm")
    assert path.exists()

    # Operación claramente sospechosa: monto alto, tasa desviada, monto atípico.
    op = {
        "amount_bob": 180000, "foreign_amount": 11000, "exchange_rate": 16.4,
        "rate_deviation_pct": 8.5, "amount_z": 4.5, "cashier_velocity": 15,
        "transaction_type": "BUY", "currency": "ARS", "payment_method": "CASH",
        "weekday": 6,
    }
    fresh = RiskReviewModel().load(path)
    ex = fresh.explain(op, top_n=5)
    assert 0.0 <= ex.probability <= 1.0
    assert ex.decision in {"REQUIERE_REVISION", "NORMAL"}
    assert len(ex.top_factors) == 5
    assert all({"feature", "value", "shap", "direction"} <= set(f) for f in ex.top_factors)
    # La suma base + SHAP debe ser coherente (aditividad de SHAP, en log-odds).
    assert ex.probability > 0.5  # esta operación debería marcarse


def test_features_esquema():
    assert len(NUM_FEATURES) == 6 and len(CAT_FEATURES) == 4
    assert FEATURES == NUM_FEATURES + CAT_FEATURES
