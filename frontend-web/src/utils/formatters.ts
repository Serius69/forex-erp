// utils/formatters.ts
export const formatCurrency = (
  amount: number | string | undefined,
  currency: string | boolean = 'BOB'  // acepta boolean por compatibilidad
): string => {
  if (amount === undefined || amount === null) return 'Bs. 0.00';
  const num      = typeof amount === 'string' ? parseFloat(amount) : amount;
  const currCode = typeof currency === 'boolean' ? 'BOB' : currency;
  return new Intl.NumberFormat('es-BO', {
    style:                 'currency',
    currency:              currCode,
    minimumFractionDigits: 2,
  }).format(num);
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
  date: string | Date | undefined,
  formatStr = 'dd/MM/yyyy'
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