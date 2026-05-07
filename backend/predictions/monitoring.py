"""
ModelMonitor — monitoreo continuo de calidad de datos y modelos.

Capacidades:
  - PSI (Population Stability Index): detecta drift en la distribución de tasas
  - Frescura de datos: alerta cuando una fuente deja de actualizar
  - Health score por modelo (0–100)
  - Logging estructurado de cada predicción para auditoría
"""
import numpy as np
import pandas as pd
import logging
from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache

logger = logging.getLogger(__name__)

# PSI thresholds (convención de industria)
PSI_GREEN  = 0.10   # distribución estable
PSI_YELLOW = 0.20   # cambio moderado — vigilar
PSI_RED    = 0.25   # drift significativo — reentrenar

# Alerta si no hay datos nuevos en N horas
DATA_STALENESS_THRESHOLD_HOURS = 4

CURRENCY_PAIRS = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'ARS/BOB', 'PEN/BOB']


class ModelMonitor:
    """
    Detecta drift, verifica frescura de datos y computa health scores.
    Usado por ModelHealthView y la tarea semanal de backtesting.
    """

    # ── API pública ───────────────────────────────────────────────────────────

    def health_report(self) -> dict:
        """Retorna reporte completo de salud para todos los pares y modelos."""
        report = {
            'generated_at': timezone.now().isoformat(),
            'pairs':        {},
            'data_sources': self._check_data_sources(),
        }
        for pair in CURRENCY_PAIRS:
            report['pairs'][pair] = self._pair_health(pair)
        return report

    # ── Salud por par ─────────────────────────────────────────────────────────

    def _pair_health(self, currency_pair: str) -> dict:
        from predictions.models import PredictionModel

        models_health = {}
        for pm in PredictionModel.objects.filter(currency_pair=currency_pair, is_active=True):
            models_health[pm.model_type] = self._model_health(pm)

        psi_result = self._compute_psi(currency_pair)

        overall_scores = [v['health_score'] for v in models_health.values() if 'health_score' in v]
        overall_score  = round(float(np.mean(overall_scores)), 1) if overall_scores else 0.0

        return {
            'overall_health_score': overall_score,
            'models':               models_health,
            'drift':                psi_result,
            'data_freshness':       self._data_freshness(currency_pair),
        }

    def _model_health(self, pm) -> dict:
        """Score 0–100 basado en: tiempo desde entrenamiento, MAPE reciente, existencia del archivo."""
        import os

        score   = 100.0
        issues  = []

        # 1. ¿Modelo entrenado recientemente? (penaliza si > 7 días sin reentrenar)
        if pm.last_trained:
            days_old = (timezone.now() - pm.last_trained).days
            if days_old > 7:
                penalty = min(30, days_old - 7)
                score  -= penalty
                issues.append(f"No reentrenado en {days_old} días")
        else:
            score -= 40
            issues.append("Nunca entrenado")

        # 2. ¿MAPE reciente aceptable?
        recent_mape = pm.metrics.get('recent_mape') or pm.metrics.get('mape', 0)
        if recent_mape:
            if recent_mape > 3.0:
                score -= 30
                issues.append(f"MAPE alto: {recent_mape:.2f}%")
            elif recent_mape > 1.5:
                score -= 15
                issues.append(f"MAPE moderado: {recent_mape:.2f}%")

        # 3. ¿Archivo del modelo existe?
        if pm.model_file and not os.path.exists(pm.model_file.path):
            score -= 50
            issues.append("Archivo del modelo no encontrado en disco")

        return {
            'model_type':   pm.model_type,
            'last_trained': pm.last_trained.isoformat() if pm.last_trained else None,
            'mape':         round(float(recent_mape or 0), 4),
            'health_score': max(0.0, round(score, 1)),
            'issues':       issues,
            'metrics':      pm.metrics,
        }

    # ── PSI drift detection ────────────────────────────────────────────────────

    def _compute_psi(self, currency_pair: str, bins: int = 10) -> dict:
        """
        Calcula PSI entre distribución de entrenamiento (90–180 días atrás)
        y distribución reciente (últimos 30 días).
        PSI < 0.10 → estable; 0.10–0.25 → cambio moderado; > 0.25 → drift significativo.
        """
        from predictions.models import TrainingData

        now       = timezone.now()
        ref_rates = list(
            TrainingData.objects
            .filter(currency_pair=currency_pair,
                    date__gte=now - timedelta(days=180),
                    date__lt=now  - timedelta(days=90))
            .values_list('rate', flat=True)
        )
        cur_rates = list(
            TrainingData.objects
            .filter(currency_pair=currency_pair,
                    date__gte=now - timedelta(days=30))
            .values_list('rate', flat=True)
        )

        if len(ref_rates) < 20 or len(cur_rates) < 20:
            return {'available': False, 'reason': 'datos insuficientes para PSI'}

        ref = np.array([float(r) for r in ref_rates])
        cur = np.array([float(r) for r in cur_rates])

        psi_value = _psi(ref, cur, bins=bins)

        if psi_value < PSI_GREEN:
            status_label, color = 'stable', 'green'
        elif psi_value < PSI_RED:
            status_label, color = 'moderate_change', 'yellow'
        else:
            status_label, color = 'significant_drift', 'red'
            logger.warning("PSI_DRIFT pair=%s psi=%.4f — considerar reentrenar", currency_pair, psi_value)
            try:
                from core.tasks import _emit_system_alert
                _emit_system_alert(
                    'ml',
                    f'Drift detectado en {currency_pair}: PSI={psi_value:.3f}',
                    severity='MEDIUM',
                )
            except Exception:
                pass

        return {
            'available':    True,
            'psi':          round(float(psi_value), 4),
            'status':       status_label,
            'color':        color,
            'ref_window':   '90–180 días atrás',
            'cur_window':   'últimos 30 días',
            'thresholds':   {'green': PSI_GREEN, 'red': PSI_RED},
        }

    # ── Frescura de datos ─────────────────────────────────────────────────────

    def _data_freshness(self, currency_pair: str) -> dict:
        from predictions.models import TrainingData

        latest = (
            TrainingData.objects
            .filter(currency_pair=currency_pair)
            .order_by('-date')
            .values('date', 'source')
            .first()
        )
        if not latest:
            return {'fresh': False, 'reason': 'Sin datos en TrainingData'}

        hours_old = (timezone.now() - latest['date']).total_seconds() / 3600
        fresh     = hours_old < DATA_STALENESS_THRESHOLD_HOURS

        if not fresh:
            logger.warning(
                "DATA_STALE pair=%s hours_old=%.1f source=%s",
                currency_pair, hours_old, latest['source'],
            )
            try:
                from core.tasks import _emit_system_alert
                _emit_system_alert(
                    'ml',
                    f'Datos desactualizados para {currency_pair}: {hours_old:.1f}h sin actualizar',
                    severity='MEDIUM',
                )
            except Exception:
                pass

        return {
            'fresh':     fresh,
            'last_date': latest['date'].isoformat(),
            'hours_old': round(hours_old, 1),
            'source':    latest['source'],
            'threshold_hours': DATA_STALENESS_THRESHOLD_HOURS,
        }

    # ── Fuentes de datos externas ─────────────────────────────────────────────

    def _check_data_sources(self) -> dict:
        """Verifica las últimas actualizaciones de cada fuente de tasas."""
        from rates.models import ExchangeRate

        sources = {}
        for src in ['BCB', 'PARALLEL', 'DIGITAL']:
            latest = (
                ExchangeRate.objects
                .filter(source=src)
                .order_by('-valid_from')
                .values('valid_from')
                .first()
            )
            if latest:
                hours_old = (timezone.now() - latest['valid_from']).total_seconds() / 3600
                sources[src] = {
                    'last_update': latest['valid_from'].isoformat(),
                    'hours_old':   round(hours_old, 1),
                    'status':      'ok' if hours_old < 2 else 'stale',
                }
            else:
                sources[src] = {'status': 'no_data'}
        return sources

    # ── Logging estructurado ──────────────────────────────────────────────────

    @staticmethod
    def log_prediction(prediction, model_type: str, currency_pair: str):
        """Logging estructurado para auditoría de cada predicción generada."""
        logger.info(
            "PREDICTION_AUDIT pair=%s model=%s date=%s rate=%.4f ci=[%.4f,%.4f] conf=%.2f",
            currency_pair,
            model_type,
            prediction['prediction_date'],
            prediction['rate'],
            prediction.get('lower', 0),
            prediction.get('upper', 0),
            prediction.get('confidence', 0),
        )


# ── Algoritmo PSI ─────────────────────────────────────────────────────────────

def _psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """
    Population Stability Index.
    PSI = Σ (actual% - expected%) * ln(actual% / expected%)
    Usa los mismos bins de referencia para ambas distribuciones.
    """
    breakpoints = np.percentile(reference, np.linspace(0, 100, bins + 1))
    breakpoints  = np.unique(breakpoints)
    if len(breakpoints) < 3:
        return 0.0

    ref_counts = np.histogram(reference, bins=breakpoints)[0]
    cur_counts = np.histogram(current,   bins=breakpoints)[0]

    # Evitar división por cero — usar Laplace smoothing
    ref_pct = (ref_counts + 0.0001) / (len(reference) + 0.0001 * len(ref_counts))
    cur_pct = (cur_counts + 0.0001) / (len(current)   + 0.0001 * len(cur_counts))

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return max(0.0, psi)
