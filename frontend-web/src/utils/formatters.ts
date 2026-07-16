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
  const formatted = Math.abs(value).toFixed(2);
  
  if (showSign && value > 0) {
    return `+${formatted}%`;
  } else if (value < 0) {
    return `-${formatted}%`;
  }
  
  return `${formatted}%`;
};

export const formatCompactNumber = (value: number): string => {
  if (value >= 1000000) {
    return `${(value / 1000000).toFixed(1)}M`;
  } else if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}K`;
  }
  
  return value.toString();
};