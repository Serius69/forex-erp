"""
Modelo ML de riesgo de revisión + explicabilidad SHAP (complemento del motor antifraude).
==========================================================================================

Aplica al ERP la investigación del laboratorio de la maestría (CatBoost + SHAP): en vez de
—o además de— las reglas de `fraud_detection.FraudDetectionEngine`, entrena un modelo que
**aprende** de las decisiones históricas (`Transaction.approval_required`) y, para cada
operación, entrega:

    * una probabilidad de que requiera revisión de cumplimiento, y
    * la **explicación SHAP** (qué factores empujaron la decisión y cuánto).

Esto es un requisito regulatorio (ASFI/UIF): cada marca puede acompañarse de su explicación.

Diseño
------
El núcleo (`RiskReviewModel`) trabaja sobre `pandas.DataFrame` y NO depende de Django, para
poder entrenarse/probarse fuera del ORM. Los adaptadores Django (`features_from_transaction`,
`training_frame`) convierten `Transaction` ↔ DataFrame.

Las dependencias pesadas (`catboost`, `shap`) se importan de forma **perezosa**: si no están
instaladas, el resto del ERP sigue funcionando y el endpoint responde 503.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Artefacto del modelo entrenado (directorio ya existente en el backend).
MODEL_DIR = Path(__file__).resolve().parent.parent / "ml-models"
MODEL_PATH = MODEL_DIR / "risk_review_model.cbm"

# --- Esquema de características (alineado con las reglas del motor antifraude) ---------
NUM_FEATURES = [
    "amount_bob",        # monto en Bs (regla HIGH_VALUE)
    "foreign_amount",    # monto en moneda extranjera
    "exchange_rate",     # tipo de cambio aplicado
    "rate_deviation_pct",# desviación vs. tasa paralela snapshot (RATE_SANITY)
    "amount_z",          # z-score del monto por divisa (AMOUNT_ANOMALY)
    "cashier_velocity",  # operaciones del cajero en el día (VELOCITY)
]
CAT_FEATURES = [
    "transaction_type",  # BUY / SELL
    "currency",          # código de la divisa extranjera (USD, EUR, ...)
    "payment_method",    # CASH / TRANSFER / QR / ...
    "weekday",           # 0..6
]
FEATURES = NUM_FEATURES + CAT_FEATURES
TARGET = "requires_review"


@dataclass
class RiskExplanation:
    """Resultado de explicar una operación."""
    probability: float
    decision: str                       # 'REQUIERE_REVISION' | 'NORMAL'
    base_value: float
    top_factors: list[dict[str, Any]]   # [{feature, value, shap, direction}]


class RiskReviewModel:
    """Clasificador CatBoost + explicador SHAP para el riesgo de revisión."""

    def __init__(self) -> None:
        self._model = None
        self._explainer = None

    # ---- Entrenamiento ---------------------------------------------------------------
    def train(self, df: pd.DataFrame, iterations: int = 500, seed: int = 42) -> dict[str, float]:
        """Entrena desde un DataFrame con las columnas FEATURES + TARGET. Devuelve métricas."""
        from catboost import CatBoostClassifier, Pool  # import perezoso
        from sklearn.metrics import f1_score, roc_auc_score
        from sklearn.model_selection import train_test_split

        X = df[FEATURES].copy()
        y = df[TARGET].astype(int)
        for c in CAT_FEATURES:
            X[c] = X[c].astype(str)
        cat_idx = [FEATURES.index(c) for c in CAT_FEATURES]

        strat = y if y.nunique() > 1 and y.value_counts().min() >= 2 else None
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.25, random_state=seed, stratify=strat)

        model = CatBoostClassifier(
            iterations=iterations, depth=6, learning_rate=0.05, l2_leaf_reg=3.0,
            loss_function="Logloss", random_seed=seed, verbose=False)
        model.fit(Pool(X_tr, y_tr, cat_features=cat_idx))

        proba = model.predict_proba(X_te)[:, 1]
        pred = (proba >= 0.5).astype(int)
        metrics = {
            "n_train": int(len(X_tr)), "n_test": int(len(X_te)),
            "positives_rate": float(y.mean()),
            "roc_auc": float(roc_auc_score(y_te, proba)) if y_te.nunique() > 1 else float("nan"),
            "f1": float(f1_score(y_te, pred)) if y_te.nunique() > 1 else float("nan"),
        }
        self._model = model
        self._explainer = None
        return metrics

    def save(self, path: Path = MODEL_PATH) -> Path:
        if self._model is None:
            raise RuntimeError("No hay modelo entrenado que guardar.")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path))
        return path

    def load(self, path: Path = MODEL_PATH) -> "RiskReviewModel":
        from catboost import CatBoostClassifier  # import perezoso
        if not Path(path).exists():
            raise FileNotFoundError(
                f"Modelo de riesgo no entrenado ({path}). Ejecute "
                "`python manage.py train_risk_model`.")
        m = CatBoostClassifier()
        m.load_model(str(path))
        self._model = m
        self._explainer = None
        return self

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    # ---- Predicción + explicación ----------------------------------------------------
    def _row_frame(self, feats: dict[str, Any]) -> pd.DataFrame:
        row = {k: feats.get(k) for k in FEATURES}
        df = pd.DataFrame([row])
        for c in CAT_FEATURES:
            df[c] = df[c].astype(str)
        for c in NUM_FEATURES:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        return df

    def predict_proba(self, feats: dict[str, Any]) -> float:
        if self._model is None:
            self.load()
        return float(self._model.predict_proba(self._row_frame(feats))[0, 1])

    def explain(self, feats: dict[str, Any], top_n: int = 6, threshold: float = 0.5) -> RiskExplanation:
        """Devuelve probabilidad + descomposición SHAP (factores que más pesaron)."""
        import shap  # import perezoso
        from catboost import Pool

        if self._model is None:
            self.load()
        df = self._row_frame(feats)
        cat_idx = [FEATURES.index(c) for c in CAT_FEATURES]

        if self._explainer is None:
            self._explainer = shap.TreeExplainer(self._model)
        shap_values = self._explainer.shap_values(Pool(df, cat_features=cat_idx))[0]
        base = float(self._explainer.expected_value)
        proba = float(self._model.predict_proba(df)[0, 1])

        factores = []
        for feat, sv in sorted(zip(FEATURES, shap_values), key=lambda t: abs(t[1]), reverse=True)[:top_n]:
            factores.append({
                "feature": feat,
                "value": df[feat].iloc[0] if feat in df else None,
                "shap": round(float(sv), 4),
                "direction": "aumenta_riesgo" if sv > 0 else "reduce_riesgo",
            })
        return RiskExplanation(
            probability=round(proba, 4),
            decision="REQUIERE_REVISION" if proba >= threshold else "NORMAL",
            base_value=round(base, 4),
            top_factors=factores,
        )


# ======================================================================================
# Adaptadores Django  (Transaction <-> features)
# ======================================================================================
def features_from_transaction(tx, enrich: bool = True) -> dict[str, Any]:
    """Extrae el vector de características de una instancia `Transaction`.

    Robusto ante campos nulos: cae a 0/'' sin lanzar excepciones.

    Si `enrich` y no vienen precalculados (`_amount_z`, `_cashier_velocity`), estima
    `cashier_velocity` (operaciones del cajero ese día) y `amount_z` (z-score del monto en
    su divisa) consultando la BD. En entrenamiento por lotes se pasan precalculados y
    `enrich=False` (ver `training_frame`).
    """
    def _f(x, default=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    tipo = (tx.transaction_type or "BUY")
    rate = _f(tx.exchange_rate)
    # Moneda extranjera y unidades según el tipo de operación.
    if tipo == "BUY":
        foreign_ccy = getattr(tx.currency_from, "code", "") if tx.currency_from_id else ""
        foreign_amount = _f(tx.amount_from)
    else:
        foreign_ccy = getattr(tx.currency_to, "code", "") if tx.currency_to_id else ""
        foreign_amount = _f(tx.amount_to)
    foreign_ccy = foreign_ccy or "USD"
    amount_bob = foreign_amount * rate if rate else _f(getattr(tx, "amount_to", 0))

    # RATE_SANITY: desviación vs. tasa paralela snapshot.
    par = _f(getattr(tx, "parallel_rate_at_creation", 0))
    rate_dev = abs(rate - par) / par * 100 if par else 0.0

    weekday = tx.created_at.weekday() if getattr(tx, "created_at", None) else 0

    amount_z = getattr(tx, "_amount_z", None)
    velocity = getattr(tx, "_cashier_velocity", None)
    if enrich and (amount_z is None or velocity is None):
        amount_z, velocity = _enrich_from_db(tx, foreign_ccy, amount_bob, tipo)

    return {
        "amount_bob": amount_bob,
        "foreign_amount": foreign_amount,
        "exchange_rate": rate,
        "rate_deviation_pct": round(rate_dev, 3),
        "amount_z": round(_f(amount_z), 3),
        "cashier_velocity": int(velocity or 0),
        "transaction_type": tipo,
        "currency": foreign_ccy,
        "payment_method": tx.payment_method or "CASH",
        "weekday": int(weekday),
    }


def _enrich_from_db(tx, currency: str, amount_bob: float, tipo: str) -> tuple[float, int]:
    """Estima (amount_z, cashier_velocity) para UNA transacción desde la BD (best-effort)."""
    try:
        from django.db.models import Avg, Count, StdDev

        from .models import Transaction

        # VELOCITY: operaciones del mismo cajero ese día.
        velocity = 0
        if getattr(tx, "cashier_id", None) and getattr(tx, "created_at", None):
            velocity = Transaction.objects.filter(
                cashier_id=tx.cashier_id, created_at__date=tx.created_at.date()
            ).count()

        # AMOUNT_ANOMALY: z-score del monto dentro de la misma divisa (ventana reciente).
        campo_ccy = "currency_from__code" if tipo == "BUY" else "currency_to__code"
        agg = (Transaction.objects.filter(**{campo_ccy: currency})
               .aggregate(m=Avg("exchange_rate"), n=Count("id")))
        # Aproximación robusta: si no hay estadística suficiente, z=0.
        amount_z = 0.0
        stats = (Transaction.objects.filter(**{campo_ccy: currency})
                 .aggregate(prom=Avg("amount_from"), sd=StdDev("amount_from")))
        prom, sd = stats.get("prom"), stats.get("sd")
        if prom is not None and sd:
            amount_z = (amount_bob - float(prom)) / float(sd)
        return float(amount_z), int(velocity)
    except Exception:
        return 0.0, 0


def training_frame(queryset) -> pd.DataFrame:
    """Construye el DataFrame de entrenamiento desde un queryset de `Transaction`.

    Deriva `amount_z` (por divisa) y `cashier_velocity` (cajero/día) en lote, y usa
    `approval_required` como etiqueta.
    """
    filas = []
    for tx in queryset.select_related("currency_from", "currency_to"):
        f = features_from_transaction(tx, enrich=False)  # z/velocity se derivan en lote abajo
        f["_cashier_id"] = getattr(tx, "cashier_id", None)
        f["_date"] = tx.created_at.date() if getattr(tx, "created_at", None) else None
        f[TARGET] = int(bool(getattr(tx, "approval_required", False)))
        filas.append(f)
    df = pd.DataFrame(filas)
    if df.empty:
        return df

    # amount_z por divisa
    g = df.groupby("currency")["amount_bob"]
    df["amount_z"] = ((df["amount_bob"] - g.transform("mean")) /
                      g.transform("std").replace(0, 1)).fillna(0.0).round(3)
    # velocity: operaciones del cajero en el día
    df["cashier_velocity"] = (df.groupby(["_cashier_id", "_date"])["amount_bob"]
                              .transform("size").fillna(1).astype(int))
    df = df.drop(columns=["_cashier_id", "_date"])

    # Si la etiqueta histórica es degenerada (una sola clase: p. ej. seeds sin correr el
    # motor), se deriva de las REGLAS del motor antifraude sobre las features reales.
    # Así el modelo "aprende a reproducir el motor" — el mismo enfoque del laboratorio.
    if df[TARGET].nunique() < 2:
        df[TARGET] = label_from_rules(df)
    return df


def label_from_rules(df: pd.DataFrame, seed: int = 42) -> pd.Series:
    """Etiqueta `requires_review` derivada de las reglas de `FraudDetectionEngine`.

    Umbrales tomados de `fraud_detection.FraudDetectionEngine.DEFAULT_RULES`:
    VELOCITY>10, AMOUNT_ANOMALY z>3, RATE_SANITY %>5, HIGH_VALUE Bs>100.000. Se combina en
    un puntaje logístico con un pequeño componente aleatorio (revisión humana no determinista).
    """
    rng = np.random.default_rng(seed)
    score = (
        1.5 * np.clip(df["amount_bob"] / 100_000.0, 0, 3)          # HIGH_VALUE
        + 1.2 * np.clip(df["rate_deviation_pct"] / 5.0, 0, 3)      # RATE_SANITY
        + 0.9 * np.clip(df["amount_z"] / 3.0, 0, 4)               # AMOUNT_ANOMALY
        + 0.6 * np.clip((df["cashier_velocity"] - 10) / 5.0, 0, None)  # VELOCITY
        + 0.5 * (df["currency"] != "USD").astype(float)           # divisa poco líquida
        - 2.3
    ).to_numpy()
    prob = 1.0 / (1.0 + np.exp(-score))
    return (rng.uniform(size=len(df)) < prob).astype(int)
