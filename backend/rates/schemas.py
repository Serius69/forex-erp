"""
Esquemas de datos compartidos entre la capa de integración y los modelos Django.

NormalizedRate es el contrato de dato entre cualquier fetcher y la DB.
Todos los precios son Decimal — nunca float.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as tz
from decimal import Decimal
from typing import Optional


@dataclass
class NormalizedRate:
    moneda_base:     str           # "USD"
    moneda_cotizada: str           # "BOB"
    precio:          Decimal       # precio de referencia principal (compra o mid)
    precio_compra:   Optional[Decimal]
    precio_venta:    Optional[Decimal]
    spread_pct:      Optional[Decimal]
    fuente:          str           # id_fuente, ej: "binance_p2p_bob"
    tipo_fuente:     str           # "P2P", "AGREGADOR", "EXCHANGE", "WALLET"
    timestamp:       datetime      # UTC
    payload_raw:     dict = field(default_factory=dict)
    confianza:       int  = 80     # 0-100
    es_valido:       bool = True
    notas:           str  = ""

    # ── Computed helpers ──────────────────────────────────────────────────────

    @property
    def par(self) -> str:
        return f"{self.moneda_base}/{self.moneda_cotizada}"

    @property
    def precio_mid(self) -> Decimal:
        if self.precio_compra and self.precio_venta:
            return (self.precio_compra + self.precio_venta) / Decimal('2')
        return self.precio

    def to_db(self) -> dict:
        """Dict listo para ExchangeRateRaw.objects.create(**rate.to_db())."""
        return {
            'id_fuente_str':   self.fuente,
            'moneda_base':     self.moneda_base,
            'moneda_cotizada': self.moneda_cotizada,
            'precio_compra':   self.precio_compra or self.precio,
            'precio_venta':    self.precio_venta,
            'precio_promedio': self.precio_mid,
            'spread_pct':      self.spread_pct,
            'timestamp_fuente': self.timestamp,
            'payload_raw':     self.payload_raw,
            'es_valido':       self.es_valido,
            'notas':           self.notas,
        }

    def __post_init__(self):
        # Asegurar que monedas estén en mayúsculas
        self.moneda_base     = self.moneda_base.upper()
        self.moneda_cotizada = self.moneda_cotizada.upper()
        # Asegurar timestamp UTC
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=tz.utc)
        # Auto-calcular spread_pct si falta y tenemos ambos precios
        if self.spread_pct is None and self.precio_compra and self.precio_venta:
            if self.precio_compra > 0:
                self.spread_pct = (
                    (self.precio_venta - self.precio_compra) / self.precio_compra * 100
                ).quantize(Decimal('0.0001'))
