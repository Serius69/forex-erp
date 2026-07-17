"""
Detector de oportunidades de arbitraje entre fuentes de tasas de cambio.

Tipos de oportunidad detectados:

  1. CROSS_SOURCE — compra en fuente A es más barata que venta en fuente B
     para la misma divisa. Profit = sell_B - buy_A.

  2. SPREAD_MARGIN — ranking de divisas por margen compra/venta propio.
     Indica qué divisas son más rentables de operar hoy.

  3. BCB_PREMIUM — cuánto % por encima del BCB oficial está cotizando
     cada mercado. Mide la brecha del mercado paralelo boliviano.

  4. TRIANGULAR — ruta indirecta A→C→B rinde más que A→B directamente.
     Ej. USD→CLP→BOB vs USD→BOB.

Uso:
    detector = ArbitrageDetector()
    opps     = detector.detect()             # todas las oportunidades
    summary  = detector.summary()            # dict para el endpoint
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

log = logging.getLogger('kapitalya.rates.arbitrage')

RiskLevel = Literal['LOW', 'MEDIUM', 'HIGH']
OpType    = Literal['cross_source', 'spread_margin', 'triangular']


# Umbral mínimo de ganancia para reportar (% sobre el costo)
MIN_PROFIT_PCT = 0.5   # 0.5% — filtra ruido


@dataclass
class ArbitrageOpportunity:
    """Una oportunidad de arbitraje detectada entre fuentes de tasas."""
    opp_type:        OpType
    currency:        str          # divisa involucrada
    currency_via:    str          # divisa intermediaria (triangular) o ''
    buy_at:          Decimal      # mejor precio de compra disponible (BOB)
    sell_at:         Decimal      # mejor precio de venta disponible (BOB)
    profit_per_unit: Decimal      # sell_at - buy_at
    profit_pct:      float        # ganancia % sobre buy_at
    scale_factor:    int          # escala de la divisa
    buy_source:      str          # fuente donde comprar más barato
    sell_source:     str          # fuente donde vender más caro
    market_buy:      str          # tipo de mercado del precio de compra
    market_sell:     str          # tipo de mercado del precio de venta
    risk:            RiskLevel    # LOW / MEDIUM / HIGH
    confidence:      float        # 0–1 combinado de las fuentes
    description:     str          # descripción legible para el UI
    detected_at:     datetime     = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict:
        return {
            'type':            self.opp_type,
            'currency':        self.currency,
            'currency_via':    self.currency_via,
            'buy_at':          float(self.buy_at),
            'sell_at':         float(self.sell_at),
            'profit_per_unit': float(self.profit_per_unit),
            'profit_pct':      round(self.profit_pct, 2),
            'scale_factor':    self.scale_factor,
            'buy_source':      self.buy_source,
            'sell_source':     self.sell_source,
            'market_buy':      self.market_buy,
            'market_sell':     self.market_sell,
            'risk':            self.risk,
            'confidence':      round(self.confidence, 3),
            'description':     self.description,
            'detected_at':     self.detected_at.isoformat(),
        }


class ArbitrageDetector:
    """
    Detecta oportunidades de arbitraje consultando las tasas activas en DB.
    Stateless — se instancia y llama por petición o desde Celery.
    """

    def detect(self) -> list[ArbitrageOpportunity]:
        """
        Ejecuta todos los detectores y retorna la lista de oportunidades
        ordenada por profit_pct descendente.
        """
        rates_by_currency = self._load_rates()
        if not rates_by_currency:
            log.warning("ARBITRAGE_NO_RATES — sin tasas activas en DB")
            return []

        opportunities: list[ArbitrageOpportunity] = []

        opportunities.extend(self._detect_cross_source(rates_by_currency))
        opportunities.extend(self._detect_spread_margin(rates_by_currency))
        opportunities.extend(self._detect_triangular(rates_by_currency))

        # Filtrar por umbral mínimo y ordenar
        filtered = [o for o in opportunities if o.profit_pct >= MIN_PROFIT_PCT]
        filtered.sort(key=lambda o: o.profit_pct, reverse=True)

        log.info(
            "ARBITRAGE_DETECT found=%d (above %.1f%% threshold)",
            len(filtered), MIN_PROFIT_PCT,
        )
        return filtered

    def summary(self) -> dict:
        """
        Retorna resumen completo para el endpoint /api/rates/arbitrage/.
        Incluye oportunidades, métricas globales y ranking por divisa.
        """
        from django.utils import timezone as tz

        opps  = self.detect()
        rates = self._load_rates()

        return {
            'detected_at':       tz.now().isoformat(),
            'total_opportunities': len(opps),
            'opportunities':     [o.to_dict() for o in opps],
            'best_opportunity':  opps[0].to_dict() if opps else None,
            'currency_ranking':  self._currency_ranking(rates),
            'market_spread_map': self._market_spread_map(rates),
            'alerts':            self._build_alerts(opps, rates),
        }

    # ------------------------------------------------------------------ #
    #  Carga de tasas desde DB                                            #
    # ------------------------------------------------------------------ #

    def _load_rates(self) -> dict[str, list[dict]]:
        """
        Carga todas las tasas activas (valid_until IS NULL) agrupadas por divisa.
        Retorna {currency_code: [{market_type, buy, sell, official, source, scale, confidence}]}
        """
        from .models import ExchangeRate, Currency

        qs = (
            ExchangeRate.objects
            .filter(valid_until__isnull=True)
            .select_related('currency_from', 'currency_to', 'rate_source')
            .order_by('currency_from__code', 'market_type')
        )

        result: dict[str, list[dict]] = {}
        for r in qs:
            code  = r.currency_from.code
            if r.currency_to.code != 'BOB':
                continue
            entry = {
                'market_type': r.market_type,
                'buy':         r.buy_rate,
                'sell':        r.sell_rate,
                'official':    r.official_rate,
                'source':      r.source or r.market_type.upper(),
                'scale':       r.currency_from.scale_factor,
                'confidence':  float(r.rate_source.weight) / 2.0 if r.rate_source else 0.7,
                'rate_id':     r.id,
            }
            result.setdefault(code, []).append(entry)

        return result

    # ------------------------------------------------------------------ #
    #  1. Cross-source: comprar en A más barato que vender en B           #
    # ------------------------------------------------------------------ #

    def _detect_cross_source(
        self, rates: dict[str, list[dict]]
    ) -> list[ArbitrageOpportunity]:
        """
        Para cada divisa, encuentra el precio de compra más bajo y el de venta
        más alto entre todas las fuentes. Si sell_max > buy_min → oportunidad.
        """
        opps = []

        for code, sources in rates.items():
            if len(sources) < 2:
                continue

            # Mejor compra (precio más bajo = compro más barato)
            cheapest = min(sources, key=lambda s: s['buy'])
            # Mejor venta (precio más alto = vendo más caro)
            dearest  = max(sources, key=lambda s: s['sell'])

            if cheapest['source'] == dearest['source']:
                continue

            buy_price  = cheapest['buy']
            sell_price = dearest['sell']

            if sell_price <= buy_price:
                continue

            profit     = sell_price - buy_price
            profit_pct = float(profit / buy_price * 100) if buy_price > 0 else 0.0

            risk  = self._risk_for_markets(cheapest['market_type'], dearest['market_type'])
            conf  = (cheapest['confidence'] + dearest['confidence']) / 2

            scale = cheapest['scale']
            scale_note = f" (por {scale:,} unidades)" if scale > 1 else ""

            opps.append(ArbitrageOpportunity(
                opp_type        = 'cross_source',
                currency        = code,
                currency_via    = '',
                buy_at          = buy_price,
                sell_at         = sell_price,
                profit_per_unit = profit,
                profit_pct      = profit_pct,
                scale_factor    = scale,
                buy_source      = cheapest['source'],
                sell_source     = dearest['source'],
                market_buy      = cheapest['market_type'],
                market_sell     = dearest['market_type'],
                risk            = risk,
                confidence      = conf,
                description     = (
                    f"Comprar {code} en {cheapest['market_type']} "
                    f"a {float(buy_price):.4f} BOB, "
                    f"vender en {dearest['market_type']} "
                    f"a {float(sell_price):.4f} BOB{scale_note}. "
                    f"Ganancia: {profit_pct:.1f}% por operación."
                ),
            ))

        return opps

    # ------------------------------------------------------------------ #
    #  2. Spread margin: rentabilidad propia por divisa                   #
    # ------------------------------------------------------------------ #

    def _detect_spread_margin(
        self, rates: dict[str, list[dict]]
    ) -> list[ArbitrageOpportunity]:
        """
        Calcula el margen (spread) de cada divisa en su mejor mercado.
        Señala divisas con spread excepcional (> media + 1.5σ).
        """
        opps = []

        spreads = []
        for code, sources in rates.items():
            best = self._best_source(sources)
            if best['buy'] > 0:
                spreads.append(float((best['sell'] - best['buy']) / best['buy'] * 100))

        if not spreads:
            return []

        avg_spread = sum(spreads) / len(spreads)
        variance   = sum((s - avg_spread) ** 2 for s in spreads) / len(spreads)
        sigma      = variance ** 0.5
        threshold  = avg_spread + 1.5 * sigma

        for code, sources in rates.items():
            best      = self._best_source(sources)
            buy       = best['buy']
            sell      = best['sell']
            if buy <= 0:
                continue
            profit    = sell - buy
            pct       = float(profit / buy * 100)

            if pct < threshold:
                continue

            scale = best['scale']
            opps.append(ArbitrageOpportunity(
                opp_type        = 'spread_margin',
                currency        = code,
                currency_via    = '',
                buy_at          = buy,
                sell_at         = sell,
                profit_per_unit = profit,
                profit_pct      = pct,
                scale_factor    = scale,
                buy_source      = best['source'],
                sell_source     = best['source'],
                market_buy      = best['market_type'],
                market_sell     = best['market_type'],
                risk            = 'LOW',
                confidence      = best['confidence'],
                description     = (
                    f"{code} tiene spread de {pct:.1f}% — "
                    f"{pct - avg_spread:.1f}pp por encima del promedio ({avg_spread:.1f}%). "
                    f"Priorizar operaciones con esta divisa hoy."
                ),
            ))

        return opps

    # ------------------------------------------------------------------ #
    #  3. Triangular: ruta indirecta A→C→B vs A→B directo                #
    # ------------------------------------------------------------------ #

    def _detect_triangular(
        self, rates: dict[str, list[dict]]
    ) -> list[ArbitrageOpportunity]:
        """
        Busca rutas A→C→BOB vs A→BOB directamente.
        Ej: vender USD para comprar CLP, luego vender CLP por BOB.

        Para que sea arbitraje real: BOB_via_C > BOB_directo
        """
        opps = []

        # Necesitamos tasas en BOB de todas las divisas
        bob_rates: dict[str, dict] = {}
        for code, sources in rates.items():
            best = self._best_source(sources)
            if best['buy'] > 0:
                bob_rates[code] = best

        currencies = list(bob_rates.keys())

        for a in currencies:
            rate_a = bob_rates[a]
            # Precio directo: sell USD → BOB (cliente vende USD, casa compra)
            bob_per_a = rate_a['buy']    # por scale_a unidades
            scale_a   = rate_a['scale']

            for c in currencies:
                if c == a:
                    continue
                rate_c = bob_rates[c]
                scale_c = rate_c['scale']

                # Ruta: a → BOB → c → BOB
                # 1. Compro a al precio sell (pago BOB)
                # 2. Con ese A compro C al precio de mercado
                # 3. Vendo C por BOB

                # a → c: usando tasas cruzadas
                # cross_rate_a_to_c = sell_a / buy_c (por unidades normalizadas)
                buy_a_per_unit  = rate_a['sell'] / Decimal(str(scale_a))    # BOB por 1 a
                sell_c_per_unit = rate_c['buy']  / Decimal(str(scale_c))    # BOB por 1 c

                if sell_c_per_unit <= 0:
                    continue

                # ¿Cuántas C obtengo por 1 A?
                c_per_a = buy_a_per_unit / sell_c_per_unit

                # ¿Cuántos BOB obtengo vendiendo esas C?
                bob_via_c_per_a = c_per_a * (rate_c['sell'] / Decimal(str(scale_c)))

                # BOB directo por 1 A (usando buy rate — casa compra A del cliente)
                bob_direct_per_a = rate_a['buy'] / Decimal(str(scale_a))

                if bob_via_c_per_a <= 0 or bob_direct_per_a <= 0:
                    continue

                profit_per_unit_a = bob_via_c_per_a - bob_direct_per_a
                profit_pct = float(profit_per_unit_a / bob_direct_per_a * 100)

                if profit_pct < MIN_PROFIT_PCT:
                    continue

                # Escalar profit de vuelta a scale_a
                profit_scaled = profit_per_unit_a * Decimal(str(scale_a))

                conf = min(rate_a['confidence'], rate_c['confidence']) * 0.85   # menor conf. triangular

                opps.append(ArbitrageOpportunity(
                    opp_type        = 'triangular',
                    currency        = a,
                    currency_via    = c,
                    buy_at          = bob_direct_per_a * Decimal(str(scale_a)),
                    sell_at         = bob_via_c_per_a  * Decimal(str(scale_a)),
                    profit_per_unit = profit_scaled,
                    profit_pct      = profit_pct,
                    scale_factor    = scale_a,
                    buy_source      = rate_a['source'],
                    sell_source     = rate_c['source'],
                    market_buy      = rate_a['market_type'],
                    market_sell     = rate_c['market_type'],
                    risk            = 'HIGH',
                    confidence      = conf,
                    description     = (
                        f"Ruta {a}→{c}→BOB rinde {profit_pct:.1f}% más que {a}→BOB directo. "
                        f"Directo: {float(bob_direct_per_a):.4f} BOB/{a}. "
                        f"Vía {c}: {float(bob_via_c_per_a):.4f} BOB/{a}. "
                        f"Riesgo alto — requiere liquidez en {c}."
                    ),
                ))

        return opps

    # ------------------------------------------------------------------ #
    #  Métricas de soporte para el summary                                #
    # ------------------------------------------------------------------ #

    def _currency_ranking(self, rates: dict[str, list[dict]]) -> list[dict]:
        """Ranking de divisas por spread % (más rentable primero)."""
        ranking = []
        for code, sources in rates.items():
            best = self._best_source(sources)
            buy, sell = best['buy'], best['sell']
            if buy <= 0:
                continue
            spread_pct = float((sell - buy) / buy * 100)
            profit_per_lot = float(sell - buy)

            ranking.append({
                'currency':        code,
                'buy':             float(buy),
                'sell':            float(sell),
                'spread_pct':      round(spread_pct, 2),
                'profit_per_lot':  round(profit_per_lot, 4),
                'scale_factor':    best['scale'],
                'market_type':     best['market_type'],
                'source':          best['source'],
            })
        ranking.sort(key=lambda r: r['spread_pct'], reverse=True)
        return ranking

    def _market_spread_map(self, rates: dict[str, list[dict]]) -> dict:
        """Mapa de spread medio por tipo de mercado."""
        totals: dict[str, list[float]] = {}
        for sources in rates.values():
            for s in sources:
                buy = s['buy']
                if buy > 0:
                    pct = float((s['sell'] - buy) / buy * 100)
                    totals.setdefault(s['market_type'], []).append(pct)

        return {
            market: {
                'avg_spread_pct': round(sum(vals) / len(vals), 2),
                'count': len(vals),
            }
            for market, vals in totals.items()
        }

    def _build_alerts(
        self, opps: list[ArbitrageOpportunity], rates: dict[str, list[dict]]
    ) -> list[dict]:
        """Alertas de alto nivel para mostrar en la cabecera del panel."""
        alerts = []

        high_profit = [o for o in opps if o.profit_pct >= 5.0]
        if high_profit:
            alerts.append({
                'level':   'HIGH',
                'message': f"{len(high_profit)} oportunidad(es) con ganancia ≥ 5% detectada(s).",
                'count':   len(high_profit),
            })

        triangulars = [o for o in opps if o.opp_type == 'triangular']
        if triangulars:
            alerts.append({
                'level':   'LOW',
                'message': f"{len(triangulars)} ruta(s) triangular(es) potencialmente rentable(s).",
                'count':   len(triangulars),
            })

        return alerts

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _best_source(sources: list[dict]) -> dict:
        """Selecciona la fuente con mayor confidence (preferir paralelo_digital > físico)."""
        priority = {'paralelo_digital': 5, 'paralelo_fisico_empresa': 5, 'paralelo_fisico_competencia': 4}
        return max(sources, key=lambda s: (priority.get(s['market_type'], 0), s['confidence']))

    @staticmethod
    def _risk_for_markets(market_buy: str, market_sell: str) -> RiskLevel:
        """Estima el nivel de riesgo basado en los tipos de mercado involucrados."""
        if market_buy == 'paralelo_digital' and 'paralelo_fisico' in market_sell:
            return 'MEDIUM'
        if market_buy == market_sell:
            return 'LOW'
        return 'HIGH'
