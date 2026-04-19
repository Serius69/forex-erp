// src/components/rates/CurrencySelector.tsx
import React, { useEffect, useState, useCallback } from 'react';
import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormHelperText,
  FormControlLabel,
  Switch,
  Alert,
  Box,
  Skeleton,
  Typography,
} from '@mui/material';
import { api } from '../../services/api';

export interface CurrencyOption {
  id: number;
  code: string;
  name_en: string;
  name_es: string;
  symbol: string;
  is_active: boolean;
  use_exchange_rate: boolean;
  is_base_currency: boolean;
  scale_factor: number;
}

interface Props {
  /** Selected currency code (e.g. "USD") */
  value: string;
  onChange: (code: string, currency?: CurrencyOption) => void;
  /** Label shown above the dropdown */
  label?: string;
  /** Show the "Usar tasa de cambio" toggle */
  showRateToggle?: boolean;
  /** Controlled value for the toggle (controlled mode) */
  useRate?: boolean;
  /** Called when the toggle changes */
  onUseRateChange?: (value: boolean) => void;
  /** Additional filter: exclude base currency from the list */
  excludeBase?: boolean;
  disabled?: boolean;
  error?: boolean;
  helperText?: string;
  size?: 'small' | 'medium';
  fullWidth?: boolean;
}

const CurrencySelector: React.FC<Props> = ({
  value,
  onChange,
  label = 'Divisa',
  showRateToggle = false,
  useRate,
  onUseRateChange,
  excludeBase = false,
  disabled = false,
  error = false,
  helperText,
  size = 'small',
  fullWidth = true,
}) => {
  const [currencies, setCurrencies] = useState<CurrencyOption[]>([]);
  const [loading, setLoading]       = useState(true);
  const [fetchError, setFetchError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFetchError(false);
    try {
      const res = await api.get('/rates/currencies/', { params: { active_only: 'true' } });
      const data: CurrencyOption[] = res.data.results ?? res.data;
      setCurrencies(data);
    } catch {
      setFetchError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const options = excludeBase
    ? currencies.filter(c => !c.is_base_currency)
    : currencies;

  const selected = currencies.find(c => c.code === value);

  const handleChange = (code: string) => {
    const cur = currencies.find(c => c.code === code);
    onChange(code, cur);
  };

  if (loading) {
    return <Skeleton variant="rounded" height={size === 'small' ? 40 : 56} sx={{ width: fullWidth ? '100%' : 200 }} />;
  }

  if (fetchError) {
    return (
      <Alert severity="error" sx={{ py: 0 }}>
        Error al cargar divisas.{' '}
        <Typography
          component="span"
          variant="caption"
          sx={{ cursor: 'pointer', textDecoration: 'underline' }}
          onClick={load}
        >
          Reintentar
        </Typography>
      </Alert>
    );
  }

  const noRateWarning =
    showRateToggle &&
    selected &&
    !selected.use_exchange_rate &&
    useRate === false;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, width: fullWidth ? '100%' : 'auto' }}>
      <FormControl fullWidth={fullWidth} size={size} error={error} disabled={disabled}>
        <InputLabel>{label}</InputLabel>
        <Select
          value={value}
          label={label}
          onChange={e => handleChange(e.target.value as string)}
          renderValue={v => {
            const cur = currencies.find(c => c.code === v);
            if (!cur) return v;
            return `${cur.symbol} ${cur.code} — ${cur.name_es || cur.name_en}`;
          }}
        >
          {options.map(cur => (
            <MenuItem key={cur.code} value={cur.code}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, width: '100%' }}>
                <Typography
                  variant="body2"
                  fontWeight={700}
                  sx={{
                    minWidth: 36,
                    px: 0.75,
                    py: 0.25,
                    borderRadius: 1,
                    bgcolor: 'action.selected',
                    textAlign: 'center',
                    fontFamily: 'monospace',
                  }}
                >
                  {cur.symbol}
                </Typography>
                <Box>
                  <Typography variant="body2" fontWeight={600} lineHeight={1.2}>
                    {cur.code}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" lineHeight={1.2}>
                    {cur.name_es || cur.name_en}
                  </Typography>
                </Box>
                {cur.is_base_currency && (
                  <Typography
                    variant="caption"
                    sx={{
                      ml: 'auto',
                      px: 0.75,
                      py: 0.125,
                      borderRadius: 1,
                      bgcolor: 'primary.main',
                      color: 'primary.contrastText',
                      fontSize: '0.65rem',
                      fontWeight: 700,
                    }}
                  >
                    BASE
                  </Typography>
                )}
              </Box>
            </MenuItem>
          ))}
        </Select>
        {helperText && <FormHelperText>{helperText}</FormHelperText>}
      </FormControl>

      {showRateToggle && onUseRateChange && (
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={useRate ?? selected?.use_exchange_rate ?? true}
              onChange={e => onUseRateChange(e.target.checked)}
              disabled={disabled}
            />
          }
          label={
            <Typography variant="caption" color="text.secondary">
              Usar tasa de cambio
            </Typography>
          }
        />
      )}

      {noRateWarning && (
        <Alert severity="warning" sx={{ py: 0.25 }}>
          Esta divisa no usa tasa de cambio — el valor es fijo.
        </Alert>
      )}
    </Box>
  );
};

export default CurrencySelector;
