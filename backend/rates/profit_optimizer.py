"""
Auto Profit Mode — Optimizador de tasas para máximo beneficio.

Lógica de negocio de casa de cambios:
  - COMPRAMOS divisas AL cliente  → pagamos `buy_rate`  BOB por unidad
  - VENDEMOS divisas AL cliente   → cobramos `sell_rate` BOB por unidad
  - Margen por operación          = sell_rate - buy_rate (en BOB)

Objetivo:
    maximizar:  profit = sell_rate - buy_rate
    sujeto a:
        buy_rate  >= market_buy  × (1 - max_buy_discount/100)   # competitivo para comprar
        sell_rate <= market_sell × (1 + max_sell_premium/100)   # competitivo para vender
        sell_rate - buy_rate >= min_spread_bob                   # ganancia mínima garantizada
        (sell_rate - buy_rate) / buy_rate × 100 <= max_spread_pct  # tope ético/regulatorio

Solución analítica:
    buy*  = market_buy  × (1 - max_buy_discount/100)   # bajar al máximo permitido
    sell* = market_sell × (1 + max_sell_premium/100)   # subir al máximo permitido
    → Ajustar si restricciones de spread son violadas.

Variantes de efectivo (billetes físicos):
    USD_CASH_LOOSE  → descuento adicional en compra (sueltos/sencillos)
    USD_SMALL_BILLS → descuento mayor en compra (billetes de 1 y 2)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

log = logging.getLogger('kapitalya.rates.profit_optimizer')

# ── Parámetros por defecto (configurables vía kwargs) ─────────────────────────
DEFAULT_MAX_BUY_DISCOUNT_PCT  = Decimal('1.50')   # Máx. descuento en compra vs mercado
DEFAULT_MAX_SELL_PREMIUM_PCT  = Decimal('1.50')   # Máx. premium en venta vs mercado
DEFAULT_MIN_SPREAD_BOB        = Decimal('0.30')   # Spread mínimo en BOB por unidad
DEFAULT_MAX_SPREAD_PCT        = Decimal('5.00')   # Spread máximo permitido (%)
DEFAULT_MIN_COMPETITIVE_PCT   = Decimal('0.50')   # Mínimo margen sobre mercado para seguir atractivo

# Descuentos adicionales para variantes físicas de USD (penalización por liquidez baja)
CASH_VARIANT_BUY_EXTRA_DISCOUNT = {
    'USD_CASH_LOOSE':   Decimal('1.50'),  # Sueltos: +1.5% descuento adicional en compra
    'USD_SMALL_BILLS':  Decimal('3.00'),  # Billetes 1/2: +3% descuento adicional en compra
    'PEN_COINS':        Decimal('2.00'),  # Monedas PEN: +2% descuento adicional
}


def _q(val, places: str = '0.0001') -> Decimal:
    return Decimal(str(val)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


@dataclass
class OptimizationResult:
    """Resultado del optimizador de profit para una divisa."""
    currency_code:       str
    variant:             Optional[str]       # None = estándar; 'USD_CASH_LOOSE' | 'USD_SMALL_BILLS' | etc.

    # Tasas de mercado de referencia
    market_buy:          Decimal
    market_sell:         Decimal
    market_spread_pct:   Decimal

    # Tasas óptimas calculadas
    optimal_buy:         Decimal
    optimal_sell:        Decimal
    optimal_spread:      Decimal
    optimal_spread_pct:  Decimal
    optimal_profit_per_unit: Decimal         # = optimal_sell - optimal_buy

    # Parámetros usados
    buy_discount_applied_pct:  Decimal       # % de descuento efectivo sobre market_buy
    sell_premium_applied_pct:  Decimal       # % de premium efectivo sobre market_sell

    # Metadatos
    constraints_hit:     list[str] = field(default_factory=list)  # qué restricciones limitaron la solución
    source_used:         str = 'binance'
    confidence:          Decimal = Decimal('0.95')
    notes:               str = ''

    def to_dict(self) -> dict:
        return {
            'currency_code':           self.currency_code,
            'variant':                 self.variant,
            'market_buy':              float(self.market_buy),
            'market_sell':             float(self.market_sell),
            'market_spread_pct':       float(self.market_spread_pct),
            'optimal_buy':             float(self.optimal_buy),
            'optimal_sell':            float(self.optimal_sell),
            'optimal_spread':          float(self.optimal_spread),
            'optimal_spread_pct':      float(self.optimal_spread_pct),
            'optimal_profit_per_unit': float(self.optimal_profit_per_unit),
            'buy_discount_pct':        float(self.buy_discount_applied_pct),
            'sell_premium_pct':        float(self.sell_premium_applied_pct),
            'constraints_hit':         self.constraints_hit,
            'source_used':             self.source_used,
            'confidence':              float(self.confidence),
            'notes':                   self.notes,
        }


class ProfitOptimizer:
    """
    Calcula las tasas óptimas de compra y venta para maximizar el margen
    sin salir del rango competitivo del mercado paralelo boliviano.

    Uso:
        optimizer = ProfitOptimizer()
        result    = optimizer.optimize('USD')
        print(result.to_dict())

        # Con variante de efectivo
        result = optimizer.optimize('USD', variant='USD_CASH_LOOSE')
    """

    def __init__(
        self,
        max_buy_discount_pct:  Decimal = DEFAULT_MAX_BUY_DISCOUNT_PCT,
        max_sell_premium_pct:  Decimal = DEFAULT_MAX_SELL_PREMIUM_PCT,
        min_spread_bob:        Decimal = DEFAULT_MIN_SPREAD_BOB,
        max_spread_pct:        Decimal = DEFAULT_MAX_SPREAD_PCT,
    ):
        self.max_buy_discount_pct = _q(max_buy_discount_pct, '0.001')
        self.max_sell_premium_pct = _q(max_sell_premium_pct, '0.001')
        self.min_spread_bob       = _q(min_spread_bob)
        self.max_spread_pct       = _q(max_spread_pct, '0.001')

    # ── Punto de entrada principal ────────────────────────────────────────────

    def optimize(
        self,
        currency_code: str,
        variant:       Optional[str] = None,
        market_buy:    Optional[Decimal] = None,
        market_sell:   Optional[Decimal] = None,
    ) -> OptimizationResult:
        """
        Calcula tasas óptimas.

        Si market_buy/sell no se proveen, los obtiene en tiempo real desde
        Binance P2P → DolarBlue → DB paralelo_digital → BCB referencial.
        """
        currency_code = currency_code.upper()

        # 1. Obtener datos de mercado
        src_buy, src_sell, source, confidence = self._get_market_rates(
            currency_code, market_buy, market_sell
        )

        # 2. Calcular descuento/premium efectivo según variante
        buy_discount_pct  = self._effective_buy_discount(variant)
        sell_premium_pct  = self.max_sell_premium_pct

        # 3. Calcular tasas iniciales (solución óptima sin restricciones)
        opt_buy  = _q(src_buy  * (1 - buy_discount_pct  / 100))
        opt_sell = _q(src_sell * (1 + sell_premium_pct  / 100))

        constraints_hit: list[str] = []

        # 4. Verificar restricción de spread mínimo
        if opt_sell - opt_buy < self.min_spread_bob:
            # Subir sell o bajar buy para garantizar margen mínimo
            opt_sell = _q(opt_buy + self.min_spread_bob)
            constraints_hit.append('MIN_SPREAD_FORCED')
            log.debug(
                'OPTIMIZER min_spread_forced currency=%s buy=%s sell=%s min=%s',
                currency_code, opt_buy, opt_sell, self.min_spread_bob,
            )

        # 5. Verificar restricción de spread máximo
        if opt_buy > 0:
            spread_pct_check = (opt_sell - opt_buy) / opt_buy * 100
            if spread_pct_check > self.max_spread_pct:
                # Bajar sell_rate para no superar el tope
                opt_sell = _q(opt_buy * (1 + self.max_spread_pct / 100))
                constraints_hit.append('MAX_SPREAD_CAPPED')
                log.debug(
                    'OPTIMIZER max_spread_capped currency=%s sell capped to %s',
                    currency_code, opt_sell,
                )

        # 6. Calcular métricas finales
        spread      = _q(opt_sell - opt_buy)
        spread_pct  = _q(spread / opt_buy * 100, '0.001') if opt_buy > 0 else Decimal('0')
        mkt_spread_pct = _q((src_sell - src_buy) / src_buy * 100, '0.001') if src_buy > 0 else Decimal('0')

        # Descuentos/premiums reales aplicados
        eff_buy_discount = _q((src_buy - opt_buy) / src_buy * 100, '0.001') if src_buy > 0 else Decimal('0')
        eff_sell_premium = _q((opt_sell - src_sell) / src_sell * 100, '0.001') if src_sell > 0 else Decimal('0')

        notes = self._generate_notes(currency_code, variant, constraints_hit, spread_pct)

        log.info(
            'OPTIMIZER_RESULT currency=%s variant=%s buy=%s sell=%s spread=%.2f%% '
            'profit_per_unit=%s source=%s constraints=%s',
            currency_code, variant or 'std',
            opt_buy, opt_sell, float(spread_pct), spread, source, constraints_hit,
        )

        return OptimizationResult(
            currency_code             = currency_code,
            variant                   = variant,
            market_buy                = src_buy,
            market_sell               = src_sell,
            market_spread_pct         = mkt_spread_pct,
            optimal_buy               = opt_buy,
            optimal_sell              = opt_sell,
            optimal_spread            = spread,
            optimal_spread_pct        = spread_pct,
            optimal_profit_per_unit   = spread,
            buy_discount_applied_pct  = eff_buy_discount,
            sell_premium_applied_pct  = eff_sell_premium,
            constraints_hit           = constraints_hit,
            source_used               = source,
            confidence                = _q(confidence, '0.001'),
            notes                     = notes,
        )

    def optimize_all(
        self,
        include_variants: bool = True,
    ) -> dict[str, OptimizationResult]:
        """
        Calcula tasas óptimas para todas las divisas activas.
        Incluye variantes físicas de USD si include_variants=True.

        Retorna dict: {currency_code: OptimizationResult, ...}
        """
        from rates.models import Currency

        currencies = Currency.objects.filter(
            is_active=True,
            use_exchange_rate=True,
        ).exclude(code='BOB')

        results: dict[str, OptimizationResult] = {}

        for cur in currencies:
            try:
                results[cur.code] = self.optimize(cur.code)
            except Exception as exc:
                log.warning('OPTIMIZER_SKIP currency=%s error=%s', cur.code, exc)

        # Variantes de USD (efectivo físico)
        if include_variants and 'USD' in results:
            usd_ref = results['USD']
            for variant_code in ('USD_CASH_LOOSE', 'USD_SMALL_BILLS'):
                try:
                    results[variant_code] = self.optimize(
                        'USD',
                        variant=variant_code,
                        market_buy=usd_ref.market_buy,
                        market_sell=usd_ref.market_sell,
                    )
                except Exception as exc:
                    log.warning('OPTIMIZER_VARIANT_SKIP variant=%s error=%s', variant_code, exc)

        if 'PEN' in results:
            try:
                results['PEN_COINS'] = self.optimize(
                    'PEN',
                    variant='PEN_COINS',
                    market_buy=results['PEN'].market_buy,
                    market_sell=results['PEN'].market_sell,
                )
            except Exception as exc:
                log.warning('OPTIMIZER_VARIANT_SKIP variant=PEN_COINS error=%s', exc)

        return results

    # ── Obtención de tasas de mercado ─────────────────────────────────────────

    def _get_market_rates(
        self,
        currency_code: str,
        market_buy:    Optional[Decimal],
        market_sell:   Optional[Decimal],
    ) -> tuple[Decimal, Decimal, str, Decimal]:
        """
        Retorna (buy, sell, source_name, confidence) desde la mejor fuente disponible.
        Cascada: parámetros → Binance P2P → DolarBlue → DB → BCB ref.
        """
        # Tasas provistas directamente
        if market_buy is not None and market_sell is not None:
            return _q(market_buy), _q(market_sell), 'direct', Decimal('1.000')

        # Solo para USD/USDT usamos Binance P2P
        if currency_code == 'USD':
            result = self._try_binance_p2p()
            if result:
                return result

        # DB: mejor tasa paralelo_digital activa
        result = self._try_db_parallel(currency_code)
        if result:
            return result


        raise ValueError(f'Sin datos de mercado disponibles para {currency_code}')

    def _try_binance_p2p(self) -> Optional[tuple[Decimal, Decimal, str, Decimal]]:
        try:
            from rates.fetchers.binance_p2p import fetch_binance_p2p
            data = fetch_binance_p2p()
            buy  = _q(data['buy'])
            sell = _q(data['sell'])
            if buy > 0 and sell > 0 and buy <= sell:
                return buy, sell, 'binance', Decimal('0.950')
        except Exception as exc:
            log.debug('OPTIMIZER_BINANCE_FAIL %s', exc)
        return None

    def _try_db_parallel(self, currency_code: str) -> Optional[tuple[Decimal, Decimal, str, Decimal]]:
        try:
            from rates.models import Currency, ExchangeRate
            from django.utils import timezone
            from datetime import timedelta

            usd_code = currency_code.split('_')[0]  # USD_CASH_LOOSE → USD
            cur = Currency.objects.get(code=usd_code)
            bob = Currency.objects.get(code='BOB')
            cutoff = timezone.now() - timedelta(minutes=60)

            rate = (ExchangeRate.objects
                    .filter(
                        currency_from=cur,
                        currency_to=bob,
                        market_type__in=('paralelo_digital', 'paralelo_fisico_empresa'),
                        valid_from__gte=cutoff,
                    )
                    .order_by('-confidence', '-valid_from')
                    .first())
            if rate:
                return (
                    _q(rate.buy_rate), _q(rate.sell_rate),
                    f'db_{rate.source or rate.market_type}',
                    _q(rate.confidence, '0.001'),
                )
        except Exception as exc:
            log.debug('OPTIMIZER_DB_FAIL currency=%s %s', currency_code, exc)
        return None

    # ── Descuento efectivo por variante ──────────────────────────────────────

    def _effective_buy_discount(self, variant: Optional[str]) -> Decimal:
        """
        Descuento total en compra = base + extra por variante de efectivo.
        Mayor descuento → pagamos menos al cliente por esa divisa.
        """
        extra = CASH_VARIANT_BUY_EXTRA_DISCOUNT.get(variant or '', Decimal('0'))
        total = self.max_buy_discount_pct + extra
        # Tope de seguridad: no más del 10% de descuento (extremo)
        return min(total, Decimal('10.0'))

    # ── Generación de notas ───────────────────────────────────────────────────

    def _generate_notes(
        self,
        currency_code: str,
        variant: Optional[str],
        constraints_hit: list[str],
        spread_pct: Decimal,
    ) -> str:
        parts = []

        if variant == 'USD_CASH_LOOSE':
            parts.append(
                'USD Sueltos/Sencillos: descuento adicional en compra por menor liquidez '
                'de denominaciones pequeñas (5, 10 USD).'
            )
        elif variant == 'USD_SMALL_BILLS':
            parts.append(
                'Billetes USD 1 y 2: descuento mayor en compra — difíciles de '
                'recolocar en el mercado boliviano, alta fricción de cambio.'
            )
        elif variant == 'PEN_COINS':
            parts.append(
                'Monedas PEN: descuento adicional en compra por costo de '
                'manejo y menor aceptación en mercado regional.'
            )

        if 'MIN_SPREAD_FORCED' in constraints_hit:
            parts.append(
                f'Margen mínimo garantizado aplicado para mantener rentabilidad.'
            )
        if 'MAX_SPREAD_CAPPED' in constraints_hit:
            parts.append(
                f'Spread recortado al máximo permitido ({float(self.max_spread_pct):.1f}%) '
                f'para mantener competitividad.'
            )

        if not parts:
            parts.append(
                f'Tasa óptima calculada. Spread efectivo: {float(spread_pct):.2f}%.'
            )

        return ' '.join(parts)


# ── Función de conveniencia ───────────────────────────────────────────────────

def get_optimal_rates(
    currency_code: str = 'USD',
    variant:       Optional[str] = None,
    **kwargs,
) -> dict:
    """
    Atajo para obtener tasas óptimas en un dict serializable.

    Parámetros opcionales en kwargs:
        max_buy_discount_pct, max_sell_premium_pct, min_spread_bob, max_spread_pct
    """
    optimizer = ProfitOptimizer(
        max_buy_discount_pct = Decimal(str(kwargs.get('max_buy_discount_pct', DEFAULT_MAX_BUY_DISCOUNT_PCT))),
        max_sell_premium_pct = Decimal(str(kwargs.get('max_sell_premium_pct', DEFAULT_MAX_SELL_PREMIUM_PCT))),
        min_spread_bob       = Decimal(str(kwargs.get('min_spread_bob',       DEFAULT_MIN_SPREAD_BOB))),
        max_spread_pct       = Decimal(str(kwargs.get('max_spread_pct',       DEFAULT_MAX_SPREAD_PCT))),
    )
    result = optimizer.optimize(currency_code, variant=variant)
    return result.to_dict()
