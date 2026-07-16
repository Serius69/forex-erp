// utils/formatters.ts
// Fuente única de formateo monetario / tasas: utils/finance.ts (es-BO, coma decimal).
// Este módulo reexporta esos helpers y mantiene utilidades de compatibilidad
// (formatNumber, formatDate, formatPercentage, formatCompactNumber) usadas por ~15 imports.
import { formatBOB } from './finance';
export { formatBOB, formatRate, formatPercent } from './finance';

export const formatCurrency = (
  amount: number | string | undefined,
  currency: string | boolean = 'BOB'  // acepta boolean por compatibilidad
): string => {
  const currCode = typeof currency === 'boolean' ? 'BOB' : currency;
  // BOB (caso mayoritario) → fuente única formatBOB (fallback 'Bs. 0,00' con coma es-BO)
  if (currCode === 'BOB') return formatBOB(amount);
  // Otras monedas: mismo locale es-BO (coma decimal), sin duplicar el fallback erróneo
  const num = amount === undefined || amount === null || amount === ''
    ? NaN
    : (typeof amount === 'string' ? parseFloat(amount) : amount);
  return new Intl.NumberFormat('es-BO', {
    style:                 'currency',
    currency:              currCode,
    minimumFractionDigits: 2,
  }).format(isNaN(num) ? 0 : num);
};

export const formatNumber = (
  value: number | string | undefined,
  decimals = 2
): string => {
  if (value === undefined || value === null) return '0';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  return new Intl.NumberFormat('es-BO', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(num);
};

export const formatDate = (
  date: string | Date | undefined
): string => {
  if (!date) return '-';
  return new Date(date).toLocaleDateString('es-BO');
};

export const formatPercentage = (value: number, showSign = true): string => {
  // Locale-aware es-BO (coma decimal), manteniendo firma y signo explícito.
  const formatted = new Intl.NumberFormat('es-BO', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));

  if (showSign && value > 0) {
    return `+${formatted}%`;
  } else if (value < 0) {
    return `-${formatted}%`;
  }

  return `${formatted}%`;
};

export const formatCompactNumber = (value: number): string => {
  // Notación compacta locale-aware es-BO → 'mil'/'M' con coma decimal (ej '1,2 M').
  if (value === undefined || value === null || isNaN(value)) return '0';
  return new Intl.NumberFormat('es-BO', {
    notation:              'compact',
    maximumFractionDigits: 1,
  }).format(value);
};