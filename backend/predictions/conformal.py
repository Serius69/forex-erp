"""Predicción conformal: intervalos de pronóstico con cobertura garantizada.

Problema que resuelve: el CI del ensemble era la unión de los CIs de los
modelos base con ``confidence: 0.95`` fijado a mano — sin ninguna garantía de
que el 95 % fuera real. Split conformal usa los residuos históricos reales
(``actual − predicho``) para construir intervalos con garantía de cobertura
*libre de distribución*: si se piden 95 %, la cobertura empírica es ≥ 95 %
(con corrección de muestra finita), sin asumir normalidad de los errores FX.

Módulo puro (numpy + stdlib, sin Django) para poder testearse aislado; el
acceso a la tabla ``Prediction`` vive en ``EnsembleForecaster.conformalize``.

Referencia: Vovk et al., *Algorithmic Learning in a Random World*;
Romano et al. (2019) para la variante asimétrica por colas.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np


__all__ = [
    "ConformalCalibrator",
    "conformal_quantile",
    "calibrate_predictions",
    "coverage_report",
    "interval_score",
    "interval_calibration_report",
    "backtest_point_forecasts",
]

# Mínimo de residuos para que el intervalo conformal sea informativo.
MIN_CALIBRATION_SAMPLES = 30

# Holgura de muestra finita al juzgar si la cobertura empírica cumple lo nominal.
# Con n moderado la cobertura fluctúa; un déficit menor a esta tolerancia (en
# puntos de proporción) no se considera miscalibración real.
COVERAGE_TOLERANCE = 0.05


def conformal_quantile(scores: Sequence | np.ndarray, alpha: float) -> float | None:
    """Cuantíl conformal de nivel ``1 − alpha`` con corrección de muestra finita.

    Devuelve el ``⌈(n+1)(1−α)⌉``-ésimo score más pequeño, o ``None`` si ``n``
    es insuficiente para ese nivel (el intervalo sería infinito).
    """
    s = np.sort(np.asarray(scores, dtype=float).ravel())
    n = s.size
    if n == 0 or not 0.0 < alpha < 1.0:
        return None
    k = math.ceil((n + 1) * (1.0 - alpha))
    if k > n:
        return None  # n demasiado chico para garantizar 1−α
    return float(s[k - 1])


class ConformalCalibrator:
    """Calibrador split-conformal asimétrico sobre residuos históricos.

    Usa las dos colas de los residuos firmados (``actual − predicho``) por
    separado, de modo que un modelo que sesga sistemáticamente hacia arriba o
    abajo obtiene intervalos asimétricos correctos (los errores FX rara vez
    son simétricos).
    """

    def __init__(self) -> None:
        self._residuals: np.ndarray | None = None

    @property
    def n(self) -> int:
        return 0 if self._residuals is None else int(self._residuals.size)

    @property
    def is_fitted(self) -> bool:
        return self._residuals is not None

    def fit(self, y_true: Sequence | np.ndarray, y_pred: Sequence | np.ndarray) -> ConformalCalibrator:
        yt = np.asarray(y_true, dtype=float).ravel()
        yp = np.asarray(y_pred, dtype=float).ravel()
        if yt.shape != yp.shape:
            raise ValueError(f"y_true y y_pred deben tener la misma forma: {yt.shape} vs {yp.shape}")
        if yt.size == 0:
            raise ValueError("No hay residuos para calibrar")
        self._residuals = yt - yp
        return self

    def fit_residuals(self, residuals: Sequence | np.ndarray) -> ConformalCalibrator:
        r = np.asarray(residuals, dtype=float).ravel()
        if r.size == 0:
            raise ValueError("No hay residuos para calibrar")
        self._residuals = r
        return self

    def interval(self, point: float, alpha: float = 0.05, scale: float = 1.0) -> tuple[float, float] | None:
        """Intervalo ``[lo, hi]`` de cobertura ``1 − alpha`` alrededor del punto.

        Cada cola se corrige a nivel ``α/2``. Devuelve ``None`` si no hay
        residuos suficientes para garantizar el nivel pedido.

        ``scale`` (≥ 0) multiplica el ancho de ambas colas: los residuos de
        calibración provienen de un horizonte fijo (24 h en el ensemble), pero el
        error de pronóstico crece con el horizonte. Escalar el cuantil base por
        ``sqrt(h/24)`` (random-walk) da intervalos que se ensanchan con el paso
        adelante en vez de aplicar el mismo ancho de 24 h a 168 h. ``scale=1.0``
        (default) conserva el comportamiento original.
        """
        if self._residuals is None:
            raise RuntimeError("ConformalCalibrator no ajustado — llama a fit() primero")
        r = self._residuals
        # Cola superior: cuantil conformal de r; cola inferior: de −r.
        up = conformal_quantile(r, alpha / 2.0)
        lo = conformal_quantile(-r, alpha / 2.0)
        if up is None or lo is None:
            return None
        return float(point - lo * scale), float(point + up * scale)

    def to_dict(self) -> dict[str, Any]:
        if self._residuals is None:
            raise RuntimeError("ConformalCalibrator no ajustado")
        return {"type": "split_conformal", "residuals": self._residuals.tolist()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConformalCalibrator:
        return cls().fit_residuals(data["residuals"])


def calibrate_predictions(
    predictions: list[dict],
    residuals: Sequence | np.ndarray,
    *,
    alpha: float = 0.05,
    min_samples: int = MIN_CALIBRATION_SAMPLES,
    horizon_scale: Sequence[float] | None = None,
) -> list[dict]:
    """Reemplaza ``lower``/``upper``/``confidence`` de cada predicción del
    ensemble por el intervalo conformal calibrado con los residuos históricos.

    Si no hay residuos suficientes (``< min_samples``) devuelve las
    predicciones sin tocar (el CI heurístico original se conserva) — nunca
    degrada el resultado por falta de datos. Marca la procedencia en
    ``external_factors['interval_method']``.

    ``horizon_scale`` (opcional, un factor por predicción) ensancha el intervalo
    con el horizonte: los residuos de calibración son de un solo horizonte (24 h),
    así que sin escalar todos los pasos —1 h … 168 h— recibirían el mismo ancho y
    los horizontes largos quedarían sub-cubiertos. Con ``None`` (default) el
    comportamiento es el original (factor 1.0 en todos los pasos).
    """
    r = np.asarray(residuals, dtype=float).ravel()
    if r.size < min_samples:
        return predictions

    cal = ConformalCalibrator().fit_residuals(r)
    out: list[dict] = []
    for i, pred in enumerate(predictions):
        scale = 1.0 if horizon_scale is None else float(horizon_scale[i])
        interval = cal.interval(float(pred["rate"]), alpha, scale=scale)
        if interval is None:
            out.append(pred)
            continue
        updated = dict(pred)
        updated["lower"], updated["upper"] = interval
        updated["confidence"] = round(1.0 - alpha, 4)
        factors = dict(updated.get("external_factors") or {})
        factors["interval_method"] = "split_conformal"
        factors["calibration_n"] = cal.n
        if horizon_scale is not None:
            factors["horizon_scale"] = round(scale, 4)
        updated["external_factors"] = factors
        out.append(updated)
    return out


def coverage_report(
    y_true: Sequence | np.ndarray,
    lower: Sequence | np.ndarray,
    upper: Sequence | np.ndarray,
) -> dict[str, float | int]:
    """Cobertura empírica de los intervalos: ¿el 95 % nominal es real?"""
    yt = np.asarray(y_true, dtype=float).ravel()
    lo = np.asarray(lower, dtype=float).ravel()
    up = np.asarray(upper, dtype=float).ravel()
    if not (yt.shape == lo.shape == up.shape):
        raise ValueError("y_true, lower y upper deben tener la misma forma")
    if yt.size == 0:
        raise ValueError("Series vacías")
    inside = (yt >= lo) & (yt <= up)
    return {
        "n": int(yt.size),
        "coverage": round(float(inside.mean()), 4),
        "avg_width": round(float(np.mean(up - lo)), 6),
    }


def interval_score(
    y_true: Sequence | np.ndarray,
    lower: Sequence | np.ndarray,
    upper: Sequence | np.ndarray,
    alpha: float,
) -> float:
    """Winkler / interval score medio de intervalos ``(1 − alpha)`` (menor = mejor).

    La cobertura por sí sola es *engañable*: un intervalo infinitamente ancho
    cubre el 100 %. El interval score (Gneiting & Raftery, 2007) es una regla de
    puntuación *propia* que premia intervalos angostos y penaliza cada
    observación fuera del intervalo proporcionalmente a su distancia y a
    ``2/alpha`` (cuanto más alto el nivel nominal, más caro fallar)::

        S = (u − l) + (2/α)·(l − y)·1{y < l} + (2/α)·(y − u)·1{y > u}

    Es el complemento honesto de :func:`coverage_report`: un modelo solo puede
    bajar el score si sus intervalos son *estrechos y* bien calibrados a la vez.
    """
    yt = np.asarray(y_true, dtype=float).ravel()
    lo = np.asarray(lower, dtype=float).ravel()
    up = np.asarray(upper, dtype=float).ravel()
    if not (yt.shape == lo.shape == up.shape):
        raise ValueError("y_true, lower y upper deben tener la misma forma")
    if yt.size == 0:
        raise ValueError("Series vacías")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha fuera de (0, 1): {alpha}")

    width      = up - lo
    below      = np.maximum(0.0, lo - yt)   # cuánto quedó y por debajo del piso
    above      = np.maximum(0.0, yt - up)   # cuánto quedó y por encima del techo
    penalty    = (2.0 / alpha) * (below + above)
    return round(float(np.mean(width + penalty)), 6)


def interval_calibration_report(
    y_true: Sequence | np.ndarray,
    lower: Sequence | np.ndarray,
    upper: Sequence | np.ndarray,
    *,
    nominal: float = 0.95,
    tol: float = COVERAGE_TOLERANCE,
) -> dict[str, float | int | bool]:
    """Diagnóstico de calibración de intervalos para monitoreo continuo.

    Reúne en un solo dict: cobertura empírica, ancho medio, Winkler score y la
    *brecha de calibración* firmada (``cobertura − nominal``). Marca
    ``undercovered=True`` cuando la cobertura cae más de ``tol`` por debajo del
    nivel prometido — señal de que la garantía conformal se rompió y hay que
    recalibrar (residuos obsoletos, régimen de mercado cambiado, etc.).
    """
    if not 0.0 < nominal < 1.0:
        raise ValueError(f"nominal fuera de (0, 1): {nominal}")

    cov = coverage_report(y_true, lower, upper)
    alpha = 1.0 - nominal
    gap = round(cov["coverage"] - nominal, 4)
    return {
        "n":               cov["n"],
        "nominal":         round(nominal, 4),
        "coverage":        cov["coverage"],
        "calibration_gap": gap,                       # <0 = sub-cobertura
        "avg_width":       cov["avg_width"],
        "interval_score":  interval_score(y_true, lower, upper, alpha),
        "undercovered":    bool(cov["coverage"] < nominal - tol),
    }


def backtest_point_forecasts(
    y_true: Sequence | np.ndarray,
    y_pred: Sequence | np.ndarray,
) -> dict[str, float | int]:
    """Backtest de pronósticos puntuales sobre pares (real, predicho) en orden
    cronológico: MAE, RMSE, MAPE, sesgo medio y precisión direccional
    (¿acertó la *dirección* del movimiento vs. el valor real anterior?).
    """
    yt = np.asarray(y_true, dtype=float).ravel()
    yp = np.asarray(y_pred, dtype=float).ravel()
    if yt.shape != yp.shape:
        raise ValueError(f"y_true y y_pred deben tener la misma forma: {yt.shape} vs {yp.shape}")
    if yt.size == 0:
        raise ValueError("Series vacías")

    err = yp - yt
    denom = np.where(yt != 0, yt, 1.0)
    metrics: dict[str, float | int] = {
        "n": int(yt.size),
        "mae": round(float(np.mean(np.abs(err))), 6),
        "rmse": round(float(np.sqrt(np.mean(err**2))), 6),
        "mape_pct": round(float(np.mean(np.abs(err / denom))) * 100.0, 4),
        "bias": round(float(np.mean(err)), 6),  # >0 = sobre-predice sistemáticamente
    }
    if yt.size >= 2:
        actual_dir = np.sign(np.diff(yt))
        pred_dir = np.sign(yp[1:] - yt[:-1])
        moved = actual_dir != 0  # los empates no cuentan
        if moved.any():
            metrics["directional_accuracy"] = round(
                float((actual_dir[moved] == pred_dir[moved]).mean()), 4
            )
    return metrics
