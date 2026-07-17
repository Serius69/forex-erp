import React, { useState } from 'react';
import {
  Box, Typography, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Chip, Button, Grid,
  Alert, AlertTitle, Slider, CircularProgress, Divider, TextField,
} from '@mui/material';
import {
  AutoMode, MonetizationOn, FlashOn, InfoOutlined,
} from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

// ── Auto Profit Mode Panel ────────────────────────────────────────────────────
const VARIANT_OPTIONS = [
  { value: '',               label: 'Estándar (billetes 20/50/100)' },
  { value: 'USD_CASH_LOOSE', label: '💵 USD Sueltos (5, 10)' },
  { value: 'USD_SMALL_BILLS',label: '🪙 USD Billetes 1 y 2' },
  { value: 'PEN_COINS',      label: '🪙 PEN Monedas' },
];

interface OptimizerResult {
  currency_code?:       string;
  variant?:             string | null;
  constraints_hit?:     string[];
  market_buy?:          number;
  market_sell?:         number;
  optimal_buy?:         number;
  optimal_sell?:        number;
  buy_discount_pct?:    number;
  sell_premium_pct?:    number;
  optimal_spread?:      number;
  optimal_spread_pct?:  number;
  market_spread_pct?:   number;
  source_used?:         string;
  confidence?:          number;
  notes?:               string;
}

const AutoProfitPanel: React.FC = () => {
  const [currency, setCurrency]     = useState('USD');
  const [variant, setVariant]       = useState('');
  const [params, setParams]         = useState({
    max_buy_discount_pct:  1.5,
    max_sell_premium_pct:  1.5,
    min_spread_bob:        0.30,
    max_spread_pct:        5.0,
  });
  const [result, setResult]         = useState<OptimizerResult | null>(null);
  const [loading, setLoading]       = useState(false);
  const [allResults, setAllResults] = useState<Record<string, OptimizerResult> | null>(null);
  const [loadingAll, setLoadingAll] = useState(false);
  const { enqueueSnackbar }         = useSnackbar();

  const calculate = async () => {
    setLoading(true);
    setResult(null);
    try {
      const res = await api.post('/rates/profit-optimizer/', {
        currency,
        variant: variant || null,
        ...params,
      });
      setResult(res.data);
    } catch (e: any) {
      enqueueSnackbar(e?.response?.data?.error ?? 'Error al calcular', { variant: 'error' });
    } finally { setLoading(false); }
  };

  const calculateAll = async () => {
    setLoadingAll(true);
    setAllResults(null);
    try {
      const res = await api.get('/rates/profit-optimizer/?all=true');
      setAllResults(res.data.optimized_rates);
    } catch (e: any) {
      enqueueSnackbar(e?.response?.data?.error ?? 'Error al calcular', { variant: 'error' });
    } finally { setLoadingAll(false); }
  };

  return (
    <Box>
      <Alert severity="info" sx={{ mb: 3 }} icon={<AutoMode />}>
        <AlertTitle>Auto Profit Mode — Optimizador de Máximo Beneficio</AlertTitle>
        Calcula las tasas óptimas de compra y venta que <strong>maximizan el margen</strong> sin salir
        del rango competitivo del mercado paralelo boliviano. El sistema busca el punto en que
        pagamos menos al cliente (compra) y cobramos más (venta) dentro de los límites configurados.
      </Alert>

      <Grid container spacing={3}>
        {/* Parámetros */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3, height: '100%' }}>
            <Typography variant="subtitle1" fontWeight={800} mb={2.5} display="flex" alignItems="center" gap={1}>
              <FlashOn color="warning" /> Parámetros de Optimización
            </Typography>

            <Box mb={2}>
              <Typography variant="body2" fontWeight={600} mb={0.75}>Divisa</Typography>
              <TextField
                select size="small" fullWidth value={currency}
                onChange={e => setCurrency(e.target.value)}
                SelectProps={{ native: true }}
              >
                {['USD', 'EUR', 'BRL', 'ARS', 'CLP', 'PEN', 'GBP', 'CNY'].map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </TextField>
            </Box>

            <Box mb={2}>
              <Typography variant="body2" fontWeight={600} mb={0.75}>Variante de Efectivo</Typography>
              <TextField
                select size="small" fullWidth value={variant}
                onChange={e => setVariant(e.target.value)}
                SelectProps={{ native: true }}
              >
                {VARIANT_OPTIONS
                  .filter(v => v.value === '' || v.value.startsWith(currency) || (currency === 'PEN' && v.value === 'PEN_COINS'))
                  .map(v => <option key={v.value} value={v.value}>{v.label}</option>)
                }
              </TextField>
            </Box>

            <Divider sx={{ my: 2 }} />

            <Typography variant="caption" color="text.secondary" fontWeight={600} display="block" mb={1.5}>
              AJUSTE DE COMPETITIVIDAD
            </Typography>

            <Box mb={2.5}>
              <Box display="flex" justifyContent="space-between">
                <Typography variant="body2">Descuento máx. en compra</Typography>
                <Typography variant="body2" fontWeight={700} color="error.main">
                  -{params.max_buy_discount_pct.toFixed(1)}%
                </Typography>
              </Box>
              <Slider
                value={params.max_buy_discount_pct} min={0.5} max={5.0} step={0.1}
                onChange={(_, v) => setParams(p => ({ ...p, max_buy_discount_pct: v as number }))}
                color="error" size="small" sx={{ mt: 0.5 }}
              />
              <Typography variant="caption" color="text.secondary">
                Pagamos este % menos que el precio de mercado al cliente
              </Typography>
            </Box>

            <Box mb={2.5}>
              <Box display="flex" justifyContent="space-between">
                <Typography variant="body2">Premium máx. en venta</Typography>
                <Typography variant="body2" fontWeight={700} color="success.main">
                  +{params.max_sell_premium_pct.toFixed(1)}%
                </Typography>
              </Box>
              <Slider
                value={params.max_sell_premium_pct} min={0.5} max={5.0} step={0.1}
                onChange={(_, v) => setParams(p => ({ ...p, max_sell_premium_pct: v as number }))}
                color="success" size="small" sx={{ mt: 0.5 }}
              />
              <Typography variant="caption" color="text.secondary">
                Cobramos este % más que el precio de mercado al cliente
              </Typography>
            </Box>

            <Box mb={2.5}>
              <Box display="flex" justifyContent="space-between">
                <Typography variant="body2">Spread mínimo (BOB)</Typography>
                <Typography variant="body2" fontWeight={700}>{params.min_spread_bob.toFixed(2)}</Typography>
              </Box>
              <Slider
                value={params.min_spread_bob} min={0.05} max={1.0} step={0.05}
                onChange={(_, v) => setParams(p => ({ ...p, min_spread_bob: v as number }))}
                size="small" sx={{ mt: 0.5 }}
              />
            </Box>

            <Box mb={3}>
              <Box display="flex" justifyContent="space-between">
                <Typography variant="body2">Spread máximo</Typography>
                <Typography variant="body2" fontWeight={700}>{params.max_spread_pct.toFixed(1)}%</Typography>
              </Box>
              <Slider
                value={params.max_spread_pct} min={1.0} max={10.0} step={0.5}
                onChange={(_, v) => setParams(p => ({ ...p, max_spread_pct: v as number }))}
                size="small" sx={{ mt: 0.5 }}
              />
              <Typography variant="caption" color="text.secondary">
                Tope ético/regulatorio del margen permitido
              </Typography>
            </Box>

            <Button
              fullWidth variant="contained" color="warning" size="large"
              onClick={calculate} disabled={loading}
              startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <AutoMode />}
              sx={{ fontWeight: 800 }}
            >
              {loading ? 'Calculando…' : 'Calcular Tasa Óptima'}
            </Button>

            <Button
              fullWidth variant="outlined" size="small" sx={{ mt: 1 }}
              onClick={calculateAll} disabled={loadingAll}
              startIcon={loadingAll ? <CircularProgress size={14} color="inherit" /> : <MonetizationOn />}
            >
              {loadingAll ? 'Procesando…' : 'Calcular Todas las Divisas'}
            </Button>
          </Paper>
        </Grid>

        {/* Resultado individual */}
        <Grid item xs={12} md={8}>
          {result ? (
            <Paper sx={{ p: 3 }}>
              <Typography variant="subtitle1" fontWeight={800} mb={2} display="flex" alignItems="center" gap={1}>
                <MonetizationOn color="success" />
                Resultado Óptimo — {result.currency_code}{result.variant ? ` (${result.variant})` : ''}
              </Typography>

              {result.constraints_hit && result.constraints_hit.length > 0 && (
                <Alert severity="warning" sx={{ mb: 2, py: 0.5 }} icon={<InfoOutlined />}>
                  Restricciones activas: {result.constraints_hit.join(', ')}
                  {result.constraints_hit.includes('MIN_SPREAD_FORCED') && ' — Spread elevado para garantizar rentabilidad mínima'}
                  {result.constraints_hit.includes('MAX_SPREAD_CAPPED') && ' — Spread recortado al máximo permitido'}
                </Alert>
              )}

              <Grid container spacing={2} mb={2}>
                <Grid item xs={6} sm={3}>
                  <Paper sx={{ p: 2, bgcolor: alpha(TOKENS.muted, 0.08), textAlign: 'center' }}>
                    <Typography variant="caption" color="text.secondary" display="block">Mercado — Compra</Typography>
                    <Typography variant="h5" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {result.market_buy?.toFixed(4)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">BOB (referencia)</Typography>
                  </Paper>
                </Grid>
                <Grid item xs={6} sm={3}>
                  <Paper sx={{ p: 2, bgcolor: alpha(TOKENS.muted, 0.08), textAlign: 'center' }}>
                    <Typography variant="caption" color="text.secondary" display="block">Mercado — Venta</Typography>
                    <Typography variant="h5" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {result.market_sell?.toFixed(4)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">BOB (referencia)</Typography>
                  </Paper>
                </Grid>
                <Grid item xs={6} sm={3}>
                  <Paper sx={{ p: 2, bgcolor: alpha(TOKENS.green, 0.08), border: '2px solid', borderColor: 'success.light', textAlign: 'center' }}>
                    <Typography variant="caption" color="success.main" display="block" fontWeight={600}>
                      ÓPTIMO — Compra
                    </Typography>
                    <Typography variant="h4" fontWeight={900} color="success.main" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {result.optimal_buy?.toFixed(4)}
                    </Typography>
                    <Typography variant="caption" color="success.dark" fontWeight={600}>
                      -{result.buy_discount_pct?.toFixed(2)}% vs mercado
                    </Typography>
                  </Paper>
                </Grid>
                <Grid item xs={6} sm={3}>
                  <Paper sx={{ p: 2, bgcolor: alpha(TOKENS.red, 0.08), border: '2px solid', borderColor: 'error.light', textAlign: 'center' }}>
                    <Typography variant="caption" color="error.main" display="block" fontWeight={600}>
                      ÓPTIMO — Venta
                    </Typography>
                    <Typography variant="h4" fontWeight={900} color="error.main" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {result.optimal_sell?.toFixed(4)}
                    </Typography>
                    <Typography variant="caption" color="error.dark" fontWeight={600}>
                      +{result.sell_premium_pct?.toFixed(2)}% vs mercado
                    </Typography>
                  </Paper>
                </Grid>
              </Grid>

              {/* Métricas de beneficio */}
              <Box sx={{ p: 2, bgcolor: alpha('#ffd700', 0.10), border: '1px solid', borderColor: alpha('#ffd700', 0.4), borderRadius: 2, mb: 2 }}>
                <Grid container spacing={2}>
                  <Grid item xs={6} sm={3} textAlign="center">
                    <Typography variant="caption" color="text.secondary" display="block">Margen por Unidad</Typography>
                    <Typography variant="h5" fontWeight={800} color="warning.dark">
                      {result.optimal_spread?.toFixed(4)} BOB
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={3} textAlign="center">
                    <Typography variant="caption" color="text.secondary" display="block">Spread Efectivo</Typography>
                    <Typography variant="h5" fontWeight={800} color="warning.dark">
                      {result.optimal_spread_pct?.toFixed(2)}%
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={3} textAlign="center">
                    <Typography variant="caption" color="text.secondary" display="block">Spread Mercado</Typography>
                    <Typography variant="h5" fontWeight={700} color="text.secondary">
                      {result.market_spread_pct?.toFixed(2)}%
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={3} textAlign="center">
                    <Typography variant="caption" color="text.secondary" display="block">Fuente</Typography>
                    <Chip
                      label={result.source_used?.toUpperCase()}
                      size="small"
                      color={result.source_used === 'binance' ? 'success' : 'warning'}
                      sx={{ fontWeight: 700 }}
                    />
                    <Typography variant="caption" color="text.secondary" display="block">
                      Confianza: {((result.confidence ?? 0) * 100).toFixed(0)}%
                    </Typography>
                  </Grid>
                </Grid>
              </Box>

              {result.notes && (
                <Alert severity="info" sx={{ mb: 2, py: 0.5 }} icon={false}>
                  <Typography variant="caption">{result.notes}</Typography>
                </Alert>
              )}

              <Alert severity="warning" sx={{ py: 0.5 }}>
                <Typography variant="caption">
                  <strong>Nota operacional:</strong> Estas tasas son sugerencias del optimizador.
                  Aplíquelas solo si están dentro de las políticas vigentes.
                  Use el botón de edición manual en la tabla de tasas para persistirlas.
                </Typography>
              </Alert>
            </Paper>
          ) : (
            <Paper sx={{ p: 4, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 280, bgcolor: alpha(TOKENS.blue, 0.03), border: '2px dashed', borderColor: alpha(TOKENS.blue, 0.2) }}>
              <AutoMode sx={{ fontSize: 56, color: alpha(TOKENS.blue, 0.3), mb: 2 }} />
              <Typography variant="h6" color="text.secondary" fontWeight={600}>Configura los parámetros</Typography>
              <Typography variant="body2" color="text.disabled" textAlign="center" mt={1} maxWidth={360}>
                Ajusta los sliders y presiona "Calcular Tasa Óptima" para ver las tasas que maximizan tu margen.
              </Typography>
            </Paper>
          )}

          {/* Resultados de todas las divisas */}
          {allResults && (
            <Paper sx={{ p: 3, mt: 3 }}>
              <Typography variant="subtitle1" fontWeight={800} mb={2}>
                Optimización Global — Todas las Divisas
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Divisa</TableCell>
                      <TableCell align="right">Mkt Compra</TableCell>
                      <TableCell align="right">Mkt Venta</TableCell>
                      <TableCell align="right">Óptimo Compra</TableCell>
                      <TableCell align="right">Óptimo Venta</TableCell>
                      <TableCell align="right">Margen/Unit</TableCell>
                      <TableCell align="right">Spread %</TableCell>
                      <TableCell>Fuente</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {Object.entries(allResults).map(([code, r]) => (
                      <TableRow key={code} hover>
                        <TableCell>
                          <Typography fontWeight={700}>{code}</Typography>
                          {r.variant && <Chip label={r.variant} size="small" sx={{ fontSize: '0.6rem', height: 16, ml: 0.5 }} />}
                        </TableCell>
                        <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {r.market_buy?.toFixed(4)}
                        </TableCell>
                        <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {r.market_sell?.toFixed(4)}
                        </TableCell>
                        <TableCell align="right">
                          <Typography color="success.main" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                            {r.optimal_buy?.toFixed(4)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Typography color="error.main" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                            {r.optimal_sell?.toFixed(4)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Chip
                            label={`${r.optimal_spread?.toFixed(3)} BOB`}
                            size="small"
                            color={(r.optimal_spread ?? 0) > 0.5 ? 'success' : 'default'}
                            sx={{ fontWeight: 700, fontSize: '0.65rem' }}
                          />
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="body2" fontWeight={600}
                            sx={{ color: (r.optimal_spread_pct ?? 0) > 3 ? 'success.main' : (r.optimal_spread_pct ?? 0) > 1 ? 'warning.main' : 'text.secondary' }}>
                            {r.optimal_spread_pct?.toFixed(2)}%
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={r.source_used?.toUpperCase()}
                            size="small"
                            color={r.source_used === 'binance' ? 'success' : 'default'}
                            sx={{ fontSize: '0.6rem', height: 20 }}
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          )}
        </Grid>
      </Grid>
    </Box>
  );
};

export default AutoProfitPanel;
