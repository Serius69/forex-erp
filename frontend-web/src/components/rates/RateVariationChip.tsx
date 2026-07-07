// src/components/rates/RateVariationChip.tsx
import React from 'react';
import { Box, Chip, Tooltip, Typography } from '@mui/material';
import { ArrowUpward, ArrowDownward, TrendingFlat } from '@mui/icons-material';
import { alpha } from '@mui/material/styles';

interface RateVariationChipProps {
  /** Porcentaje de cambio (positivo = sube, negativo = baja) */
  changePct?:  number | null;
  /** Valor actual (para calcular changePct si no se provee) */
  current?:    number;
  /** Valor anterior */
  previous?:   number | null;
  /** Modo compacto (sin etiqueta, solo ícono + número) */
  compact?:    boolean;
  /** Texto de referencia temporal (e.g. "vs ayer", "vs 1h") */
  label?:      string;
}

const RateVariationChip: React.FC<RateVariationChipProps> = ({
  changePct, current, previous, compact = false, label = 'vs anterior',
}) => {
  // Calcular changePct si no se provee
  const pct = React.useMemo<number | null>(() => {
    if (changePct !== undefined && changePct !== null) return changePct;
    if (current !== undefined && previous !== undefined && previous !== null && previous !== 0) {
      return ((current - previous) / previous) * 100;
    }
    return null;
  }, [changePct, current, previous]);

  if (pct === null) return null;

  const isUp      = pct > 0.005;
  const isDown    = pct < -0.005;
  const isFlat    = !isUp && !isDown;
  const absPct    = Math.abs(pct);
  const pctStr    = `${isUp ? '+' : isDown ? '-' : ''}${absPct.toFixed(2)}%`;

  const color     = isUp ? '#2e7d32' : isDown ? '#c62828' : '#616161';
  const bg        = isUp ? alpha('#4caf50', 0.1) : isDown ? alpha('#f44336', 0.1) : alpha('#9e9e9e', 0.1);
  const borderCol = isUp ? alpha('#4caf50', 0.3) : isDown ? alpha('#f44336', 0.3) : alpha('#9e9e9e', 0.25);

  const Icon = isUp ? ArrowUpward : isDown ? ArrowDownward : TrendingFlat;

  return (
    <Tooltip
      title={`Variación: ${pctStr} ${label}`}
      arrow
      placement="top"
    >
      <Box
        sx={{
          display:     'inline-flex',
          alignItems:  'center',
          gap:         0.25,
          px:          compact ? 0.5 : 0.75,
          py:          0.2,
          borderRadius: '6px',
          bgcolor:     bg,
          border:      '1px solid',
          borderColor: borderCol,
          cursor:      'help',
        }}
      >
        <Icon sx={{ fontSize: 11, color }} />
        <Typography
          variant="caption"
          fontWeight={700}
          sx={{ color, fontSize: '0.68rem', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}
        >
          {pctStr}
        </Typography>
        {!compact && label && (
          <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.6rem', ml: 0.25 }}>
            {label}
          </Typography>
        )}
      </Box>
    </Tooltip>
  );
};

export default RateVariationChip;
