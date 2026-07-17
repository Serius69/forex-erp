"""
Caché LRU en-proceso de artefactos de modelo, keyed por (ruta, mtime).

Los forecasters recargaban su artefacto de disco en CADA ``predict()``
(``tf.keras.models.load_model`` + ``joblib.load``). En ``cache_all_horizons``
eso se repetía 4× por horizonte × 18 combos (par×market)/hora, y de nuevo en
``refresh_ensemble_weights`` cada 4 h: cientos de deserializaciones/hora sobre un
puñado de artefactos que no cambian entre llamadas. Esta caché mantiene el objeto
ya deserializado en memoria y lo re-lee SOLO cuando el ``mtime`` del archivo
cambia (es decir, tras reentrenar, que reescribe el .pkl/.keras) → auto-invalida.

Diseño:
  - **Proceso-local** (dict a nivel de módulo). Bajo Celery *prefork* cada worker
    tiene su propia copia; no se comparte entre procesos → sin pickling ni fork
    de objetos Keras/joblib.
  - **LRU acotada** (``maxsize``, default 32) para no crecer sin límite.
  - **Clave = (ruta, mtime)**. Un ``mtime`` nuevo produce una clave nueva → la
    entrada vieja cae por LRU y se sirve la recién entrenada. La resolución de
    ``mtime`` (~1 s) puede servir una versión obsoleta si un reentreno y un
    ``predict`` caen en el mismo segundo; se auto-corrige en la llamada siguiente.
  - **Thread-safety**: un ``Lock`` protege el ``OrderedDict``; la deserialización
    (potencialmente de segundos para Keras) se hace FUERA del lock para no
    serializar cargas de artefactos distintos.

Los objetos cacheados se usan en modo SOLO-LECTURA por los ``predict()``
(``model.predict`` / ``scaler.transform``); no se mutan, así que compartir la
misma instancia entre llamadas es seguro.
"""
import os
import threading
from collections import OrderedDict

DEFAULT_MAXSIZE = 32

_lock = threading.Lock()
_cache: "OrderedDict[tuple, object]" = OrderedDict()


def load_cached(path: str, loader, maxsize: int = DEFAULT_MAXSIZE):
    """Devuelve ``loader(path)`` cacheado por ``(path, mtime(path))``.

    ``loader`` es un callable que recibe la ruta y devuelve el objeto
    deserializado (p.ej. ``joblib.load`` o ``tf.keras.models.load_model``). Se
    invoca solo en cache-miss o cuando el archivo cambió de ``mtime`` (reentreno).
    """
    mtime = os.path.getmtime(path)      # lanza FileNotFoundError si no existe (igual que joblib.load)
    key = (path, mtime)

    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    # Cargar fuera del lock (puede tardar segundos para Keras).
    obj = loader(path)

    with _lock:
        # Otro hilo pudo haber cargado el mismo key mientras tanto.
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        _cache[key] = obj
        _cache.move_to_end(key)
        while len(_cache) > maxsize:
            _cache.popitem(last=False)
    return obj


def clear() -> None:
    """Vacía la caché (uso en tests)."""
    with _lock:
        _cache.clear()
