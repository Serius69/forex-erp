"""Tests de predicción conformal: cuantiles, intervalos, calibración y backtest.

Puros (sin DB/Django models). Ejecutar desde backend/:
    python -m pytest predictions/test_conformal.py -o addopts="" -p no:django
"""
from __future__ import annotations

import numpy as np
import pytest

from predictions.conformal import (
    ConformalCalibrator,
    backtest_point_forecasts,
    calibrate_predictions,
    conformal_quantile,
    coverage_report,
    interval_calibration_report,
    interval_score,
)


def test_conformal_quantile_finite_sample() -> None:
    scores = list(range(1, 100))  # 1..99
    # n=99, alpha=0.05 → k = ceil(100*0.95) = 95 → 95º más chico = 95
    assert conformal_quantile(scores, 0.05) == 95.0
    # n insuficiente para el nivel pedido → None
    assert conformal_quantile([1.0, 2.0], 0.05) is None
    assert conformal_quantile([], 0.05) is None


def test_interval_has_guaranteed_coverage() -> None:
    """Propiedad central: cobertura empírica >= 1−alpha en datos intercambiables."""
    rng = np.random.default_rng(42)
    residuals = rng.standard_t(df=3, size=500) * 0.02  # colas pesadas tipo FX
    cal = ConformalCalibrator().fit_residuals(residuals[:250])

    fresh = residuals[250:]
    lo, hi = cal.interval(0.0, alpha=0.10)
    coverage = float(np.mean((fresh >= lo) & (fresh <= hi)))
    assert coverage >= 0.90 - 0.03  # margen muestral


def test_interval_is_asymmetric_for_biased_model() -> None:
    # Modelo que sub-predice: residuos (actual − pred) mayormente positivos.
    residuals = np.concatenate([np.full(90, 0.05), np.full(10, -0.01)])
    cal = ConformalCalibrator().fit_residuals(residuals)
    lo, hi = cal.interval(6.96, alpha=0.10)
    assert (hi - 6.96) > (6.96 - lo)  # más margen hacia arriba
    assert lo < 6.96 < hi


def test_calibrate_predictions_rewrites_ci() -> None:
    preds = [
        {"prediction_date": None, "rate": 6.96, "lower": 6.90, "upper": 7.00,
         "confidence": 0.95, "external_factors": {"model": "ENSEMBLE"}},
    ]
    residuals = np.random.default_rng(7).normal(0, 0.01, 200)
    out = calibrate_predictions(preds, residuals, alpha=0.05)

    assert out is not preds
    p = out[0]
    assert p["lower"] < 6.96 < p["upper"]
    assert p["confidence"] == 0.95
    assert p["external_factors"]["interval_method"] == "split_conformal"
    assert p["external_factors"]["calibration_n"] == 200
    assert p["external_factors"]["model"] == "ENSEMBLE"  # no pisa lo existente
    assert preds[0]["lower"] == 6.90  # el original no se muta


def test_calibrate_predictions_insufficient_data_is_noop() -> None:
    preds = [{"rate": 6.96, "lower": 6.90, "upper": 7.00, "confidence": 0.95}]
    out = calibrate_predictions(preds, [0.01] * 5, alpha=0.05)
    assert out is preds  # intactas, mismo objeto


def test_coverage_report() -> None:
    rep = coverage_report([1.0, 2.0, 3.0, 10.0], [0.5, 1.5, 2.5, 3.0], [1.5, 2.5, 3.5, 4.0])
    assert rep["n"] == 4
    assert rep["coverage"] == pytest.approx(0.75)  # 10.0 fuera
    assert rep["avg_width"] == pytest.approx(1.0)


def test_interval_score_no_penalty_when_inside() -> None:
    # Todas las observaciones dentro → score = ancho medio, sin penalización.
    s = interval_score([1.0, 2.0, 3.0], [0.0, 1.0, 2.0], [2.0, 3.0, 4.0], alpha=0.10)
    assert s == pytest.approx(2.0)


def test_interval_score_penalizes_misses_scaled_by_alpha() -> None:
    # y=5 fuera de [0,2]: penalización = (2/α)·(5−2) sumada al ancho (2).
    assert interval_score([5.0], [0.0], [2.0], alpha=0.10) == pytest.approx(2 + 60.0)
    # α mayor (menos confianza) penaliza menos el mismo fallo.
    assert interval_score([5.0], [0.0], [2.0], alpha=0.20) == pytest.approx(2 + 30.0)


def test_interval_score_rewards_sharpness() -> None:
    # Con la misma cobertura (ambos cubren y=1), el intervalo más angosto gana.
    tight = interval_score([1.0], [0.5], [1.5], alpha=0.10)
    wide  = interval_score([1.0], [0.0], [2.0], alpha=0.10)
    assert tight < wide


def test_interval_score_validation() -> None:
    with pytest.raises(ValueError):
        interval_score([], [], [], alpha=0.1)
    with pytest.raises(ValueError):
        interval_score([1.0], [0.0], [2.0], alpha=0.0)
    with pytest.raises(ValueError):
        interval_score([1.0], [0.0], [2.0, 3.0], alpha=0.1)


def test_interval_calibration_report_well_calibrated() -> None:
    rep = interval_calibration_report(
        [1.0, 2.0, 3.0, 4.0], [0.0, 1.0, 2.0, 3.0], [2.0, 3.0, 4.0, 5.0], nominal=0.95
    )
    assert rep["coverage"] == pytest.approx(1.0)
    assert rep["calibration_gap"] == pytest.approx(0.05)
    assert rep["undercovered"] is False
    assert rep["avg_width"] == pytest.approx(2.0)


def test_interval_calibration_report_detects_undercoverage() -> None:
    # 10 puntos, solo 5 dentro → cobertura 0.5 << nominal 0.95 → miscalibrado.
    y_true = list(range(10))
    lower  = [v - 0.5 for v in y_true]
    upper  = [v + 0.5 for v in y_true]
    # Sacar 5 observaciones fuera de su intervalo desplazándolas.
    y_true = [v if i % 2 == 0 else v + 5 for i, v in enumerate(y_true)]
    rep = interval_calibration_report(y_true, lower, upper, nominal=0.95)
    assert rep["coverage"] == pytest.approx(0.5)
    assert rep["calibration_gap"] < 0
    assert rep["undercovered"] is True


def test_interval_calibration_report_validation() -> None:
    with pytest.raises(ValueError):
        interval_calibration_report([1.0], [0.0], [2.0], nominal=1.5)


def test_backtest_point_forecasts() -> None:
    y_true = [6.90, 6.95, 6.92, 7.00]
    y_pred = [6.92, 6.94, 6.95, 6.98]
    m = backtest_point_forecasts(y_true, y_pred)
    assert m["n"] == 4
    assert m["mae"] == pytest.approx(0.02, abs=1e-9)
    assert m["bias"] == pytest.approx(0.005, abs=1e-9)
    # Direcciones reales: +,−,+ ; predichas vs actual previo: +,±0→0,+ → 2/3
    assert m["directional_accuracy"] == pytest.approx(2 / 3, abs=1e-3)


def test_validation_errors() -> None:
    with pytest.raises(RuntimeError):
        ConformalCalibrator().interval(1.0)
    with pytest.raises(ValueError):
        ConformalCalibrator().fit([1, 2], [1, 2, 3])
    with pytest.raises(ValueError):
        backtest_point_forecasts([], [])
    with pytest.raises(ValueError):
        coverage_report([1], [0], [2, 3])


def test_calibrator_serialization_roundtrip() -> None:
    cal = ConformalCalibrator().fit_residuals(np.linspace(-0.05, 0.05, 100))
    restored = ConformalCalibrator.from_dict(cal.to_dict())
    assert restored.interval(6.96, 0.10) == pytest.approx(cal.interval(6.96, 0.10))
