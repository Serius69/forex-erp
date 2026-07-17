import React from 'react';
import {
  Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Chip, Box, Typography, IconButton, Tooltip, Link,
} from '@mui/material';
import { Edit, CheckCircle } from '@mui/icons-material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { isScaled, formatScale, formatRate } from '../../utils/finance';
import { SourceBadge, ConfidenceBar } from './RateBadges';
import type { ExchangeRate } from './rateTypes';

// Tabla completa de tasas (par, mercado, compra/venta, spread, fuente,
// confianza, estado y acción de edición para ADMIN).
const RatesTable: React.FC<{
  rates:   ExchangeRate[];
  isAdmin: boolean;
  onEdit:  (rate: ExchangeRate) => void;
}> = ({ rates, isAdmin, onEdit }) => (
  <TableContainer component={Paper}>
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Par</TableCell>
          <TableCell>Mercado</TableCell>
          <TableCell align="right">Tasa mercado</TableCell>
          <TableCell align="right">Compra</TableCell>
          <TableCell align="right">Venta</TableCell>
          <TableCell align="right">Spread</TableCell>
          <TableCell>Escala</TableCell>
          <TableCell>Fuente / URL</TableCell>
          <TableCell>Confianza</TableCell>
          <TableCell>Actualizado</TableCell>
          <TableCell>Estado</TableCell>
          {isAdmin && <TableCell>Acciones</TableCell>}
        </TableRow>
      </TableHead>
      <TableBody>
        {rates.map((rate) => {
          const scale       = rate.currency_from?.scale_factor ?? 1;
          const scaled      = isScaled(scale);
          const rateLabel   = scaled ? `por ${formatScale(scale)} ${rate.currency_from?.code}` : 'por unidad';
          const isInference = rate.source_method === 'INFERENCE';
          const conf        = parseFloat(rate.confidence ?? '1');

          return (
            <TableRow key={rate.id} hover
              sx={isInference ? { bgcolor: '#fff8f8' } : undefined}>
              <TableCell>
                <Box display="flex" alignItems="center" gap={0.5}>
                  <Typography fontWeight="bold">
                    {rate.currency_from?.code} / {rate.currency_to?.code}
                  </Typography>
                  {rate.is_primary && (
                    <Tooltip title="Tasa activa — usada en transacciones" arrow>
                      <Chip label="★" size="small" color="primary"
                        sx={{ fontSize: '0.6rem', height: 16, minWidth: 0, px: 0.5 }} />
                    </Tooltip>
                  )}
                </Box>
              </TableCell>
              <TableCell>
                <Chip
                  label={
                    rate.market_type?.includes('paralelo_digital') ? 'Digital' :
                    rate.market_type?.includes('paralelo') ? 'Paralelo' :
                    rate.market_type === 'digital' ? 'Digital' : 'Paralelo'
                  }
                  size="small"
                  color="default"
                  variant="outlined"
                />
              </TableCell>
              <TableCell align="right">
                <Tooltip title="Mid-rate paralelo por unidad" arrow>
                  <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums', cursor: 'help' }}>
                    {((parseFloat(rate.buy_rate) + parseFloat(rate.sell_rate)) / 2).toFixed(4)}
                  </Typography>
                </Tooltip>
              </TableCell>
              <TableCell align="right">
                <Typography color="success.main" fontWeight="medium" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                  {formatRate(rate.buy_rate)}
                </Typography>
              </TableCell>
              <TableCell align="right">
                <Typography color="error.main" fontWeight="medium" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                  {formatRate(rate.sell_rate)}
                </Typography>
              </TableCell>
              <TableCell align="right">
                <Typography variant="body2" fontWeight={parseFloat(rate.spread_percentage ?? '0') > 3 ? 700 : 400}
                  color={parseFloat(rate.spread_percentage ?? '0') > 3 ? 'warning.main' : 'text.secondary'}>
                  {rate.spread_percentage}%
                </Typography>
              </TableCell>
              <TableCell>
                {scaled
                  ? <Chip label={`×${formatScale(scale)}`} size="small"
                      sx={{ bgcolor: 'warning.main', color: 'warning.contrastText', fontSize: '0.65rem' }} />
                  : <Typography variant="caption" color="text.secondary">×1</Typography>
                }
                <Typography variant="caption" color="text.secondary" display="block">{rateLabel}</Typography>
              </TableCell>

              {/* Source with clickable URL */}
              <TableCell>
                <Box display="flex" flexDirection="column" gap={0.5}>
                  <SourceBadge
                    method={rate.source_method}
                    sourceUrl={rate.source_url}
                    confidence={conf}
                    fetchedAt={rate.fetched_at}
                  />
                  {rate.source_url ? (
                    <Link
                      href={rate.source_url}
                      target="_blank"
                      rel="noopener"
                      underline="hover"
                      sx={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap', display: 'block', fontSize: '0.65rem', color: 'text.secondary' }}
                    >
                      {rate.source_url}
                    </Link>
                  ) : (
                    <Typography variant="caption" color="text.disabled" fontStyle="italic">
                      Sin URL
                    </Typography>
                  )}
                </Box>
              </TableCell>

              {/* Confidence indicator */}
              <TableCell>
                <ConfidenceBar value={conf} />
              </TableCell>

              {/* Last updated */}
              <TableCell>
                {rate.fetched_at ? (
                  <Typography variant="caption">
                    {format(new Date(rate.fetched_at), 'dd/MM HH:mm', { locale: es })}
                  </Typography>
                ) : (
                  <Typography variant="caption" color="text.disabled">—</Typography>
                )}
              </TableCell>

              {/* Status */}
              <TableCell>
                <Box display="flex" flexDirection="column" gap={0.5}>
                  <Chip
                    label={rate.valid_until ? 'Vencida' : 'Vigente'}
                    color={rate.valid_until ? 'default' : 'success'}
                    size="small"
                  />
                  {rate.is_validated && (
                    <Chip label="✓ Validada" color="primary" size="small" variant="outlined"
                      icon={<CheckCircle sx={{ fontSize: 12 }} />} />
                  )}
                  {isInference && !rate.is_validated && (
                    <Chip label="⚠ Sin validar" color="error" size="small" variant="outlined" />
                  )}
                </Box>
              </TableCell>

              {isAdmin && (
                <TableCell>
                  <Tooltip title={isInference ? 'Editar y validar tasa estimada' : 'Editar tasa'}>
                    <IconButton
                      size="small"
                      onClick={() => onEdit(rate)}
                      color={isInference ? 'error' : 'default'}
                    >
                      <Edit />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              )}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  </TableContainer>
);

export default RatesTable;
