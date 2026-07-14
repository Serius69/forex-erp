# Modelos ML persistidos

Directorio para artefactos de modelos entrenados. En Docker es un **volumen nombrado**
(`forex-erp_ml_models` → `/app/ml-models`), por lo que los artefactos persisten entre
reinicios y **no** se versionan en git.

## `risk_review_model.cbm` — Riesgo de revisión de cumplimiento (CatBoost + SHAP)

Modelo que **aprende a reproducir el motor antifraude** (`transactions/fraud_detection.py`)
y explica cada decisión con SHAP. Complementa a las reglas: además de *si* una operación se
marca, dice *por qué* (factores y su peso), un requisito regulatorio (ASFI/UIF).

Origen: laboratorios de la Maestría en IA (comparación de algoritmos → CatBoost por manejo
nativo de categóricas + `TreeExplainer` exacto). Código: `transactions/ml_risk.py`.

### Entrenar

```bash
# Desde el historial real de transacciones (usa Transaction.approval_required como etiqueta;
# si es degenerada —seeds sin marcar— la deriva de las reglas del motor sobre features reales):
python manage.py train_risk_model

# Prueba rápida sin BD (datos sintéticos):
python manage.py train_risk_model --demo
```

Guarda `risk_review_model.cbm` en este directorio e imprime AUC / F1.

### Explicar una operación (API)

```
GET /api/transactions/<id>/risk-explanation/
```

Respuesta:

```jsonc
{
  "transaction": "0120260708G0016",
  "probability": 0.99,             // P(requiere revisión) del modelo ML
  "decision": "REQUIERE_REVISION",
  "base_value": -1.68,             // valor base SHAP (log-odds)
  "rule_engine": {                 // decisión del motor de reglas (para contraste)
    "fraud_score": 0.0, "approval_required": false, "fraud_flags": []
  },
  "top_factors": [                 // descomposición SHAP: qué pesó y cuánto
    {"feature": "amount_z", "value": 133.2, "shap": 2.568, "direction": "aumenta_riesgo"},
    {"feature": "foreign_amount", "value": 19900, "shap": 1.579, "direction": "aumenta_riesgo"}
  ],
  "features": { ... }
}
```

Si faltan `catboost`/`shap` o el modelo no está entrenado, el endpoint responde **503**
(el resto del ERP no se ve afectado — importaciones perezosas).

### Características usadas (alineadas con las reglas del motor)

| Feature | Regla del motor |
|---|---|
| `amount_bob` | HIGH_VALUE (umbral de supervisión) |
| `rate_deviation_pct` | RATE_SANITY (tasa desviada) |
| `amount_z` | AMOUNT_ANOMALY (monto atípico por divisa) |
| `cashier_velocity` | VELOCITY (operaciones cajero/día) |
| `foreign_amount`, `exchange_rate`, `transaction_type`, `currency`, `payment_method`, `weekday` | contexto |

### Despliegue

`catboost` y `shap` están en `requirements.txt`. Tras reconstruir la imagen del backend,
ejecutar `python manage.py train_risk_model` una vez para generar el artefacto.

### Tests

`transactions/tests/test_ml_risk.py` (no requieren BD; se saltan si faltan catboost/shap).
