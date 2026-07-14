"""
Entrena el modelo ML de riesgo de revisión (CatBoost + SHAP) desde el historial real.

    python manage.py train_risk_model                 # entrena desde la BD
    python manage.py train_risk_model --min-rows 500   # exige un mínimo de filas
    python manage.py train_risk_model --demo           # datos sintéticos (sin BD)

Guarda el artefacto en `backend/ml-models/risk_review_model.cbm`, reutilizado por el
endpoint de explicación (`/api/transactions/<id>/risk_explanation/`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand

from transactions.ml_risk import FEATURES, TARGET, RiskReviewModel


def _demo_frame(n: int = 4000, seed: int = 42) -> pd.DataFrame:
    """Genera un DataFrame sintético con la estructura de features (para pruebas sin BD)."""
    rng = np.random.default_rng(seed)
    foreign = rng.lognormal(4.6, 1.0, n).round(2)
    rate = rng.normal(15.8, 0.6, n).round(2)
    amount_bob = (foreign * rate).round(2)
    rate_dev = np.abs(rng.normal(0, 2.5, n)).round(3)
    ccy = rng.choice(["USD", "EUR", "CLP", "PEN", "BRL", "ARS"], n,
                     p=[0.7, 0.08, 0.09, 0.06, 0.04, 0.03])
    z = ((amount_bob - amount_bob.mean()) / amount_bob.std()).round(3)
    velocity = rng.poisson(6, n) + 1
    score = (1.4 * np.clip(amount_bob / 20000, 0, 3) + 1.2 * np.clip(rate_dev / 5, 0, 3)
             + 0.8 * np.clip(z, 0, 4) + 0.2 * np.clip(velocity - 10, 0, None)
             + 0.6 * (ccy != "USD") - 2.4)
    prob = 1 / (1 + np.exp(-score))
    return pd.DataFrame({
        "amount_bob": amount_bob, "foreign_amount": foreign, "exchange_rate": rate,
        "rate_deviation_pct": rate_dev, "amount_z": z, "cashier_velocity": velocity,
        "transaction_type": rng.choice(["BUY", "SELL"], n, p=[0.77, 0.23]),
        "currency": ccy, "payment_method": rng.choice(["CASH", "QR"], n, p=[0.98, 0.02]),
        "weekday": rng.integers(0, 7, n),
        TARGET: (rng.uniform(size=n) < prob).astype(int),
    })


class Command(BaseCommand):
    help = "Entrena el modelo ML de riesgo de revisión (CatBoost) desde el historial de transacciones."

    def add_arguments(self, parser):
        parser.add_argument("--min-rows", type=int, default=300,
                            help="Mínimo de transacciones para entrenar desde la BD.")
        parser.add_argument("--demo", action="store_true",
                            help="Usar datos sintéticos en vez de la BD.")
        parser.add_argument("--iterations", type=int, default=500)

    def handle(self, *args, **opts):
        if opts["demo"]:
            self.stdout.write("Modo DEMO: entrenando con datos sintéticos…")
            df = _demo_frame()
        else:
            from transactions.ml_risk import training_frame
            from transactions.models import Transaction
            qs = Transaction.objects.all()
            df = training_frame(qs)
            if df.empty or len(df) < opts["min_rows"]:
                self.stderr.write(self.style.WARNING(
                    f"Solo {0 if df.empty else len(df)} transacciones (< {opts['min_rows']}). "
                    "Use --demo para una prueba, o espere a tener más historial."))
                if df.empty:
                    return
            df = df[FEATURES + [TARGET]]

        if df[TARGET].nunique() < 2:
            self.stderr.write(self.style.ERROR(
                "La etiqueta 'requires_review' no tiene ambas clases; no se puede entrenar."))
            return

        model = RiskReviewModel()
        metrics = model.train(df, iterations=opts["iterations"])
        path = model.save()

        self.stdout.write(self.style.SUCCESS(f"Modelo guardado en {path}"))
        self.stdout.write(
            f"  filas: {metrics['n_train']} train / {metrics['n_test']} test  |  "
            f"positivos: {metrics['positives_rate']:.1%}")
        self.stdout.write(
            f"  ROC-AUC: {metrics['roc_auc']:.3f}  |  F1: {metrics['f1']:.3f}")
