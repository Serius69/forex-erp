// Formatting and display utilities only — all real arithmetic is done by the backend (Python Decimal).

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

export function formatRate(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '0,0000';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return '0,0000';
  return new Intl.NumberFormat('es-BO', {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  }).format(num);
}

export function isScaled(scaleFactor: number): boolean {
  return scaleFactor > 1;
}

export function formatScale(scaleFactor: number): string {
  return new Intl.NumberFormat('es-BO').format(scaleFactor);
}

export function realAmount(amount: number, scaleFactor: number): number {
  return amount * scaleFactor;
}

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
