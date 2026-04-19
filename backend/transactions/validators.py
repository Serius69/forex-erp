# transactions/validators.py
"""
Validadores financieros para billetes y montos de transacciones.

Reglas de negocio:
  1. Sin decimales: amount_from y amount_to deben ser enteros cuando
     alguna de las divisas es USD (o cualquier divisa extranjera).
  2. USD billetes (BILLS):  solo billetes de 100 y 50  → monto divisible por 50.
  3. USD sueltos (SUELTOS): solo billetes de 5, 10, 20 → monto divisible por 5.
  4. USD 1 y 2 (SINGLES):   billetes de 1 y 2          → cualquier entero positivo.

Estas reglas aplican solo a transacciones en efectivo (CASH) que involucren USD.
Transferencias, QR y cheques no requieren validación de denominación.
"""
from __future__ import annotations
from decimal import Decimal

from django.core.exceptions import ValidationError

# ── Denominaciones válidas ────────────────────────────────────────────────────

DENOMINATION_BILLS   = 'BILLS'    # Billetes de 100 y 50
DENOMINATION_SUELTOS = 'SUELTOS'  # Billetes de 5, 10, 20
DENOMINATION_SINGLES = 'SINGLES'  # Billetes de 1 y 2

DENOMINATION_CHOICES = [
    (DENOMINATION_BILLS,   'Billetes grandes (100 y 50)'),
    (DENOMINATION_SUELTOS, 'Sueltos (5, 10, 20)'),
    (DENOMINATION_SINGLES, 'Unidades (1 y 2)'),
]

# Divisor mínimo por denominación (GCD de los billetes válidos)
_DENOMINATION_DIVISOR: dict[str, int] = {
    DENOMINATION_BILLS:   50,  # GCD(100, 50) = 50
    DENOMINATION_SUELTOS: 5,   # GCD(5, 10, 20) = 5
    DENOMINATION_SINGLES: 1,   # GCD(1, 2) = 1
}

# Billetes concretos permitidos (para mensajes de error)
_DENOMINATION_BILLS_LIST: dict[str, list[int]] = {
    DENOMINATION_BILLS:   [50, 100],
    DENOMINATION_SUELTOS: [5, 10, 20],
    DENOMINATION_SINGLES: [1, 2],
}

# Métodos de pago que requieren validación de denominación
CASH_PAYMENT_METHODS = {'CASH'}


# ── Función 1: Verificar que un monto es entero ───────────────────────────────

def validate_integer_amount(amount, field_name: str = 'monto') -> None:
    """
    Rechaza montos con decimales.
    Acepta int, Decimal o float; falla si el valor tiene parte fraccionaria.

    >>> validate_integer_amount(100)               # OK (int)
    >>> validate_integer_amount(Decimal('100'))    # OK
    >>> validate_integer_amount(Decimal('100.50')) # ValidationError
    >>> validate_integer_amount(100.5)             # ValidationError
    """
    d = Decimal(str(amount))
    if d != d.to_integral_value():
        raise ValidationError(
            {field_name: (
                f'El monto debe ser un número entero sin decimales. '
                f'Recibido: {amount}. '
                f'Ejemplo correcto: {int(d.to_integral_value())}'
            )}
        )


# ── Función 2: Verificar denominación de billete ─────────────────────────────

def validate_denomination(
    amount: Decimal,
    denomination_type: str,
    field_name: str = 'amount',
) -> None:
    """
    Valida que el monto sea expresable con los billetes de la denominación dada.

    BILLS   → divisible por 50  (billetes de 50 y 100)
    SUELTOS → divisible por 5   (billetes de 5, 10, 20)
    SINGLES → cualquier entero  (billetes de 1 y 2)

    >>> validate_denomination(Decimal('200'), 'BILLS')    # OK  (200 / 50 = 4)
    >>> validate_denomination(Decimal('75'), 'BILLS')     # ValidationError
    >>> validate_denomination(Decimal('15'), 'SUELTOS')   # OK  (15 / 5 = 3)
    >>> validate_denomination(Decimal('12'), 'SUELTOS')   # ValidationError
    >>> validate_denomination(Decimal('7'),  'SINGLES')   # OK
    """
    if denomination_type not in _DENOMINATION_DIVISOR:
        raise ValidationError(
            {field_name: f'Tipo de denominación desconocido: {denomination_type!r}'}
        )

    divisor    = _DENOMINATION_DIVISOR[denomination_type]
    bills_list = _DENOMINATION_BILLS_LIST[denomination_type]
    int_amount = int(amount)

    if int_amount <= 0:
        raise ValidationError({field_name: 'El monto debe ser mayor a 0.'})

    if int_amount % divisor != 0:
        bills_str = ', '.join(str(b) for b in bills_list)
        raise ValidationError(
            {field_name: (
                f'Monto USD {int_amount} no es válido para denominación '
                f'"{denomination_type}" (billetes: {bills_str}). '
                f'El monto debe ser divisible por {divisor}. '
                f'Ejemplos válidos: '
                f'{", ".join(str(int_amount - int_amount % divisor + d) for d in bills_list if int_amount - int_amount % divisor + d > 0)}'
            )}
        )


# ── Función 3: Validación completa de una transacción ────────────────────────

def validate_transaction_amounts(
    *,
    currency_from_code: str,
    currency_to_code: str,
    amount_from: Decimal,
    amount_to: Decimal,
    payment_method: str,
    denomination_type: str | None,
    transaction_type: str,
) -> None:
    """
    Punto de entrada principal — llama desde Transaction.clean() y serializer.

    Ejecuta en orden:
      1. Validación de enteros para montos en divisas extranjeras (no BOB).
      2. Validación de denominación si es efectivo USD.

    Args:
        currency_from_code: código de divisa origen (ej. 'USD', 'BOB')
        currency_to_code:   código de divisa destino
        amount_from:        monto en currency_from
        amount_to:          monto en currency_to
        payment_method:     'CASH', 'TRANSFER', etc.
        denomination_type:  'BILLS', 'SUELTOS', 'SINGLES' o None
        transaction_type:   'BUY' o 'SELL'
    """
    errors: dict[str, str] = {}

    # ── Regla 1: Sin decimales ────────────────────────────────────────────────
    # Aplica a cualquier monto en divisa extranjera (no BOB) — siempre.
    # La lógica es: en efectivo no existen centavos de USD.
    if currency_from_code != 'BOB':
        try:
            validate_integer_amount(amount_from, 'amount_from')
        except ValidationError as e:
            errors.update(e.message_dict)

    if currency_to_code != 'BOB':
        try:
            validate_integer_amount(amount_to, 'amount_to')
        except ValidationError as e:
            errors.update(e.message_dict)

    # ── Regla 2-4: Denominación de billetes ──────────────────────────────────
    # Solo aplica si: pago en efectivo AND alguna divisa es USD AND
    #                 se especificó denomination_type.
    involves_usd = (currency_from_code == 'USD' or currency_to_code == 'USD')

    if payment_method in CASH_PAYMENT_METHODS and involves_usd:
        if denomination_type is None:
            errors['denomination_type'] = (
                'Debes especificar el tipo de denominación para transacciones '
                'en efectivo USD: BILLS (100/50), SUELTOS (5/10/20) o SINGLES (1/2).'
            )
        else:
            # Determinar cuál lado es USD por código de divisa — nunca por BUY/SELL.
            # Invariante del sistema: currency_from es SIEMPRE la divisa extranjera,
            # currency_to es SIEMPRE BOB.  Aplica tanto a BUY como a SELL.
            if currency_from_code == 'USD':
                usd_amount = amount_from
                usd_field  = 'amount_from'
            else:
                # currency_to_code == 'USD'
                usd_amount = amount_to
                usd_field  = 'amount_to'

            try:
                validate_denomination(usd_amount, denomination_type, usd_field)
            except ValidationError as e:
                errors.update(e.message_dict)

    if errors:
        raise ValidationError(errors)


# ── Función auxiliar: sugerir monto válido más cercano ───────────────────────

def nearest_valid_amount(amount: int, denomination_type: str) -> dict[str, int]:
    """
    Dado un monto y denominación, retorna el monto válido más cercano
    (inferior e inferior+divisor).

    Útil para mensajes de sugerencia en el frontend.
    """
    if denomination_type not in _DENOMINATION_DIVISOR:
        return {}

    divisor  = _DENOMINATION_DIVISOR[denomination_type]
    floored  = (amount // divisor) * divisor
    ceiled   = floored + divisor if floored < amount else floored

    return {
        'floor': floored if floored > 0 else divisor,
        'ceil':  ceiled,
        'divisor': divisor,
        'denomination_type': denomination_type,
    }
