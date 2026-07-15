"""
Simulación estocástica de tasas de cambio calibrada con DATOS REALES.

Antes no existía ningún módulo de simulación en el sistema (cero Monte Carlo,
VaR o stress testing). Este módulo trabaja SIEMPRE sobre la serie diaria real
de TrainingData (la misma que alimenta el forecasting, por par y mercado):

  · `simulate_paths`  — Monte Carlo de N caminos a H días:
       - method='bootstrap': re-muestrea log-retornos diarios REALES
         (captura colas gordas del paralelo boliviano sin asumir normalidad).
       - method='gbm': Movimiento Browniano Geométrico con μ/σ estimados de la
         misma serie real (referencia paramétrica clásica).
  · Escenario de estrés opcional: shock inicial de ±X% (devaluación/apreciación)
    aplicado el día 1 sobre todos los caminos.
  · `position_var` — VaR/Expected Shortfall en BOB de la posición REAL de
    inventario (CurrencyInventory física+digital) frente a la distribución
    simulada de la tasa.

Sin dependencias nuevas: numpy puro.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger('kapitalya.predictions.simulation')

# Límites de servicio (el endpoint es sync — mantener acotado)
MAX_PATHS   = 10_000
MAX_HORIZON = 365
MIN_HISTORY = 60          # días de historia mínima para calibrar
PERCENTILES = (5, 25, 50, 75, 95)


class SimulationError(ValueError):
    """Datos insuficientes o parámetros inválidos."""


@dataclass
class CalibratedSeries:
    """Serie real y sus estadísticos de calibración."""
    pair:        str
    market:      str
    last_rate:   float
    log_returns: np.ndarray   # diarios
    mu_daily:    float
    sigma_daily: float
    n_days:      int
    start:       str
    end:         str


def load_series(currency_pair: str, market: str = 'web',
                lookback_days: int = 730) -> CalibratedSeries:
    """Carga la serie diaria real desde TrainingData y calibra μ/σ."""
    from datetime import timedelta

    from django.utils import timezone

    from predictions.models import TrainingData

    cutoff = timezone.now() - timedelta(days=lookback_days)
    rows = list(
        TrainingData.objects
        .filter(currency_pair=currency_pair, market=market, date__gte=cutoff)
        .order_by('date')
        .values_list('date', 'rate')
    )
    if len(rows) < MIN_HISTORY:
        raise SimulationError(
            f'Historia insuficiente para {currency_pair}/{market}: '
            f'{len(rows)} días (mínimo {MIN_HISTORY})')

    rates = np.array([float(r[1]) for r in rows], dtype=np.float64)
    rates = rates[rates > 0]
    lr = np.diff(np.log(rates))
    # descartar retornos absurdos (>25%/día = error de captura, no mercado)
    lr = lr[np.abs(lr) < 0.25]
    if len(lr) < MIN_HISTORY - 10:
        raise SimulationError('Serie degenerada tras limpieza de retornos')

    return CalibratedSeries(
        pair=currency_pair, market=market,
        last_rate=float(rates[-1]),
        log_returns=lr,
        mu_daily=float(np.mean(lr)),
        sigma_daily=float(np.std(lr, ddof=1)),
        n_days=len(rates),
        start=str(rows[0][0].date()), end=str(rows[-1][0].date()),
    )


def simulate_paths(series: CalibratedSeries,
                   horizon_days: int = 30,
                   n_paths: int = 2000,
                   method: str = 'bootstrap',
                   shock_pct: float = 0.0,
                   seed: int | None = None) -> dict:
    """
    Simula caminos de la tasa y devuelve bandas de percentiles + distribución final.

    shock_pct: estrés aplicado el día 1 (p.ej. 15 = devaluación inicial del 15%).
    """
    horizon_days = int(horizon_days)
    n_paths      = int(n_paths)
    if not (1 <= horizon_days <= MAX_HORIZON):
        raise SimulationError(f'horizon_days fuera de rango [1, {MAX_HORIZON}]')
    if not (100 <= n_paths <= MAX_PATHS):
        raise SimulationError(f'n_paths fuera de rango [100, {MAX_PATHS}]')
    if method not in ('bootstrap', 'gbm'):
        raise SimulationError("method debe ser 'bootstrap' o 'gbm'")
    if abs(shock_pct) > 80:
        raise SimulationError('shock_pct fuera de rango [-80, 80]')

    rng = np.random.default_rng(seed)

    if method == 'bootstrap':
        # Re-muestreo IID de los log-retornos reales
        idx = rng.integers(0, len(series.log_returns), size=(n_paths, horizon_days))
        increments = series.log_returns[idx]
    else:   # gbm
        drift = series.mu_daily - 0.5 * series.sigma_daily ** 2
        increments = drift + series.sigma_daily * rng.standard_normal(
            (n_paths, horizon_days))

    if shock_pct:
        increments[:, 0] += np.log1p(shock_pct / 100.0)

    log_paths = np.cumsum(increments, axis=1)
    paths = series.last_rate * np.exp(log_paths)      # (n_paths, horizon)

    bands = {
        f'p{p}': np.percentile(paths, p, axis=0).round(4).tolist()
        for p in PERCENTILES
    }
    finals = paths[:, -1]

    return {
        'pair':   series.pair,
        'market': series.market,
        'method': method,
        'params': {
            'horizon_days': horizon_days, 'n_paths': n_paths,
            'shock_pct': shock_pct,
            'mu_daily': round(series.mu_daily, 6),
            'sigma_daily': round(series.sigma_daily, 6),
            'sigma_annual_pct': round(series.sigma_daily * np.sqrt(365) * 100, 2),
        },
        'calibration': {
            'n_days': series.n_days, 'from': series.start, 'to': series.end,
            'last_rate': round(series.last_rate, 4),
        },
        'bands': bands,                      # percentiles por día (listas de H)
        'final_distribution': {
            'mean':   round(float(np.mean(finals)), 4),
            'std':    round(float(np.std(finals)), 4),
            'min':    round(float(np.min(finals)), 4),
            'max':    round(float(np.max(finals)), 4),
            **{f'p{p}': round(float(np.percentile(finals, p)), 4)
               for p in PERCENTILES},
            'prob_above_last': round(float(np.mean(finals > series.last_rate)), 4),
        },
        '_finals': finals,   # uso interno (position_var); el view lo elimina
    }


def position_var(sim_result: dict, position_amount: float,
                 confidence: float = 0.95) -> dict:
    """
    VaR y Expected Shortfall (en BOB) de una posición larga de divisa frente a
    la distribución simulada de la tasa al horizonte.

    position_amount: unidades de la divisa en inventario (>0 = posición larga).
    """
    finals = sim_result.get('_finals')
    if finals is None:
        raise SimulationError('sim_result sin distribución final')
    if position_amount < 0:
        raise SimulationError('position_amount debe ser >= 0')

    last = sim_result['calibration']['last_rate']
    pnl = (finals - last) * position_amount        # BOB por camino
    alpha = 1 - confidence
    var = -float(np.percentile(pnl, alpha * 100))  # pérdida (positiva) al 95%
    tail = pnl[pnl <= -var] if var > 0 else pnl[pnl <= np.percentile(pnl, alpha * 100)]
    es = -float(np.mean(tail)) if len(tail) else var

    return {
        'position_amount':    position_amount,
        'valuation_bob':      round(last * position_amount, 2),
        'confidence':         confidence,
        'horizon_days':       sim_result['params']['horizon_days'],
        'var_bob':            round(max(var, 0.0), 2),
        'expected_shortfall_bob': round(max(es, 0.0), 2),
        'pnl_mean_bob':       round(float(np.mean(pnl)), 2),
        'pnl_p5_bob':         round(float(np.percentile(pnl, 5)), 2),
        'pnl_p95_bob':        round(float(np.percentile(pnl, 95)), 2),
    }


def inventory_position(currency_code: str, company=None) -> float:
    """Posición total REAL (física+digital) de una divisa en inventario."""
    from django.db.models import F, Sum

    from inventory.models import CurrencyInventory

    qs = CurrencyInventory.objects.filter(currency__code=currency_code)
    if company is not None:
        qs = qs.filter(branch__company=company)
    total = qs.aggregate(
        t=Sum(F('physical_balance') + F('digital_balance')))['t']
    return float(total or 0)
