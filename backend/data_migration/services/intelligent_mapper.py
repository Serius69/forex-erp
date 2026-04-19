# data_migration/services/intelligent_mapper.py
"""
Mapper inteligente: dado un conjunto de columnas del Google Sheet,
sugiere automáticamente los campos del modelo Django destino.

Estrategia:
1. Exact match (normalizado)
2. Fuzzy match con ratio de similitud
3. Heurísticas por contenido de muestra (fechas, montos, etc.)
"""
from __future__ import annotations
import re
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

# ── Definiciones de modelos destino ──────────────────────────────────────────
# Cada target tiene: campos requeridos, campos opcionales, tipo de transform sugerido

MODEL_SCHEMAS: dict[str, dict] = {
    'transactions': {
        'fields': {
            'fecha':            {'type': 'date_bo',      'required': True,  'aliases': ['date', 'fecha', 'f fecha', 'day', 'dia', 'fecha_transaccion']},
            'transaction_type': {'type': 'upper',         'required': True,  'aliases': ['tipo', 'type', 'operacion', 'operation', 'buy_sell', 'compra_venta']},
            'currency_code':    {'type': 'currency_code', 'required': True,  'aliases': ['moneda', 'currency', 'divisa', 'coin', 'cod_moneda']},
            'amount_from':      {'type': 'decimal',       'required': True,  'aliases': ['monto_origen', 'amount_from', 'monto_bob', 'bolivianos', 'bs', 'bob']},
            'amount_to':        {'type': 'decimal',       'required': True,  'aliases': ['monto_destino', 'amount_to', 'monto_divisa', 'foreign', 'divisas']},
            'exchange_rate':    {'type': 'decimal',       'required': True,  'aliases': ['tasa', 'rate', 'tipo_cambio', 'exchange', 'precio', 'cotizacion']},
            'payment_method':   {'type': 'upper',         'required': False, 'aliases': ['metodo_pago', 'payment', 'forma_pago', 'medio_pago']},
            'customer_name':    {'type': 'strip',         'required': False, 'aliases': ['cliente', 'customer', 'nombre', 'name', 'cliente_nombre']},
            'notes':            {'type': 'strip',         'required': False, 'aliases': ['notas', 'notes', 'observaciones', 'comentarios', 'obs']},
            'branch':           {'type': 'lookup_branch', 'required': False, 'aliases': ['sucursal', 'branch', 'oficina', 'agencia']},
        },
    },
    'rates': {
        'fields': {
            'currency_code':    {'type': 'currency_code', 'required': True,  'aliases': ['moneda', 'currency', 'divisa']},
            'buy_rate':         {'type': 'decimal',       'required': True,  'aliases': ['compra', 'buy', 'tipo_compra', 'precio_compra']},
            'sell_rate':        {'type': 'decimal',       'required': True,  'aliases': ['venta', 'sell', 'tipo_venta', 'precio_venta']},
            'official_rate':    {'type': 'decimal',       'required': False, 'aliases': ['oficial', 'official', 'bcb', 'boliviano_oficial']},
            'fecha':            {'type': 'date_bo',       'required': False, 'aliases': ['fecha', 'date', 'dia']},
            'market_type':      {'type': 'upper',         'required': False, 'aliases': ['mercado', 'market', 'tipo_mercado']},
        },
    },
    'inventory': {
        'fields': {
            'currency_code':    {'type': 'currency_code', 'required': True,  'aliases': ['moneda', 'currency', 'divisa']},
            'quantity':         {'type': 'decimal',       'required': True,  'aliases': ['cantidad', 'stock', 'quantity', 'monto', 'unidades']},
            'wac':              {'type': 'decimal',       'required': False, 'aliases': ['cmc', 'wac', 'costo_promedio', 'precio_promedio']},
            'fecha':            {'type': 'date_bo',       'required': False, 'aliases': ['fecha', 'date']},
            'branch':           {'type': 'lookup_branch', 'required': False, 'aliases': ['sucursal', 'branch']},
        },
    },
    'customers': {
        'fields': {
            'full_name':        {'type': 'strip',         'required': True,  'aliases': ['nombre', 'name', 'full_name', 'nombre_completo', 'cliente']},
            'document_number':  {'type': 'strip',         'required': False, 'aliases': ['ci', 'cedula', 'documento', 'doc', 'id', 'carnet']},
            'phone':            {'type': 'strip',         'required': False, 'aliases': ['telefono', 'phone', 'cel', 'celular', 'movil']},
            'email':            {'type': 'lower',         'required': False, 'aliases': ['email', 'correo', 'mail']},
            'address':          {'type': 'strip',         'required': False, 'aliases': ['direccion', 'address', 'domicilio']},
        },
    },
    'capital': {
        'fields': {
            'fecha':            {'type': 'date_bo',       'required': True,  'aliases': ['fecha', 'date', 'dia']},
            'concepto':         {'type': 'strip',         'required': True,  'aliases': ['concepto', 'descripcion', 'gasto', 'expense', 'detail']},
            'monto':            {'type': 'decimal',       'required': True,  'aliases': ['monto', 'amount', 'importe', 'valor', 'bs']},
            'categoria':        {'type': 'upper',         'required': False, 'aliases': ['categoria', 'category', 'tipo', 'type']},
            'branch':           {'type': 'lookup_branch', 'required': False, 'aliases': ['sucursal', 'branch']},
        },
    },
}


def _normalize(s: str) -> str:
    """Normaliza string: minúsculas, sin tildes, reemplaza espacios/guiones con _."""
    s = s.lower().strip()
    # Quitar tildes
    for a, b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n'),('ü','u')]:
        s = s.replace(a, b)
    s = re.sub(r'[\s\-/]+', '_', s)
    s = re.sub(r'[^a-z0-9_]', '', s)
    return s


def _similarity(a: str, b: str) -> float:
    """Ratio de similitud simple basado en caracteres comunes (Jaccard sobre bigramas)."""
    def bigrams(s: str) -> set:
        return {s[i:i+2] for i in range(len(s)-1)} if len(s) > 1 else {s}

    ba, bb = bigrams(a), bigrams(b)
    if not ba and not bb:
        return 1.0
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def _detect_transform(samples: list[Any]) -> str:
    """Detecta el tipo de transformación más adecuado según muestras de datos."""
    non_empty = [str(s).strip() for s in samples if s is not None and str(s).strip()]
    if not non_empty:
        return 'none'

    # Detectar fechas
    date_patterns = [
        r'^\d{1,2}/\d{1,2}/\d{4}$',   # dd/mm/yyyy o mm/dd/yyyy
        r'^\d{4}-\d{2}-\d{2}$',        # ISO
        r'^\d{1,2}-\d{1,2}-\d{4}$',
    ]
    if all(any(re.match(p, s) for p in date_patterns) for s in non_empty[:10]):
        if all(re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', s) for s in non_empty[:5]):
            return 'date_bo'
        return 'date_iso'

    # Detectar decimales
    decimal_hits = 0
    for s in non_empty[:20]:
        try:
            Decimal(s.replace(',', '.').replace(' ', ''))
            decimal_hits += 1
        except InvalidOperation:
            pass
    if decimal_hits >= len(non_empty[:20]) * 0.8:
        return 'decimal'

    # Detectar booleanos
    bool_values = {'si','no','yes','no','true','false','1','0','verdadero','falso'}
    if all(s.lower() in bool_values for s in non_empty[:10]):
        return 'boolean'

    # Detectar códigos de moneda
    currency_pattern = r'^[A-Z]{2,4}$'
    if all(re.match(currency_pattern, s.upper()) for s in non_empty[:10]):
        return 'currency_code'

    return 'strip'


class IntelligentMapper:
    """
    Dado un target_model y las columnas del sheet (con muestras opcionales),
    sugiere un mapeo columna → campo + transformación.
    """

    def __init__(self, target_model: str):
        if target_model not in MODEL_SCHEMAS:
            raise ValueError(f'target_model "{target_model}" no soportado. '
                             f'Opciones: {list(MODEL_SCHEMAS.keys())}')
        self.target_model = target_model
        self.schema = MODEL_SCHEMAS[target_model]['fields']

    def suggest_mappings(
        self,
        sheet_columns: list[str],
        sample_data: list[list[Any]] | None = None,
    ) -> list[dict]:
        """
        Retorna lista de sugerencias ordenadas por confianza descendente.

        Args:
            sheet_columns: Lista de nombres de columna del sheet.
            sample_data:   Filas de muestra (sin header) para inferir tipos.

        Returns:
            Lista de dicts con: sheet_column, model_field, transform,
            confidence (0.0–1.0), is_required, matched_by.
        """
        # Construir índice de muestras por columna
        column_samples: dict[str, list] = {}
        if sample_data:
            for col_idx, col_name in enumerate(sheet_columns):
                column_samples[col_name] = [
                    row[col_idx] if col_idx < len(row) else None
                    for row in sample_data[:30]
                ]

        suggestions = []
        matched_fields: set[str] = set()

        for col_name in sheet_columns:
            col_norm = _normalize(col_name)
            best_field: str | None = None
            best_confidence: float = 0.0
            best_match_by: str = 'none'
            best_transform: str = 'none'

            for field_name, field_def in self.schema.items():
                if field_name in matched_fields:
                    continue

                aliases = [_normalize(a) for a in field_def['aliases']]

                # 1. Exact match
                if col_norm == _normalize(field_name) or col_norm in aliases:
                    confidence = 1.0
                    match_by = 'exact'
                else:
                    # 2. Fuzzy match
                    sims = [_similarity(col_norm, a) for a in aliases + [_normalize(field_name)]]
                    max_sim = max(sims)
                    if max_sim > best_confidence:
                        confidence = max_sim * 0.9  # penalizar fuzzy
                        match_by = 'fuzzy'
                    else:
                        continue

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_field = field_name
                    best_match_by = match_by
                    best_transform = field_def['type']

            # 3. Detectar transform por muestras si confianza moderada
            samples = column_samples.get(col_name, [])
            if samples and best_confidence < 0.8:
                detected = _detect_transform(samples)
                if detected != 'none':
                    best_transform = detected

            if best_field and best_confidence >= 0.35:
                matched_fields.add(best_field)
                suggestions.append({
                    'sheet_column':  col_name,
                    'model_field':   best_field,
                    'transform':     best_transform,
                    'confidence':    round(best_confidence, 3),
                    'is_required':   self.schema[best_field]['is_required'],
                    'matched_by':    best_match_by,
                    'default_value': '',
                })
            else:
                # Columna sin match → incluir sin campo asignado
                suggestions.append({
                    'sheet_column':  col_name,
                    'model_field':   '',
                    'transform':     _detect_transform(samples) if samples else 'none',
                    'confidence':    0.0,
                    'is_required':   False,
                    'matched_by':    'none',
                    'default_value': '',
                })

        suggestions.sort(key=lambda x: x['confidence'], reverse=True)

        # Verificar campos requeridos no mapeados
        mapped_fields = {s['model_field'] for s in suggestions if s['model_field']}
        missing_required = [
            f for f, d in self.schema.items()
            if d['is_required'] and f not in mapped_fields
        ]
        if missing_required:
            logger.warning(
                'Campos requeridos sin mapear para %s: %s',
                self.target_model, missing_required
            )

        return suggestions

    def get_required_fields(self) -> list[str]:
        return [f for f, d in self.schema.items() if d['is_required']]

    def validate_mapping_completeness(self, mappings: list[dict]) -> dict:
        """Verifica que todos los campos requeridos estén mapeados."""
        mapped = {m['model_field'] for m in mappings if m.get('model_field')}
        required = set(self.get_required_fields())
        missing = required - mapped
        return {
            'is_complete': len(missing) == 0,
            'missing_required': list(missing),
            'mapped_count': len(mapped),
            'total_required': len(required),
        }
