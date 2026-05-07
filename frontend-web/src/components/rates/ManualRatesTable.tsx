// src/components/rates/ManualRatesTable.tsx
// Tabla DataGrid de tasas manuales con toggle activo y edición inline.
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Button, Chip, IconButton, Paper, Skeleton, Switch,
  Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Tooltip, Typography, Alert, Stack,
} from '@mui/material';
import {
  Add, Edit, Refresh, CheckCircle, Warning, RadioButtonUnchecked,
} from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { TOKENS } from '../../styles/theme';
import { ratesApi, ExchangeRate } from '../../services/ratesApi';
import { useAuth } from '../../contexts/AuthContext';
import RateSourceBadge from './RateSourceBadge';
import ManualRateForm from './ManualRateForm';

// ── Helpers ───────────────────────────────────────────────────────────────────

const isExpired = (rate: ExchangeRate): boolean =>
  Boolean(rate.valid_until && new Date(rate.valid_until) < new Date());

const MarketChip: React.FC<{ marketType: string }> = ({ marketType }) => {
  const label = marketType?.includes('digital') ? 'Digital'
              : marketType?.includes('paralelo') || marketType === 'parallel' ? 'Paralelo'
              : marketType ?? '—';
  return <Chip label={label} size="small" variant="outlined" sx={{ fontSize: '0.62rem', height: 20 }} />;
};

// ── ManualRatesTable ──────────────────────────────────────────────────────────

interface ManualRatesTableProps {
  /** Si true, muestra solo tasas manuales (source_method = MANUAL) */
  manualOnly?: boolean;
}

const ManualRatesTable: React.FC<ManualRatesTableProps> = ({ manualOnly = true }) => {
  const [rates,       setRates]       = useState<ExchangeRate[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [formOpen,    setFormOpen]    = useState(false);
  const [editingRate, setEditingRate] = useState<ExchangeRate | null>(null);
  const [toggling,    setToggling]    = useState<number | null>(null);
  const { user }          = useAuth();
  const { enqueueSnackbar } = useSnackbar();
  const isAdmin = user?.role === 'ADMIN';

  const loadRates = useCallback(async () => {
    setLoading(true);
    try {
      const all = await ratesApi.getExchangeRates();
      setRates(manualOnly ? all.filter(r => r.source_method === 'MANUAL') : all);
    } catch {
      enqueueSnackbar('Error al cargar tasas', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [manualOnly, enqueueSnackbar]);

  useEffect(() => { loadRates(); }, [loadRates]);

  const handleTogglePrimary = async (rate: ExchangeRate) => {
    setToggling(rate.id);
    try {
      await ratesApi.updateRate(rate.id, { is_primary: !rate.is_primary });
      enqueueSnackbar(
        `Tasa ${rate.currency_from?.code}/${rate.currency_to?.code} ${!rate.is_primary ? 'activada' : 'desactivada'}`,
        { variant: 'success' }
      );
      loadRates();
    } catch {
      enqueueSnackbar('Error al actualizar estado', { variant: 'error' });
    } finally {
      setToggling(null);
    }
  };

  const handleEdit = (rate: ExchangeRate) => {
    setEditingRate(rate);
    setFormOpen(true);
  };

  const handleFormClose = (saved: boolean) => {
    setFormOpen(false);
    setEditingRate(null);
    if (saved) loadRates();
  };

  // ── Skeleton ─────────────────────────────────────────────────────────────
  if (loading) return (
    <Box>
      {[1, 2, 3, 4].map(i => (
        <Skeleton key={i} variant="rectangular" height={40} sx={{ mb: 0.5, borderRadius: 1 }} />
      ))}
    </Box>
  );

  return (
    <Box>
      {/* Toolbar */}
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={2} flexWrap="wrap" gap={1}>
        <Box>
          <Typography variant="subtitle1" fontWeight={800}>
            Tasas Manuales
            <Chip
              label={rates.length}
              size="small"
              sx={{ ml: 1, height: 20, fontSize: '0.65rem', bgcolor: alpha(TOKENS.amber, 0.12), color: TOKENS.amber, fontWeight: 700 }}
            />
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Tasas ingresadas manualmente por operadores. Solo las marcadas ★ se usan en transacciones.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <Button
            size="small"
            variant="outlined"
            startIcon={<Refresh />}
            onClick={loadRates}
          >
            Recargar
          </Button>
          {isAdmin && (
            <Button
              size="small"
              variant="contained"
              color="warning"
              startIcon={<Add />}
              onClick={() => { setEditingRate(null); setFormOpen(true); }}
              sx={{ fontWeight: 700 }}
            >
              Nueva Tasa Manual
            </Button>
          )}
        </Stack>
      </Box>

      {rates.length === 0 ? (
        <Alert severity="info" icon={<RadioButtonUnchecked />}>
          No hay tasas manuales registradas.
          {isAdmin && ' Usa el botón "Nueva Tasa Manual" para ingresar una.'}
        </Alert>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: alpha(TOKENS.amber, 0.04) }}>
                <TableCell sx={{ fontWeight: 700 }}>Par</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Mercado</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Compra</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Venta</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Spread</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Fuente</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Operador</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Fecha/Hora</TableCell>
                <TableCell align="center" sx={{ fontWeight: 700 }}>Estado</TableCell>
                {isAdmin && <TableCell align="center" sx={{ fontWeight: 700 }}>Activo</TableCell>}
                {isAdmin && <TableCell align="center" sx={{ fontWeight: 700 }}>Acciones</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {rates.map(rate => {
                const expired  = isExpired(rate);
                const isPrimary = rate.is_primary;

                return (
                  <TableRow
                    key={rate.id}
                    hover
                    sx={{
                      bgcolor: expired ? alpha('#9e9e9e', 0.04) : undefined,
                      opacity: expired ? 0.7 : 1,
                    }}
                  >
                    {/* Par */}
                    <TableCell>
                      <Box display="flex" alignItems="center" gap={0.5}>
                        <Typography fontWeight={800} sx={{ fontFamily: 'monospace', fontSize: '0.9rem' }}>
                          {rate.currency_from?.code}/{rate.currency_to?.code}
                        </Typography>
                        {isPrimary && (
                          <Tooltip title="Tasa activa — usada en transacciones" arrow>
                            <CheckCircle sx={{ fontSize: 14, color: TOKENS.green }} />
                          </Tooltip>
                        )}
                      </Box>
                    </TableCell>

                    {/* Mercado */}
                    <TableCell>
                      <MarketChip marketType={rate.market_type} />
                    </TableCell>

                    {/* Compra */}
                    <TableCell align="right">
                      <Typography color="success.main" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                        {parseFloat(rate.buy_rate).toFixed(4)}
                      </Typography>
                    </TableCell>

                    {/* Venta */}
                    <TableCell align="right">
                      <Typography color="error.main" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                        {parseFloat(rate.sell_rate).toFixed(4)}
                      </Typography>
                    </TableCell>

                    {/* Spread */}
                    <TableCell align="right">
                      <Typography
                        variant="body2"
                        fontWeight={parseFloat(rate.spread_percentage) > 3 ? 700 : 400}
                        color={parseFloat(rate.spread_percentage) > 3 ? 'warning.main' : 'text.secondary'}
                      >
                        {rate.spread_percentage}%
                      </Typography>
                    </TableCell>

                    {/* Fuente */}
                    <TableCell>
                      <RateSourceBadge source={rate.source_method} confidence={parseFloat(rate.confidence)} />
                    </TableCell>

                    {/* Operador */}
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">
                        {rate.created_by
                          ? `${rate.created_by.first_name ?? ''} ${rate.created_by.last_name ?? ''}`.trim() || rate.created_by.username
                          : '—'}
                      </Typography>
                    </TableCell>

                    {/* Fecha */}
                    <TableCell>
                      <Typography variant="caption">
                        {rate.fetched_at
                          ? format(new Date(rate.fetched_at), 'dd/MM/yy HH:mm', { locale: es })
                          : rate.valid_from
                          ? format(new Date(rate.valid_from), 'dd/MM/yy HH:mm', { locale: es })
                          : '—'}
                      </Typography>
                    </TableCell>

                    {/* Estado */}
                    <TableCell align="center">
                      <Box display="flex" flexDirection="column" gap={0.4} alignItems="center">
                        <Chip
                          label={expired ? 'Vencida' : 'Vigente'}
                          color={expired ? 'default' : 'success'}
                          size="small"
                          sx={{ fontSize: '0.6rem', height: 18 }}
                        />
                        {rate.is_validated && (
                          <Chip
                            label="✓ Validada"
                            color="primary"
                            size="small"
                            variant="outlined"
                            sx={{ fontSize: '0.6rem', height: 18 }}
                          />
                        )}
                      </Box>
                    </TableCell>

                    {/* Toggle activo */}
                    {isAdmin && (
                      <TableCell align="center">
                        <Tooltip title={isPrimary ? 'Desactivar (quitar de transacciones)' : 'Activar como tasa principal'} arrow>
                          <span>
                            <Switch
                              checked={isPrimary}
                              size="small"
                              disabled={toggling === rate.id}
                              onChange={() => handleTogglePrimary(rate)}
                              color="success"
                            />
                          </span>
                        </Tooltip>
                      </TableCell>
                    )}

                    {/* Editar */}
                    {isAdmin && (
                      <TableCell align="center">
                        <Tooltip title="Editar tasa" arrow>
                          <IconButton size="small" onClick={() => handleEdit(rate)}>
                            <Edit sx={{ fontSize: 16 }} />
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
      )}

      {/* Formulario crear/editar */}
      <ManualRateForm
        open={formOpen}
        editingRate={editingRate}
        onClose={handleFormClose}
      />
    </Box>
  );
};

export default ManualRatesTable;
