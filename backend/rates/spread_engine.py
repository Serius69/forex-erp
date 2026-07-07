# rates/spread_engine.py
"""
Motor de spreads dinámicos para casa de cambio.

Formula:
    spread_final = spread_base
                   × factor_inventario
                   × factor_volatilidad
                   × factor_volumen
                   × factor_hora
                   × factor_cliente
                   × factor_monto

    Resultado clampado entre spread_minimo y spread_maximo (configurables).

Factores:
    factor_inventario  : reducir buy si largo en divisa, reducir sell si corto
    factor_volatilidad : ampliar spread si alta volatilidad
    factor_volumen     : reducir si alto volumen (descuento por volumen)
    factor_hora        : ampliar fuera de horario pico
    factor_cliente     : reducir para clientes frecuentes o tier alto
    factor_monto       : reducir para montos grandes (wholesale)
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from datetime import time

from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger('rates.spread')

# ── Tipos de salida ────────────────────────────────────────────────────────────

@dataclass
class SpreadResult:
    buy_rate:           Decimal
    sell_rate:          Decimal
    spread_abs:         Decimal    # sell - buy en unidades absolutas
    spread_pct:         Decimal    # spread_abs / buy_rate * 100
    margin_per_1000:    Decimal    # ganancia estimada por 1000 unidades
    expires_at:         str        # ISO timestamp de expiración
    parallel_rate:      Decimal
    factors_breakdown:  dict       = field(default_factory=dict)
    recommendation:     str        = 'HOLD'   # WIDEN | NARROW | HOLD


# ── Configuración por defecto ─────────────────────────────────────────────────

_DEFAULTS = {
    'spread_base_pct':   Decimal('1.00'),   # 1.00% spread base
    'spread_min_pct':    Decimal('0.20'),   # mínimo permitido
    'spread_max_pct':    Decimal('5.00'),   # máximo permitido
    'rate_lock_minutes': 15,                # vigencia del precio
}

# Horarios pico: 9:00–12:00 y 14:00–17:00 (hora local)
_PEAK_HOURS  = [(time(9, 0), time(12, 0)), (time(14, 0), time(17, 0))]


class DynamicSpreadEngine:
    """
    Calcula buy_rate y sell_rate dinámicos basados en múltiples factores.

    Uso:
        engine = DynamicSpreadEngine()
        result = engine.calculate(
            currency='USD',
            parallel_rate=Decimal('9.80'),
            transaction_type='BUY',      # 'BUY' | 'SELL' | 'BOTH'
            branch=branch_instance,
            customer_tier='FREQUENT',    # REGULAR | FREQUENT | VIP
            transaction_size_bob=35000,
        )
    """

    # ── Configuración (cargada lazy desde DB o caché) ─────────────────────────

    def _load_config(self, currency: str) -> dict:
        """Carga la configuración de margen desde RateConfiguration si existe."""
        cache_key = f'spread_config:{currency}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        try:
            from rates.models import RateConfiguration
            cfg = RateConfiguration.objects.filter(
                currency_from__code=currency,
                currency_to__is_base_currency=True,
                is_active=True,
            ).first()
            if cfg:
                margins = cfg.get_current_margins()
                config = {
                    'spread_base_pct': (Decimal(str(margins[0])) + Decimal(str(margins[1]))) / 2,
                    'spread_min_pct':  Decimal('0.20'),
                    'spread_max_pct':  Decimal('5.00'),
                    'rate_lock_minutes': 15,
                }
            else:
                config = _DEFAULTS.copy()
        except Exception:
            config = _DEFAULTS.copy()

        cache.set(cache_key, config, 120)
        return config

    # ── Factores individuales ─────────────────────────────────────────────────

    def _factor_inventario(self, currency: str, branch, transaction_type: str) -> tuple[Decimal, str]:
        """
        Ajusta el spread según la posición de inventario:
        - Muy largo en divisa: reducir compra (factor > 1 aumenta spread de buy)
        - Muy corto en divisa: reducir venta (factor < 1 reduce spread de sell)
        """
        try:
            from inventory.models import CurrencyInventory
            inv = CurrencyInventory.objects.select_related('currency').filter(
                currency__code=currency,
                branch=branch,
            ).first()
            if not inv:
                return Decimal('1.00'), 'inventory_not_found'

            pct = float(inv.stock_level_percentage)
            if pct > 150:    # muy sobreabastecido → ampliar spread (incentivar ventas)
                factor = Decimal('1.20')
                note   = f'overstocked_{pct:.0f}pct'
            elif pct > 100:  # sobreabastecido leve
                factor = Decimal('1.08')
                note   = f'slightly_over_{pct:.0f}pct'
            elif pct < 30:   # stock muy bajo → ampliar spread (incentivar compras)
                factor = Decimal('0.90')
                note   = f'low_stock_{pct:.0f}pct'
            elif pct < 50:   # stock bajo
                factor = Decimal('0.95')
                note   = f'below_target_{pct:.0f}pct'
            else:
                factor = Decimal('1.00')
                note   = f'normal_{pct:.0f}pct'

            return factor, note
        except Exception as exc:
            log.debug('SPREAD_INVENTORY_ERR %s', exc)
            return Decimal('1.00'), 'error'

    def _factor_volatilidad(self, currency: str) -> tuple[Decimal, str]:
        """
        Amplía el spread en entornos de alta volatilidad.
        Calcula la desviación estándar de las últimas 24h de tasas.
        """
        try:
            from django.utils import timezone
            from rates.models import ExchangeRate
            since = timezone.now() - timezone.timedelta(hours=24)
            rates = list(
                ExchangeRate.objects.filter(
                    currency_from__code=currency,
                    currency_to__is_base_currency=True,
                    valid_from__gte=since,
                ).values_list('avg_rate', flat=True)
            )
            if len(rates) < 3:
                return Decimal('1.00'), 'insufficient_data'

            import statistics
            rates_f = [float(r) for r in rates if r]
            if not rates_f:
                return Decimal('1.00'), 'no_data'
            mean   = statistics.mean(rates_f)
            stdev  = statistics.stdev(rates_f)
            cv     = stdev / mean if mean else 0  # coeficiente de variación

            if cv > 0.02:
                factor = Decimal('1.30')
                note   = f'high_vol_cv_{cv:.4f}'
            elif cv > 0.01:
                factor = Decimal('1.15')
                note   = f'medium_vol_cv_{cv:.4f}'
            else:
                factor = Decimal('1.00')
                note   = f'low_vol_cv_{cv:.4f}'

            return factor, note
        except Exception as exc:
            log.debug('SPREAD_VOL_ERR %s', exc)
            return Decimal('1.00'), 'error'

    def _factor_volumen(self, currency: str, branch) -> tuple[Decimal, str]:
        """
        Reduce el spread si el volumen de las últimas 24h es alto.
        Alto volumen = mercado líquido → costo de spread menor.
        """
        try:
            from django.utils import timezone
            from transactions.models import Transaction
            from django.db.models import Sum
            since = timezone.now() - timezone.timedelta(hours=24)
            vol = Transaction.objects.filter(
                branch=branch,
                currency_from__code=currency,
                created_at__gte=since,
                status='COMPLETED',
            ).aggregate(total=Sum('amount_from'))['total'] or 0

            if vol > 500_000:
                factor = Decimal('0.85')
                note   = f'very_high_vol_{vol:,.0f}'
            elif vol > 200_000:
                factor = Decimal('0.92')
                note   = f'high_vol_{vol:,.0f}'
            elif vol > 50_000:
                factor = Decimal('0.97')
                note   = f'medium_vol_{vol:,.0f}'
            else:
                factor = Decimal('1.00')
                note   = f'low_vol_{vol:,.0f}'

            return factor, note
        except Exception as exc:
            log.debug('SPREAD_VOL_ERR %s', exc)
            return Decimal('1.00'), 'error'

    @staticmethod
    def _factor_hora() -> tuple[Decimal, str]:
        """Amplía el spread fuera de horarios pico."""
        now = timezone.localtime(timezone.now()).time()
        for start, end in _PEAK_HOURS:
            if start <= now <= end:
                return Decimal('1.00'), f'peak_{now.hour}h'
        if now < time(8, 0) or now > time(18, 30):
            return Decimal('1.25'), f'off_hours_{now.hour}h'
        return Decimal('1.08'), f'shoulder_{now.hour}h'

    @staticmethod
    def _factor_cliente(customer_tier: str) -> tuple[Decimal, str]:
        """Reduce el spread para clientes VIP o frecuentes."""
        tiers = {
            'VIP':      (Decimal('0.80'), 'tier_vip'),
            'FREQUENT': (Decimal('0.92'), 'tier_frequent'),
            'REGULAR':  (Decimal('1.00'), 'tier_regular'),
        }
        return tiers.get(customer_tier, (Decimal('1.00'), 'tier_unknown'))

    @staticmethod
    def _factor_monto(transaction_size_bob: int | None) -> tuple[Decimal, str]:
        """Descuento por monto: operaciones grandes obtienen mejor precio."""
        if not transaction_size_bob:
            return Decimal('1.00'), 'no_size'
        if transaction_size_bob > 500_000:
            return Decimal('0.75'), f'wholesale_{transaction_size_bob:,.0f}'
        if transaction_size_bob > 100_000:
            return Decimal('0.88'), f'large_{transaction_size_bob:,.0f}'
        if transaction_size_bob > 20_000:
            return Decimal('0.95'), f'medium_{transaction_size_bob:,.0f}'
        return Decimal('1.00'), f'small_{transaction_size_bob:,.0f}'

    # ── Cálculo principal ─────────────────────────────────────────────────────

    def calculate(
        self,
        currency: str,
        parallel_rate: Decimal,
        transaction_type: str = 'BOTH',
        branch=None,
        customer_tier: str = 'REGULAR',
        transaction_size_bob: int | None = None,
    ) -> SpreadResult:
        """
        Calcula buy_rate y sell_rate dinámicos para `currency`.

        Args:
            currency:            Código de divisa (USD, EUR, etc.)
            parallel_rate:       Tasa paralela de referencia
            transaction_type:    BUY | SELL | BOTH
            branch:              Instancia de Branch (para inventario y volumen)
            customer_tier:       REGULAR | FREQUENT | VIP
            transaction_size_bob: Tamaño en BOB para factor de monto
        """
        config = self._load_config(currency)
        spread_base = config['spread_base_pct'] / 100  # convertir a fracción

        # ── Factores ──────────────────────────────────────────────────────────
        f_inv,   n_inv   = self._factor_inventario(currency, branch, transaction_type)
        f_vol,   n_vol   = self._factor_volatilidad(currency)
        f_vl,    n_vl    = self._factor_volumen(currency, branch)
        f_hora,  n_hora  = self._factor_hora()
        f_cli,   n_cli   = self._factor_cliente(customer_tier)
        f_monto, n_monto = self._factor_monto(transaction_size_bob)

        # ── Spread final ──────────────────────────────────────────────────────
        spread_pct = (
            spread_base
            * f_inv * f_vol * f_vl * f_hora * f_cli * f_monto
        )

        # Clamp
        s_min = config['spread_min_pct'] / 100
        s_max = config['spread_max_pct'] / 100
        spread_pct = max(s_min, min(s_max, spread_pct))

        half_spread = parallel_rate * spread_pct / 2
        buy_rate  = (parallel_rate - half_spread).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        sell_rate = (parallel_rate + half_spread).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

        spread_abs  = sell_rate - buy_rate
        spread_pct_display = (spread_abs / buy_rate * 100).quantize(Decimal('0.0001'))
        margin_1k   = (spread_abs * 1000).quantize(Decimal('0.01'))

        # Expiración
        lock_min  = config.get('rate_lock_minutes', 15)
        expires   = (timezone.now() + timezone.timedelta(minutes=lock_min)).isoformat()

        # Recomendación
        cv_factor = float(f_vol)
        if cv_factor >= 1.15:
            recommendation = 'WIDEN'
        elif float(spread_pct / s_max) < 0.40:
            recommendation = 'NARROW'
        else:
            recommendation = 'HOLD'

        return SpreadResult(
            buy_rate=buy_rate,
            sell_rate=sell_rate,
            spread_abs=spread_abs,
            spread_pct=spread_pct_display,
            margin_per_1000=margin_1k,
            expires_at=expires,
            parallel_rate=parallel_rate,
            factors_breakdown={
                'spread_base_pct':  str(spread_base * 100),
                'f_inventario':     {'factor': str(f_inv),   'note': n_inv},
                'f_volatilidad':    {'factor': str(f_vol),   'note': n_vol},
                'f_volumen':        {'factor': str(f_vl),    'note': n_vl},
                'f_hora':           {'factor': str(f_hora),  'note': n_hora},
                'f_cliente':        {'factor': str(f_cli),   'note': n_cli},
                'f_monto':          {'factor': str(f_monto), 'note': n_monto},
                'spread_final_pct': str(spread_pct * 100),
            },
            recommendation=recommendation,
        )
