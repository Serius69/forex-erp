// src/components/rates/AIPricingSuggestions.tsx
import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Button, Select, MenuItem,
  FormControl, InputLabel, CircularProgress, Alert, Chip, Divider,
  Table, TableBody, TableCell, TableHead, TableRow, Tooltip,
  IconButton, LinearProgress,
} from '@mui/material';
import {
  Psychology, Refresh, TrendingUp, TrendingDown,
  Inventory, PeopleAlt, InfoOutlined,
} from '@mui/icons-material';
import axios from 'axios';

interface PricingDecision {
  id: number;
  currency: string;
  suggested_buy: number;
  suggested_sell: number;
  suggested_spread_pct: number;
  base_rate: number;
  inventory_factor: number;
  demand_factor: number;
  stock_pct: number | null;
  actual_buy: number | null;
  actual_sell: number | null;
  deviation_pct: number | null;
  recommendation: string;
  trigger: string;
  created_at: string;
  rates_used: { bcb?: number; binance?: number; historical?: number; competition?: number };
}

const CURRENCIES = ['USD', 'EUR', 'BRL', 'ARS', 'PEN'];

const FactorBadge: React.FC<{ label: string; value: number; icon: React.ReactNode }> = ({ label, value, icon }) => {
  const isHigh = value > 1.005;
  const isLow  = value < 0.995;
  return (
    <Tooltip title={`Factor ${label}: ${value.toFixed(4)}`}>
      <Chip
        size="small"
        icon={icon as any}
        label={`${label}: ${value > 1 ? '+' : ''}${((value - 1) * 100).toFixed(1)}%`}
        color={isHigh ? 'success' : isLow ? 'error' : 'default'}
        variant={isHigh || isLow ? 'filled' : 'outlined'}
      />
    </Tooltip>
  );
};

const AIPricingSuggestions: React.FC = () => {
  const [decisions, setDecisions] = useState<PricingDecision[]>([]);
  const [loading, setLoading] = useState(false);
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [currency, setCurrency] = useState('USD');

  const fetchDecisions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`/api/rates/ai-pricing/?currency=${currency}&limit=10`);
      setDecisions(res.data.decisions || []);
    } catch (e: any) {
      setError('Error al cargar decisiones de precios AI');
    } finally {
      setLoading(false);
    }
  }, [currency]);

  useEffect(() => { fetchDecisions(); }, [fetchDecisions]);

  const handleCalculate = async () => {
    setCalculating(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await axios.post('/api/rates/ai-pricing/', { currency });
      setSuccess(`Precio calculado: Compra Bs ${res.data.suggested_buy?.toFixed(4)} / Venta Bs ${res.data.suggested_sell?.toFixed(4)}`);
      fetchDecisions();
    } catch (e: any) {
      setError(e.response?.data?.error || 'Error al calcular precio AI');
    } finally {
      setCalculating(false);
    }
  };

  const latest = decisions[0];

  return (
    <Card>
      <CardContent>
        {/* Header */}
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Box display="flex" alignItems="center" gap={1}>
            <Psychology color="primary" />
            <Box>
              <Typography variant="h6" fontWeight={600}>Motor de Precios AI</Typography>
              <Typography variant="caption" color="text.secondary">
                TCsugerido = w₁·BCB + w₂·Binance + w₃·Histórico + w₄·Competencia
              </Typography>
            </Box>
          </Box>
          <Box display="flex" gap={1} alignItems="center">
            <FormControl size="small" sx={{ minWidth: 90 }}>
              <InputLabel>Divisa</InputLabel>
              <Select value={currency} label="Divisa" onChange={e => setCurrency(e.target.value)}>
                {CURRENCIES.map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}
              </Select>
            </FormControl>
            <Tooltip title="Calcular ahora">
              <Button
                variant="contained" size="small" startIcon={calculating ? <CircularProgress size={14} /> : <Psychology />}
                onClick={handleCalculate} disabled={calculating}
              >
                Calcular
              </Button>
            </Tooltip>
            <IconButton size="small" onClick={fetchDecisions}><Refresh fontSize="small" /></IconButton>
          </Box>
        </Box>

        {error  && <Alert severity="error"   sx={{ mb: 2 }}>{error}</Alert>}
        {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}
        {loading && <LinearProgress sx={{ mb: 2 }} />}

        {/* Última decisión highlight */}
        {latest && (
          <Box sx={{ background: 'action.hover', bgcolor: 'rgba(33,150,243,0.05)', p: 2, borderRadius: 2, mb: 2 }}>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="subtitle1" fontWeight={700}>Última Sugerencia — {latest.currency}</Typography>
              <Chip label={latest.trigger} size="small" variant="outlined" />
            </Box>

            <Box display="flex" gap={3} mb={1.5} flexWrap="wrap">
              <Box>
                <Typography variant="caption" color="text.secondary">Compra Sugerida</Typography>
                <Typography variant="h5" fontWeight={700} color="success.main">
                  Bs {latest.suggested_buy.toFixed(4)}
                </Typography>
                {latest.actual_buy && (
                  <Typography variant="caption" color="text.secondary">
                    Actual: Bs {latest.actual_buy.toFixed(4)}
                  </Typography>
                )}
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">Venta Sugerida</Typography>
                <Typography variant="h5" fontWeight={700} color="primary.main">
                  Bs {latest.suggested_sell.toFixed(4)}
                </Typography>
                {latest.actual_sell && (
                  <Typography variant="caption" color="text.secondary">
                    Actual: Bs {latest.actual_sell.toFixed(4)}
                  </Typography>
                )}
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">Spread</Typography>
                <Typography variant="h5" fontWeight={700}
                  color={latest.suggested_spread_pct > 0.5 ? 'success.main' : 'warning.main'}>
                  {latest.suggested_spread_pct.toFixed(3)}%
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">Tasa Base</Typography>
                <Typography variant="h5" fontWeight={700} color="text.primary">
                  Bs {latest.base_rate.toFixed(4)}
                </Typography>
              </Box>
            </Box>

            {/* Factores */}
            <Box display="flex" gap={1} flexWrap="wrap" mb={1.5}>
              <FactorBadge label="Inventario" value={latest.inventory_factor} icon={<Inventory />} />
              <FactorBadge label="Demanda" value={latest.demand_factor} icon={<PeopleAlt />} />
              {latest.stock_pct !== null && (
                <Chip size="small" label={`Stock: ${latest.stock_pct.toFixed(0)}%`}
                  color={latest.stock_pct < 20 ? 'error' : latest.stock_pct > 80 ? 'warning' : 'default'}
                  variant="outlined" />
              )}
              {latest.deviation_pct !== null && (
                <Chip size="small"
                  label={`Desviación vs actual: ${latest.deviation_pct > 0 ? '+' : ''}${latest.deviation_pct.toFixed(2)}%`}
                  color={Math.abs(latest.deviation_pct) > 1 ? 'warning' : 'default'}
                  variant="outlined" />
              )}
            </Box>

            {/* Fuentes usadas */}
            <Box display="flex" gap={1} flexWrap="wrap" mb={1}>
              {Object.entries(latest.rates_used).map(([src, val]) => val && (
                <Chip key={src} size="small" variant="outlined"
                  label={`${src.toUpperCase()}: Bs ${Number(val).toFixed(4)}`} />
              ))}
            </Box>

            {/* Recomendación */}
            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
              💡 {latest.recommendation}
            </Typography>
          </Box>
        )}

        {/* Historial */}
        {decisions.length > 1 && (
          <>
            <Typography variant="subtitle2" fontWeight={600} mb={1}>Historial de decisiones</Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Fecha</TableCell>
                  <TableCell align="right">Compra</TableCell>
                  <TableCell align="right">Venta</TableCell>
                  <TableCell align="right">Spread%</TableCell>
                  <TableCell>Trigger</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {decisions.slice(1, 8).map(d => (
                  <TableRow key={d.id} hover>
                    <TableCell sx={{ fontSize: 12 }}>
                      {new Date(d.created_at).toLocaleString('es-BO', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })}
                    </TableCell>
                    <TableCell align="right" sx={{ fontSize: 12 }}>{d.suggested_buy.toFixed(4)}</TableCell>
                    <TableCell align="right" sx={{ fontSize: 12 }}>{d.suggested_sell.toFixed(4)}</TableCell>
                    <TableCell align="right" sx={{ fontSize: 12 }}>
                      <Chip label={`${d.suggested_spread_pct.toFixed(2)}%`} size="small"
                        color={d.suggested_spread_pct > 0.4 ? 'success' : 'warning'} />
                    </TableCell>
                    <TableCell>
                      <Chip label={d.trigger} size="small" variant="outlined" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}

        {!loading && decisions.length === 0 && (
          <Alert severity="info">
            No hay decisiones AI para {currency}. Haz clic en "Calcular" para generar la primera.
          </Alert>
        )}
      </CardContent>
    </Card>
  );
};

export default AIPricingSuggestions;
