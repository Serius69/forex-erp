"""
Servicio de precios para variantes físicas de divisas.

En el mercado paralelo boliviano las casas de cambio aplican
descuentos diferenciados según la condición física del billete:

  USD (estándar)      → billetes 20/50/100 en buen estado
  USD_CASH_LOOSE      → sueltos/sencillos (5, 10 USD) — menor liquidez
  USD_SMALL_BILLS     → billetes 1 y 2 USD — muy difíciles de recolocar
  PEN_COINS           → monedas sol peruano — menor aceptación
  PEN (estándar)      → billetes PEN en buen estado

Lógica:
  - Sell rate = IGUAL al estándar (al cliente le cobramos igual)
  - Buy rate  = MENOR que el estándar (al cliente le pagamos menos)
  El descuento refleja el costo extra de manejar divisas de baja liquidez.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

log = logging.getLogger('kapitalya.rates.cash_variants')


def _q(val, places: str = '0.0001') -> Decimal:
    return Decimal(str(val)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


# ── Configuración de variantes ────────────────────────────────────────────────
# buy_discount_pct: cuánto menos pagamos al cliente respecto al estándar
# sell_premium_pct: cuánto más cobramos al cliente (normalmente 0)
# description:      texto para el operador
VARIANT_CONFIG: dict[str, dict] = {
    # USD_LOOSE: billetes 5, 10, 20 — menor liquidez
    # buy = USD_buy - 0.30 BOB (absolute deduction per spec)
    'USD_LOOSE': {
        'base_currency':      'USD',
        'buy_deduct_bob':     Decimal('0.30'),   # absolute BOB deduction on buy
        'sell_add_bob':       Decimal('0.00'),   # sell = same as standard
        'buy_discount_pct':   None,              # not used — absolute mode
        'sell_premium_pct':   Decimal('0.00'),
        'name_es':            'USD Sueltos (5, 10, 20)',
        'description':        (
            'Billetes USD de denominación baja (5, 10, 20). '
            'Compra 0.30 BOB menos que USD estándar.'
        ),
        'icon':               '💵',
    },
    # USD_SMALL: billetes 1, 2 — muy difíciles de recolocar
    # buy = USD_buy - 0.60 BOB (absolute deduction per spec)
    'USD_SMALL': {
        'base_currency':      'USD',
        'buy_deduct_bob':     Decimal('0.60'),   # absolute BOB deduction on buy
        'sell_add_bob':       Decimal('0.00'),
        'buy_discount_pct':   None,
        'sell_premium_pct':   Decimal('0.00'),
        'name_es':            'USD Billetes 1 y 2',
        'description':        (
            'Billetes USD de 1 y 2 dólares. '
            'Compra 0.60 BOB menos que USD estándar.'
        ),
        'icon':               '🪙',
    },
    # PEN_COINS: monedas sol peruano — menor aceptación (wider spread)
    'PEN_COINS': {
        'base_currency':      'PEN',
        'buy_deduct_bob':     Decimal('0.10'),   # absolute deduction
        'sell_add_bob':       Decimal('0.05'),   # slight premium on sell
        'buy_discount_pct':   None,
        'sell_premium_pct':   Decimal('0.00'),
        'name_es':            'PEN Monedas',
        'description':        (
            'Monedas sol peruano. '
            'Spread mayor por menor aceptación regional.'
        ),
        'icon':               '🪙',
    },
    # Legacy aliases — keep for backward compatibility
    'USD_CASH_LOOSE': {
        'base_currency':      'USD',
        'buy_deduct_bob':     Decimal('0.30'),
        'sell_add_bob':       Decimal('0.00'),
        'buy_discount_pct':   None,
        'sell_premium_pct':   Decimal('0.00'),
        'name_es':            'USD Sueltos / Sencillos (legacy)',
        'description':        'Legacy alias for USD_LOOSE.',
        'icon':               '💵',
    },
    'USD_SMALL_BILLS': {
        'base_currency':      'USD',
        'buy_deduct_bob':     Decimal('0.60'),
        'sell_add_bob':       Decimal('0.00'),
        'buy_discount_pct':   None,
        'sell_premium_pct':   Decimal('0.00'),
        'name_es':            'USD Billetes 1 y 2 (legacy)',
        'description':        'Legacy alias for USD_SMALL.',
        'icon':               '🪙',
    },
}

# Todos los códigos que son "variantes" (no divisas ISO independientes)
VARIANT_CODES = set(VARIANT_CONFIG.keys())


@dataclass
class CashVariantRate:
    """Tasa de cambio calculada para una variante física."""
    variant_code:     str
    base_code:        str              # código ISO base (USD, PEN, etc.)
    name_es:          str
    description:      str
    icon:             str

    # Referencia del estándar
    std_buy_rate:     Decimal
    std_sell_rate:    Decimal

    # Tasas de la variante (ajustadas)
    buy_rate:         Decimal
    sell_rate:        Decimal
    avg_rate:         Decimal
    spread:           Decimal
    spread_pct:       Decimal

    # Descuento aplicado
    buy_discount_pct: Decimal
    buy_discount_bob: Decimal         # diferencia absoluta en BOB

    # Metadata
    source_method:    str = 'MANUAL'
    confidence:       Decimal = Decimal('0.900')
    notes:            str = ''

    def to_dict(self) -> dict:
        return {
            'variant_code':     self.variant_code,
            'base_code':        self.base_code,
            'name_es':          self.name_es,
            'description':      self.description,
            'icon':             self.icon,
            'std_buy_rate':     float(self.std_buy_rate),
            'std_sell_rate':    float(self.std_sell_rate),
            'buy_rate':         float(self.buy_rate),
            'sell_rate':        float(self.sell_rate),
            'avg_rate':         float(self.avg_rate),
            'spread':           float(self.spread),
            'spread_pct':       float(self.spread_pct),
            'buy_discount_pct': float(self.buy_discount_pct),
            'buy_discount_bob': float(self.buy_discount_bob),
            'source_method':    self.source_method,
            'confidence':       float(self.confidence),
            'notes':            self.notes,
        }


class CashVariantService:
    """
    Calcula y persiste tasas para variantes físicas de divisas.

    Uso:
        service = CashVariantService()
        rates = service.calculate_all()          # → dict[code, CashVariantRate]
        service.save_to_db(rates)                # → guarda en ExchangeRate
    """

    def calculate(
        self,
        variant_code: str,
        std_buy_rate: Optional[Decimal] = None,
        std_sell_rate: Optional[Decimal] = None,
    ) -> CashVariantRate:
        """
        Calcula la tasa para una variante.
        Si std_buy/sell no se proveen, los obtiene desde la DB.
        """
        config = VARIANT_CONFIG.get(variant_code)
        if not config:
            raise ValueError(f'Variante desconocida: {variant_code}. Conocidas: {list(VARIANT_CONFIG)}')

        base_code = config['base_currency']

        # Obtener tasas base si no se pasaron
        if std_buy_rate is None or std_sell_rate is None:
            std_buy_rate, std_sell_rate = self._get_standard_rates(base_code)

        sell_premium_pct = config.get('sell_premium_pct', Decimal('0.00'))

        # Tasa compra: descuento absoluto en BOB (spec: USD_LOOSE -0.30, USD_SMALL -0.60)
        buy_deduct_bob = config.get('buy_deduct_bob')
        sell_add_bob   = config.get('sell_add_bob', Decimal('0.00'))

        if buy_deduct_bob is not None:
            # Absolute BOB deduction (spec-compliant)
            variant_buy  = _q(std_buy_rate  - buy_deduct_bob)
            variant_sell = _q(std_sell_rate + sell_add_bob)
        else:
            # Percentage discount (legacy path)
            buy_discount_pct = config.get('buy_discount_pct', Decimal('0.00'))
            variant_buy  = _q(std_buy_rate  * (1 - buy_discount_pct  / 100))
            variant_sell = _q(std_sell_rate * (1 + sell_premium_pct / 100))

        # Asegurar buy < sell
        if variant_buy >= variant_sell:
            variant_sell = _q(variant_buy * Decimal('1.005'))

        spread      = _q(variant_sell - variant_buy)
        spread_pct  = _q(spread / variant_buy * 100, '0.001') if variant_buy > 0 else Decimal('0')
        avg_rate    = _q((variant_buy + variant_sell) / 2)
        discount_bob = _q(std_buy_rate - variant_buy)

        if buy_deduct_bob is not None:
            notes = (
                f"Compra {float(buy_deduct_bob):.2f} BOB menos que {base_code} estándar "
                f"({float(std_buy_rate):.2f} → {float(variant_buy):.2f} BOB/unidad)."
            )
        else:
            notes = (
                f"Compra a {float(buy_discount_pct):.1f}% menos que {base_code} estándar "
                f"({float(std_buy_rate):.4f} → {float(variant_buy):.4f} BOB). "
                f"Diferencia: {float(discount_bob):.4f} BOB."
            )

        log.info(
            'CASH_VARIANT_CALC variant=%s base=%s std_buy=%s variant_buy=%s '
            'discount=%.1f%% spread=%.2f%%',
            variant_code, base_code, std_buy_rate, variant_buy,
            float(buy_discount_pct), float(spread_pct),
        )

        return CashVariantRate(
            variant_code     = variant_code,
            base_code        = base_code,
            name_es          = config['name_es'],
            description      = config['description'],
            icon             = config['icon'],
            std_buy_rate     = _q(std_buy_rate),
            std_sell_rate    = _q(std_sell_rate),
            buy_rate         = variant_buy,
            sell_rate        = variant_sell,
            avg_rate         = avg_rate,
            spread           = spread,
            spread_pct       = spread_pct,
            buy_discount_pct = buy_discount_pct,
            buy_discount_bob = discount_bob,
            notes            = notes,
        )

    def calculate_all(self) -> dict[str, CashVariantRate]:
        """Calcula todas las variantes definidas."""
        results: dict[str, CashVariantRate] = {}
        for code in VARIANT_CONFIG:
            try:
                results[code] = self.calculate(code)
            except Exception as exc:
                log.warning('CASH_VARIANT_SKIP code=%s error=%s', code, exc)
        return results

    def save_to_db(self, rates: dict[str, CashVariantRate]) -> int:
        """
        Guarda las tasas de variantes en ExchangeRate como market_type='paralelo_fisico_empresa'.
        Registra source_method='MANUAL' porque son precios de política interna.
        """
        from django.utils import timezone
        from rates.models import Currency, ExchangeRate

        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            log.error('CASH_VARIANT_SAVE_FAIL BOB currency missing')
            return 0

        saved = 0
        now = timezone.now()

        for variant_code, rate in rates.items():
            # Buscar o usar la divisa base (USD, PEN, etc.)
            base_currency = Currency.objects.filter(code=rate.base_code).first()
            if not base_currency:
                log.warning('CASH_VARIANT_SAVE_SKIP no currency for base=%s', rate.base_code)
                continue

            # Cerrar registro anterior del mismo "source" de variante
            ExchangeRate.objects.filter(
                currency_from=base_currency,
                currency_to=bob,
                market_type='paralelo_fisico_empresa',
                source=variant_code,
                valid_until__isnull=True,
            ).update(valid_until=now)

            try:
                ExchangeRate.objects.create(
                    currency_from = base_currency,
                    currency_to   = bob,
                    market_type   = 'paralelo_fisico_empresa',
                    source        = variant_code,
                    buy_rate      = rate.buy_rate,
                    sell_rate     = rate.sell_rate,
                    avg_rate      = rate.avg_rate,
                    official_rate = rate.std_buy_rate,
                    valid_from    = now,
                    valid_until   = None,
                    source_method = 'MANUAL',
                    source_url    = None,
                    fetched_at    = now,
                    confidence    = rate.confidence,
                    is_validated  = True,
                )
                saved += 1
                log.info(
                    'CASH_VARIANT_SAVED variant=%s buy=%s sell=%s',
                    variant_code, rate.buy_rate, rate.sell_rate,
                )
            except Exception as exc:
                log.error('CASH_VARIANT_SAVE_ERROR variant=%s error=%s', variant_code, exc)

        return saved

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_standard_rates(self, currency_code: str) -> tuple[Decimal, Decimal]:
        """Obtiene tasas estándar desde la DB (mejor fuente disponible)."""
        from rates.models import Currency, ExchangeRate
        from django.utils import timezone
        from datetime import timedelta

        try:
            cur = Currency.objects.get(code=currency_code)
            bob = Currency.objects.get(code='BOB')
            cutoff = timezone.now() - timedelta(hours=2)

            rate = (ExchangeRate.objects
                    .filter(
                        currency_from=cur,
                        currency_to=bob,
                        valid_until__isnull=True,
                        valid_from__gte=cutoff,
                    )
                    .exclude(source__in=list(VARIANT_CODES))
                    .order_by('-confidence', '-valid_from')
                    .first())

            if rate:
                return _q(rate.buy_rate), _q(rate.sell_rate)

            # Si no hay dato reciente, usar el más reciente sin restricción de tiempo
            rate = (ExchangeRate.objects
                    .filter(
                        currency_from=cur,
                        currency_to=bob,
                        valid_until__isnull=True,
                    )
                    .exclude(source__in=list(VARIANT_CODES))
                    .order_by('-valid_from')
                    .first())
            if rate:
                return _q(rate.buy_rate), _q(rate.sell_rate)

        except Exception as exc:
            log.warning('CASH_VARIANT_STDRATE_FAIL currency=%s error=%s', currency_code, exc)

        raise ValueError(f'No hay tasa estándar disponible para {currency_code}')
