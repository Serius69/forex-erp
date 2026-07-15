"""
Utilidades para keyear artefactos de modelos por serie de mercado.

Las 3 series de pronóstico (web / competencia / empresa) comparten par de divisas
pero entrenan modelos distintos. Para no pisarse entre sí, cada artefacto
(archivo .pkl/.keras, fila PredictionModel, cache key) se cualifica por `market`.

Regla: la serie 'web' NO lleva sufijo → los artefactos web existentes siguen
válidos byte-a-byte (retrocompatibilidad). Las series ≠ web llevan `__<market>`.
"""

VALID_MARKETS = ('web', 'competencia', 'empresa')
DEFAULT_MARKET = 'web'


def normalize_market(market: str) -> str:
    m = (market or DEFAULT_MARKET).strip().lower()
    return m if m in VALID_MARKETS else DEFAULT_MARKET


def fname_suffix(market: str) -> str:
    """Sufijo para nombres de archivo/keys. '' para web, '__<market>' para el resto."""
    m = normalize_market(market)
    return '' if m == DEFAULT_MARKET else f'__{m}'
