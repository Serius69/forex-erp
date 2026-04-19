"""
Utilidades de precisión financiera para Kapitalya ERP.
Todas las operaciones monetarias deben pasar por estas funciones.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, Context, setcontext

# Contexto global de precisión para operaciones financieras
FINANCIAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_UP)
setcontext(FINANCIAL_CONTEXT)

# Cuantizadores
MONEY_Q     = Decimal('0.01')    # 2 decimales para montos BOB
RATE_Q      = Decimal('0.0001')  # 4 decimales para tipos de cambio
PERCENT_Q   = Decimal('0.0001')  # 4 decimales para porcentajes
AMOUNT_Q    = Decimal('0.0001')  # 4 decimales para montos en divisa extranjera


def quantize_money(value) -> Decimal:
    """Cuantiza un valor monetario a 2 decimales (BOB)."""
    return Decimal(str(value)).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def quantize_rate(value) -> Decimal:
    """Cuantiza un tipo de cambio a 4 decimales."""
    return Decimal(str(value)).quantize(RATE_Q, rounding=ROUND_HALF_UP)


def quantize_amount(value) -> Decimal:
    """Cuantiza un monto en divisa extranjera a 4 decimales."""
    return Decimal(str(value)).quantize(AMOUNT_Q, rounding=ROUND_HALF_UP)


def quantize_percent(value) -> Decimal:
    """Cuantiza un porcentaje a 4 decimales."""
    return Decimal(str(value)).quantize(PERCENT_Q, rounding=ROUND_HALF_UP)


def calculate_amount_to(amount_from: Decimal, exchange_rate: Decimal,
                        transaction_type: str) -> Decimal:
    """
    Calcula el monto resultante con precisión garantizada.
    BUY:  cliente entrega divisa extranjera, recibe BOB  → amount_to = amount_from * rate
    SELL: cliente entrega BOB, recibe divisa extranjera  → amount_to = amount_from / rate
    """
    amount_from   = quantize_amount(amount_from)
    exchange_rate = quantize_rate(exchange_rate)

    if transaction_type == 'BUY':
        result = amount_from * exchange_rate
    else:
        if exchange_rate == 0:
            raise ValueError("El tipo de cambio no puede ser cero")
        result = amount_from / exchange_rate

    return quantize_money(result)


def calculate_profit(amount_from: Decimal, exchange_rate: Decimal,
                     official_rate: Decimal, transaction_type: str) -> Decimal:
    """
    Calcula la ganancia real de la transacción respecto a la tasa oficial.
    Requiere la tasa oficial del BCB para cálculo exacto.
    """
    amount_from   = quantize_amount(amount_from)
    exchange_rate = quantize_rate(exchange_rate)
    official_rate = quantize_rate(official_rate)

    if transaction_type == 'BUY':
        # Casa compra a buy_rate (menor que oficial) — spread = oficial - buy
        profit_per_unit = official_rate - exchange_rate
    else:
        # Casa vende a sell_rate (mayor que oficial) — spread = sell - oficial
        profit_per_unit = exchange_rate - official_rate

    return quantize_money(profit_per_unit * amount_from)


def calculate_wac(current_balance: Decimal, current_cost: Decimal,
                  incoming_amount: Decimal, incoming_rate: Decimal) -> Decimal:
    """
    Calcula el Costo Promedio Ponderado (WAC) al agregar divisas.
    WAC = (balance_actual * costo_actual + monto_nuevo * tasa_nueva) /
          (balance_actual + monto_nuevo)
    """
    current_balance  = quantize_amount(current_balance)
    current_cost     = quantize_rate(current_cost)
    incoming_amount  = quantize_amount(incoming_amount)
    incoming_rate    = quantize_rate(incoming_rate)

    total_value    = (current_balance * current_cost) + (incoming_amount * incoming_rate)
    total_quantity = current_balance + incoming_amount

    if total_quantity == 0:
        return Decimal('0')

    return (total_value / total_quantity).quantize(RATE_Q, rounding=ROUND_HALF_UP)
