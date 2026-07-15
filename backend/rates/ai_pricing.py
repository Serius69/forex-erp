# rates/ai_pricing.py
"""
Motor de precios AI para tipo de cambio.

Fórmula:
    TC_base = (w_binance*Binance + w_dolarblue*DolarBlue + w_hist*Histórico + w_comp*Competencia)
              / sum(pesos_disponibles)

Ajustes dinámicos:
    inventory_factor:
        stock < 20% máximo  → buy_rate *= 1.020  (escasez: comprar más caro)
        stock < 40% máximo  → buy_rate *= 1.010
        stock > 80% máximo  → buy_rate *= 0.985  (exceso: bajar precio compra)

    demand_factor (últimas 4h):
        sell_count > avg_4h * 1.5  → sell_rate *= 1.010  (alta demanda)
        sell_count < avg_4h * 0.5  → sell_rate *= 0.995  (baja demanda)

    spread mínimo garantizado:
        spread_pct < MIN_SPREAD_PCT → ajustar sell_rate para mantener margen

Pesos: leídos de ExchangeRateSource.weight (normalizado a 1.0 automáticamente).
Si una fuente no tiene datos recientes (<30 min), se excluye del cálculo.
"""
from __future__ import annotations
import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Avg
from django.utils import timezone

log = logging.getLogger('kapitalya.rates.ai_pricing')

# ── Constantes configurables ──────────────────────────────────────────────────
MIN_SPREAD_PCT    = Decimal('0.30')   # Spread mínimo para no operar en pérdida
DEFAULT_BUY_MARGIN = Decimal('0.985') # TC_base * este factor = buy_rate
DEFAULT_SELL_MARGIN = Decimal('1.015') # TC_base * este factor = sell_rate
STALE_MINUTES     = 30                # Datos > X min = excluidos del promedio ponderado
DEMAND_WINDOW_HRS = 4                 # Ventana para medir demanda reciente


def _q(val, places: str = '0.0001') -> Decimal:
    return Decimal(str(val)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


class AIPricingEngine:
    """
    Motor de pricing que combina múltiples fuentes y aplica ajustes dinámicos.

    Uso:
        engine = AIPricingEngine()
        result = engine.calculate('USD', branch=my_branch)
        decision = engine.save_decision(result, branch=my_branch)
    """

    def __init__(self):
        self._source_weights: dict | None = None

    # ── Pesos de fuentes ──────────────────────────────────────────────────────

    def _get_source_weights(self) -> dict[str, Decimal]:
        """
        Lee pesos de ExchangeRateSource activas.
        Retorna dict: {source_type: weight_normalized}
        """
        if self._source_weights is not None:
            return self._source_weights

        from rates.models import ExchangeRateSource
        sources = ExchangeRateSource.objects.filter(is_active=True)
        raw: dict[str, Decimal] = {}
        for s in sources:
            if s.source_type not in raw:
                raw[s.source_type] = Decimal('0')
            raw[s.source_type] = max(raw[s.source_type], Decimal(str(s.weight)))

        # Mapeo: source_type → componente del motor
        mapping = {
            'digital':  'binance',    # Binance/Takenos/Airtm son "digital"
            'parallel': 'dolarblue',  # Mercado paralelo (DolarBlue Bolivia)
            'paralelo_digital': 'dolarblue',
        }
        result: dict[str, Decimal] = {'binance': Decimal('0'), 'dolarblue': Decimal('0'),
                                       'historical': Decimal('0.25'), 'competition': Decimal('0')}
        for st, w in raw.items():
            component = mapping.get(st)
            if component:
                result[component] = max(result[component], w)

        # Normalizar a suma = 1.0
        total = sum(result.values())
        if total > 0:
            result = {k: _q(v / total, '0.0001') for k, v in result.items()}
        else:
            result = {'binance': Decimal('0.40'), 'dolarblue': Decimal('0.35'),
                      'historical': Decimal('0.15'), 'competition': Decimal('0.10')}

        self._source_weights = result
        return result

    # ── Obtener tasas de cada fuente ──────────────────────────────────────────

    def _get_rate_dolarblue(self, currency_code: str) -> Decimal | None:
        """Última tasa del mercado paralelo digital (DolarBlue Bolivia / Binance)."""
        from rates.models import ExchangeRate, Currency
        try:
            bob = Currency.objects.get(code='BOB')
            cur = Currency.objects.get(code=currency_code)
            cutoff = timezone.now() - timedelta(minutes=STALE_MINUTES)
            rate = (ExchangeRate.objects
                    .filter(currency_from=cur, currency_to=bob,
                            market_type__in=('paralelo_digital', 'parallel'),
                            valid_from__gte=cutoff)
                    .order_by('-valid_from')
                    .first())
            if rate:
                return _q(rate.sell_rate)
        except Exception as exc:
            log.debug('DolarBlue rate lookup failed for %s: %s', currency_code, exc)
        return None

    def _get_rate_binance(self, currency_code: str) -> Decimal | None:
        """Última tasa digital (Binance P2P / Takenos)."""
        from rates.models import ExchangeRate, Currency
        try:
            bob = Currency.objects.get(code='BOB')
            cur = Currency.objects.get(code=currency_code)
            cutoff = timezone.now() - timedelta(minutes=STALE_MINUTES)
            rate = (ExchangeRate.objects
                    .filter(currency_from=cur, currency_to=bob,
                            market_type__in=('paralelo_digital', 'digital'),
                            valid_from__gte=cutoff)
                    .order_by('-valid_from')
                    .first())
            if rate:
                return _q(rate.sell_rate)
        except Exception as exc:
            log.debug('Binance rate lookup failed for %s: %s', currency_code, exc)
        return None

    def _get_rate_historical(self, currency_code: str, days: int = 7) -> Decimal | None:
        """Promedio de tasas de los últimos N días (paralelo físico empresa)."""
        from rates.models import ExchangeRate, Currency
        try:
            bob = Currency.objects.get(code='BOB')
            cur = Currency.objects.get(code=currency_code)
            cutoff = timezone.now() - timedelta(days=days)
            avg = (ExchangeRate.objects
                   .filter(currency_from=cur, currency_to=bob,
                           market_type__in=('paralelo_fisico_empresa', 'parallel'),
                           valid_from__gte=cutoff)
                   .aggregate(avg=Avg('sell_rate'))['avg'])
            if avg:
                return _q(avg)
        except Exception as exc:
            log.debug('Historical rate failed for %s: %s', currency_code, exc)
        return None

    def _get_rate_competition(self, currency_code: str) -> Decimal | None:
        """Última tasa de competencia (paralelo_fisico_competencia)."""
        from rates.models import ExchangeRate, Currency
        try:
            bob = Currency.objects.get(code='BOB')
            cur = Currency.objects.get(code=currency_code)
            cutoff = timezone.now() - timedelta(hours=6)
            rate = (ExchangeRate.objects
                    .filter(currency_from=cur, currency_to=bob,
                            market_type='paralelo_fisico_competencia',
                            valid_from__gte=cutoff)
                    .order_by('-valid_from')
                    .first())
            if rate:
                return _q(rate.sell_rate)
        except Exception as exc:
            log.debug('Competition rate failed for %s: %s', currency_code, exc)
        return None

    # ── Contexto de inventario ────────────────────────────────────────────────

    def _get_inventory_context(self, currency_code: str, branch=None) -> dict:
        """Retorna {stock, minimum, maximum, stock_pct, factor}."""
        from inventory.models import CurrencyInventory
        try:
            qs = CurrencyInventory.objects.filter(
                currency__code=currency_code,
            )
            if branch:
                qs = qs.filter(branch=branch)

            inv = qs.first()
            if not inv:
                return {'stock': None, 'minimum': None, 'maximum': None,
                        'stock_pct': None, 'factor': Decimal('1.0000')}

            stock   = inv.physical_balance + inv.digital_balance
            maximum = inv.maximum_stock or Decimal('50000')
            minimum = inv.minimum_stock or Decimal('1000')
            stock_pct = _q(stock / maximum * 100 if maximum > 0 else Decimal('50'), '0.01')

            # Calcular factor: ajuste sobre buy_rate
            factor = Decimal('1.0000')
            if stock_pct < 20:
                factor = Decimal('1.0200')   # muy bajo: comprar más caro para atraer vendedores
            elif stock_pct < 40:
                factor = Decimal('1.0100')   # bajo: leve incentivo
            elif stock_pct > 80:
                factor = Decimal('0.9850')   # exceso: bajar precio compra
            elif stock_pct > 60:
                factor = Decimal('0.9950')   # abundante: ligera baja

            return {
                'stock':     _q(stock, '0.01'),
                'minimum':   _q(minimum, '0.01'),
                'maximum':   _q(maximum, '0.01'),
                'stock_pct': stock_pct,
                'factor':    factor,
            }
        except Exception as exc:
            log.warning('Inventory context failed for %s: %s', currency_code, exc)
            return {'stock': None, 'minimum': None, 'maximum': None,
                    'stock_pct': None, 'factor': Decimal('1.0000')}

    # ── Contexto de demanda ───────────────────────────────────────────────────

    def _get_demand_context(self, currency_code: str, branch=None) -> dict:
        """Analiza transacciones recientes para detectar presión de demanda."""
        from transactions.models import Transaction
        from django.db.models import Count
        try:
            window = timezone.now() - timedelta(hours=DEMAND_WINDOW_HRS)
            qs = Transaction.objects.filter(
                currency_from__code__in=[currency_code, 'BOB'],
                currency_to__code__in=[currency_code, 'BOB'],
                created_at__gte=window,
                status='COMPLETED',
            )
            if branch:
                qs = qs.filter(branch=branch)

            # order_by() explícito: el ordering default contamina el GROUP BY
            counts = qs.values('transaction_type').order_by('transaction_type').annotate(n=Count('id'))
            buy_count  = next((c['n'] for c in counts if c['transaction_type'] == 'BUY'), 0)
            sell_count = next((c['n'] for c in counts if c['transaction_type'] == 'SELL'), 0)
            total      = buy_count + sell_count

            # Baseline: promedio histórico de las últimas 2 semanas en misma ventana horaria
            past_window = timezone.now() - timedelta(days=14)
            avg_sell = (Transaction.objects
                        .filter(transaction_type='SELL',
                                currency_from__code__in=[currency_code, 'BOB'],
                                created_at__gte=past_window, status='COMPLETED')
                        .count() / 14 / (24 / DEMAND_WINDOW_HRS))  # promedio por ventana

            # Factor sobre sell_rate
            demand_factor = Decimal('1.0000')
            if avg_sell > 0:
                ratio = sell_count / avg_sell
                if ratio > 1.5:
                    demand_factor = Decimal('1.0100')   # alta demanda: subir venta
                elif ratio > 1.2:
                    demand_factor = Decimal('1.0050')
                elif ratio < 0.5:
                    demand_factor = Decimal('0.9950')   # baja demanda: bajar venta

            return {
                'buy_count':    buy_count,
                'sell_count':   sell_count,
                'demand_ratio': round(sell_count / avg_sell, 2) if avg_sell > 0 else 1.0,
                'factor':       demand_factor,
            }
        except Exception as exc:
            log.debug('Demand context failed: %s', exc)
            return {'buy_count': 0, 'sell_count': 0, 'demand_ratio': 1.0,
                    'factor': Decimal('1.0000')}

    # ── Cálculo principal ─────────────────────────────────────────────────────

    def calculate(self, currency_code: str, branch=None) -> dict:
        """
        Calcula el TC sugerido para una divisa.

        Returns dict con:
            base_rate, suggested_buy, suggested_sell, suggested_spread_pct,
            rates_used, weights_used, inventory, demand, recommendation
        """
        weights = self._get_source_weights()

        # Obtener tasas disponibles
        rates = {
            'binance':     self._get_rate_binance(currency_code),
            'dolarblue':   self._get_rate_dolarblue(currency_code),
            'historical':  self._get_rate_historical(currency_code),
            'competition': self._get_rate_competition(currency_code),
        }

        # Calcular TC base ponderado (solo fuentes disponibles)
        total_weight = Decimal('0')
        weighted_sum = Decimal('0')
        used_weights: dict[str, Decimal] = {}

        for component, rate in rates.items():
            w = weights.get(component, Decimal('0'))
            if rate and rate > 0 and w > 0:
                weighted_sum += w * rate
                total_weight += w
                used_weights[component] = w

        if total_weight == 0 or weighted_sum == 0:
            log.warning('No source rates available for %s — using historical fallback', currency_code)
            # Fallback: usar último TC registrado
            historical = self._get_rate_historical(currency_code, days=30)
            if not historical:
                raise ValueError(f'Sin datos de tipo de cambio para {currency_code}')
            base_rate = historical
        else:
            base_rate = _q(weighted_sum / total_weight)

        # Contextos
        inv     = self._get_inventory_context(currency_code, branch)
        demand  = self._get_demand_context(currency_code, branch)

        # Aplicar ajustes
        inv_factor    = inv['factor']
        demand_factor = demand['factor']

        # buy_rate ajustado por inventario (inv_factor afecta principalmente compra)
        buy_rate  = _q(base_rate * inv_factor * DEFAULT_BUY_MARGIN)
        # sell_rate ajustado por demanda
        sell_rate = _q(base_rate * demand_factor * DEFAULT_SELL_MARGIN)

        # Garantizar spread mínimo
        spread_pct = (sell_rate - buy_rate) / buy_rate * 100 if buy_rate > 0 else Decimal('0')
        if spread_pct < MIN_SPREAD_PCT:
            # Subir sell_rate hasta garantizar el spread mínimo
            sell_rate = _q(buy_rate * (1 + MIN_SPREAD_PCT / 100))
            spread_pct = _q((sell_rate - buy_rate) / buy_rate * 100, '0.001')

        spread_bob = _q(sell_rate - buy_rate)

        # Recomendación textual
        messages = []
        if inv['stock_pct'] is not None:
            if inv['stock_pct'] < 20:
                messages.append(f'ALERTA: stock {inv["stock_pct"]}% — precio compra elevado para reponer')
            elif inv['stock_pct'] > 80:
                messages.append(f'Exceso de stock ({inv["stock_pct"]}%) — precio compra reducido')
        if demand_factor > Decimal('1.005'):
            messages.append('Alta demanda detectada — precio venta ajustado al alza')
        elif demand_factor < Decimal('1.000'):
            messages.append('Demanda baja — precio venta ligeramente reducido')
        if not messages:
            messages.append('Condiciones normales de mercado')

        return {
            'currency_code':   currency_code,
            'base_rate':       base_rate,
            'suggested_buy':   buy_rate,
            'suggested_sell':  sell_rate,
            'suggested_spread': spread_bob,
            'suggested_spread_pct': _q(spread_pct, '0.001'),
            'rates_used':      {k: str(v) for k, v in rates.items() if v},
            'weights_used':    {k: str(v) for k, v in used_weights.items()},
            'inventory_factor': inv_factor,
            'demand_factor':    demand_factor,
            'inventory':        {k: str(v) if v is not None else None for k, v in inv.items()},
            'demand':           demand,
            'recommendation':   ' | '.join(messages),
        }

    def save_decision(self, result: dict, branch=None, trigger: str = 'scheduled') -> 'ExchangeRateDecisionLog':
        """Persiste la decisión en ExchangeRateDecisionLog."""
        from rates.models import ExchangeRateDecisionLog, ExchangeRate, Currency

        rates = result['rates_used']
        weights = result['weights_used']

        # TC real actual (para comparar)
        actual_buy = actual_sell = None
        try:
            bob = Currency.objects.get(code='BOB')
            cur = Currency.objects.get(code=result['currency_code'])
            current = (ExchangeRate.objects
                       .filter(currency_from=cur, currency_to=bob,
                               market_type='paralelo_fisico_empresa')
                       .order_by('-valid_from').first())
            if current:
                actual_buy  = current.buy_rate
                actual_sell = current.sell_rate
        except Exception:
            pass

        inv  = result['inventory']
        dem  = result['demand']

        decision = ExchangeRateDecisionLog(
            currency_code    = result['currency_code'],
            branch           = branch,
            trigger          = trigger,
            # (rate_bcb/weight_bcb eliminados: el modelo ya no tiene esos campos
            #  desde que se quitaron las fuentes BCB — pasarlos rompía el save
            #  de TODA decisión → el Motor AI no registraba nada)
            rate_binance     = rates.get('binance'),
            rate_historical  = rates.get('historical'),
            rate_competition = rates.get('competition'),
            weight_binance     = weights.get('binance', '0'),
            weight_historical  = weights.get('historical', '0'),
            weight_competition = weights.get('competition', '0'),
            base_rate_bob    = result['base_rate'],
            inventory_factor = result['inventory_factor'],
            demand_factor    = result['demand_factor'],
            suggested_buy    = result['suggested_buy'],
            suggested_sell   = result['suggested_sell'],
            suggested_spread = result['suggested_spread'],
            suggested_spread_pct = result['suggested_spread_pct'],
            actual_buy       = actual_buy,
            actual_sell      = actual_sell,
            inventory_stock     = inv.get('stock'),
            inventory_minimum   = inv.get('minimum'),
            inventory_maximum   = inv.get('maximum'),
            inventory_stock_pct = inv.get('stock_pct'),
            recent_buy_count  = dem.get('buy_count', 0),
            recent_sell_count = dem.get('sell_count', 0),
            recommendation    = result['recommendation'],
        )
        decision.save()
        log.info(
            'AI pricing decision saved: %s buy=%s sell=%s spread=%.2f%% [%s]',
            result['currency_code'], result['suggested_buy'], result['suggested_sell'],
            float(result['suggested_spread_pct']), trigger,
        )
        return decision

    def suggest_and_save(self, currency_code: str, branch=None, trigger: str = 'scheduled') -> dict:
        """Calcular y guardar. Retorna el resultado completo."""
        try:
            result   = self.calculate(currency_code, branch)
            decision = self.save_decision(result, branch=branch, trigger=trigger)
            result['decision_id'] = decision.pk
            return result
        except Exception as exc:
            log.error('AIPricingEngine.suggest_and_save failed for %s: %s', currency_code, exc)
            raise
