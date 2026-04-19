/**
 * Utilidades financieras para Kapitalya ERP.
 *
 * IMPORTANTE: JavaScript usa float64 (IEEE 754) que NO es adecuado
 * para aritmética financiera. Estas funciones usan strings y formateo
 * controlado para evitar errores de redondeo en la UI.
 *
 * Toda la aritmética real se hace en el backend (Python Decimal).
 * El frontend solo formatea y valida rangos.
 */

// ── Formateo de montos ────────────────────────────────────────────────────────

/**
 * Formatea un monto en BOB para mostrar en la UI.
 * Ej: 6960.00 → "Bs. 6.960,00"
 */
export function formatBOB(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return 'Bs. 0,00';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return 'Bs. 0,00';
  return new Intl.NumberFormat('es-BO', {
    style:                 'currency',
    currency:              'BOB',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
}

/**
 * Formatea un monto en divisa extranjera (USD, EUR, etc.).
 * Usa 4 decimales para divisas (precisión de trading).
 * Ej: 1000.0000 → "1.000,0000 USD"
 */
export function formatFX(
  value: number | string | null | undefined,
  currency: string = 'USD',
  decimals: number = 4,
): string {
  if (value === null || value === undefined || value === '') return `0,0000 ${currency}`;
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return `0,0000 ${currency}`;
  return (
    new Intl.NumberFormat('es-BO', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(num) + ` ${currency}`
  );
}

/**
 * Formatea un tipo de cambio con 4 decimales.
 * Ej: 6.9600 → "6,9600"
 */
export function formatRate(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '0,0000';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return '0,0000';
  return new Intl.NumberFormat('es-BO', {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  }).format(num);
}

/**
 * Formatea un porcentaje de spread.
 * Ej: 0.8643 → "0,86%"
 */
export function formatSpread(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '0,00%';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return '0,00%';
  return new Intl.NumberFormat('es-BO', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num) + '%';
}

/**
 * Formatea cambio porcentual con signo y color implícito.
 * Retorna { text: "+2,45%", positive: true }
 */
export function formatChange(value: number | null | undefined): { text: string; positive: boolean } {
  if (value === null || value === undefined || isNaN(value)) {
    return { text: '0,00%', positive: true };
  }
  const positive = value >= 0;
  const text = (positive ? '+' : '') + new Intl.NumberFormat('es-BO', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value) + '%';
  return { text, positive };
}

// ── Validaciones de input ─────────────────────────────────────────────────────

/**
 * Valida que un monto sea un número positivo con máximo 4 decimales.
 * Retorna el error como string o null si es válido.
 */
export function validateAmount(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return 'El monto es requerido';

  const num = parseFloat(trimmed);
  if (isNaN(num)) return 'Debe ser un número válido';
  if (num <= 0) return 'El monto debe ser mayor a 0';
  if (num > 9_999_999) return 'El monto excede el límite permitido';

  const decimals = trimmed.split('.')[1];
  if (decimals && decimals.length > 4) return 'Máximo 4 decimales permitidos';

  return null;
}

/**
 * Valida que un tipo de cambio sea razonable (0.0001 - 999999).
 */
export function validateRate(value: string): string | null {
  const num = parseFloat(value);
  if (isNaN(num) || num <= 0) return 'El tipo de cambio debe ser mayor a 0';
  if (num > 999_999) return 'Tipo de cambio fuera de rango';
  return null;
}

// ── Cálculos de presentación (NO usar para valores que se envían al backend) ──

/**
 * Estima el monto resultante para mostrar en la UI mientras el usuario escribe.
 * El valor final lo calcula el backend con aritmética Decimal.
 *
 * BUY (casa compra): cliente da divisa extranjera, recibe BOB
 *   amount_to_bob = amount_from_fx * buy_rate
 * SELL (casa vende): cliente da BOB, recibe divisa extranjera
 *   amount_to_fx = amount_from_bob / sell_rate
 */
export function estimateAmountTo(
  amountFrom: number,
  rate: number,
  transactionType: 'BUY' | 'SELL',
): number {
  if (!amountFrom || !rate || rate === 0) return 0;
  const result = transactionType === 'BUY'
    ? amountFrom * rate
    : amountFrom * rate;   // SELL: misma dirección — ver TransactionService
  // Redondear a 2dp para presentación (el backend decide el valor exacto)
  return Math.round(result * 100) / 100;
}

// ── Escala de divisas ─────────────────────────────────────────────────────────

/**
 * Devuelve true si la divisa usa escala >1 (CLP, ARS → cotización por 1000 unidades).
 */
export function isScaled(scaleFactor: number): boolean {
  return scaleFactor > 1;
}

/**
 * Formato legible del factor de escala: 1000 → "1.000"
 */
export function formatScale(scaleFactor: number): string {
  return new Intl.NumberFormat('es-BO').format(scaleFactor);
}

/**
 * Calcula el monto REAL en unidades de la divisa física.
 * Ej. amount=45 bundles de CLP (scale=1000) → 45.000 CLP reales.
 */
export function realAmount(amount: number, scaleFactor: number): number {
  return amount * scaleFactor;
}

/**
 * Formatea la etiqueta de la tasa de cambio para el UI.
 * Con escala: "BOB 10,0000 / 1.000 CLP"
 * Sin escala: "BOB 9,3000"
 */
export function formatRateLabel(
  rate: number | string | null | undefined,
  currencyCode: string,
  scaleFactor: number,
): string {
  const formatted = formatRate(rate);
  if (isScaled(scaleFactor)) {
    return `${formatted} / ${formatScale(scaleFactor)} ${currencyCode}`;
  }
  return formatted;
}

/**
 * Formatea el monto de divisa extranjera con contexto de escala.
 * Con escala: "45,00 lotes (45.000 CLP)"
 * Sin escala: "45,0000 USD"
 */
export function formatFXWithScale(
  value: number | string | null | undefined,
  currencyCode: string,
  scaleFactor: number,
): string {
  if (value === null || value === undefined || value === '') {
    return isScaled(scaleFactor)
      ? `0 lotes (0 ${currencyCode})`
      : `0,0000 ${currencyCode}`;
  }
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return `0 ${currencyCode}`;

  if (!isScaled(scaleFactor)) return formatFX(num, currencyCode);

  const lotsFormatted = new Intl.NumberFormat('es-BO', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
  const realFormatted = new Intl.NumberFormat('es-BO', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(realAmount(num, scaleFactor));
  return `${lotsFormatted} lotes (${realFormatted} ${currencyCode})`;
}

// ── Utilidades de número de transacción ──────────────────────────────────────

/** Genera un Idempotency-Key UUID v4 para el header de la request. */
export function generateIdempotencyKey(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
