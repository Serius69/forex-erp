/**
 * Simulador Monte Carlo de tasas — calibrado con la serie diaria REAL.
 *
 * Backend: GET /api/predictions/simulate/{par}/ (bootstrap de retornos reales
 * o GBM), con escenario de estrés (shock ±%) y VaR de la posición real de
 * inventario.
 */
import React, { useCallback, useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider,
  Grid, InputAdornment, MenuItem, Slider, TextField, Tooltip, Typography,
} from '@mui/material';
import { Casino, PlayArrow, ShowChart, Warning } from '@mui/icons-material';
import {
  Area, AreaChart, CartesianGrid, Line, ResponsiveContainer,
  Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

const PAIRS = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'ARS/BOB', 'PEN/BOB'];
const MARKETS = [
  { value: 'web',         label: 'Paralelo digital (web)' },
  { value: 'competencia', label: 'Físico competencia' },
  { value: 'empresa',     label: 'Empresa (tasas propias)' },
];

interface SimResult {
  pair: string;
  market: string;
  method: string;
  params: { horizon_days: number; n_paths: number; shock_pct: number; sigma_annual_pct: number };
  calibration: { n_days: number; from: string; to: string; last_rate: number };
  bands: Record<string, number[]>;
  final_distribution: Record<string, number>;
  position_risk?: {
    position_amount?: number; valuation_bob?: number; var_bob?: number;
    expected_shortfall_bob?: number; pnl_mean_bob?: number; note?: string; error?: string;
  };
}

const fmtBs = (v: number | undefined) =>
  v === undefined ? '—' : `Bs ${v.toLocaleString('es-BO', { maximumFractionDigits: 0 })}`;

const Simulator: React.FC = () => {
  const { enqueueSnackbar } = useSnackbar();
  const [pair, setPair] = useState('USD/BOB');
  const [market, setMarket] = useState('web');
  const [method, setMethod] = useState<'bootstrap' | 'gbm'>('bootstrap');
  const [horizon, setHorizon] = useState(30);
  const [shock, setShock] = useState(0);
  const [withVar, setWithVar] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SimResult | null>(null);
  const [error, setError] = useState('');

  const run = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get(`/predictions/simulate/${pair.replace('/', '-')}/`, {
        params: {
          market, method, horizon_days: horizon, n_paths: 3000,
          shock_pct: shock, var: withVar ? 'true' : 'false',
        },
      });
      setResult(res.data);
    } catch (e: any) {
      const msg = e?.response?.data?.error ?? 'Simulación fallida';
      setError(msg);
      enqueueSnackbar(msg, { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [pair, market, method, horizon, shock, withVar, enqueueSnackbar]);

  const chartData = result
    ? result.bands.p50.map((_, i) => ({
        day: i + 1,
        p5:  result.bands.p5[i],
        p25: result.bands.p25[i],
        p50: result.bands.p50[i],
        p75: result.bands.p75[i],
        p95: result.bands.p95[i],
      }))
    : [];

  const fd = result?.final_distribution;

  return (
    <Box sx={{ p: { xs: 2, md: 3 } }}>
      <Typography variant="h5" fontWeight={700} gutterBottom>
        Simulador de Tasas
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Monte Carlo calibrado con la historia diaria real del par/mercado. Bootstrap
        re-muestrea retornos observados (captura colas gordas del paralelo boliviano);
        GBM es la referencia paramétrica. El shock simula una devaluación/apreciación
        inicial y el VaR usa tu posición real de inventario.
      </Typography>

      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={6} sm={3} md={2}>
              <TextField select fullWidth size="small" label="Par" value={pair}
                         onChange={e => setPair(e.target.value)}>
                {PAIRS.map(p => <MenuItem key={p} value={p}>{p}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={6} sm={4} md={3}>
              <TextField select fullWidth size="small" label="Mercado" value={market}
                         onChange={e => setMarket(e.target.value)}>
                {MARKETS.map(m => <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={6} sm={3} md={2}>
              <TextField select fullWidth size="small" label="Método" value={method}
                         onChange={e => setMethod(e.target.value as 'bootstrap' | 'gbm')}>
                <MenuItem value="bootstrap">Bootstrap (real)</MenuItem>
                <MenuItem value="gbm">GBM</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={6} sm={2} md={2}>
              <TextField
                fullWidth size="small" label="Horizonte" type="number" value={horizon}
                onChange={e => setHorizon(Math.max(1, Math.min(365, Number(e.target.value) || 30)))}
                InputProps={{ endAdornment: <InputAdornment position="end">días</InputAdornment> }}
              />
            </Grid>
            <Grid item xs={12} sm={6} md={2}>
              <Typography variant="caption" color="text.secondary">
                Shock inicial: {shock > 0 ? '+' : ''}{shock}%
              </Typography>
              <Slider
                size="small" min={-30} max={30} step={1} value={shock}
                onChange={(_, v) => setShock(v as number)}
                marks={[{ value: 0, label: '0' }]}
              />
            </Grid>
            <Grid item xs={12} md={1}>
              <Button
                fullWidth variant="contained" onClick={run} disabled={loading}
                startIcon={loading ? <CircularProgress size={16} /> : <PlayArrow />}
              >
                Simular
              </Button>
            </Grid>
          </Grid>
          <Box sx={{ mt: 1 }}>
            <Chip
              size="small" icon={<Warning fontSize="small" />}
              label={withVar ? 'VaR de inventario: activado' : 'VaR de inventario: desactivado'}
              color={withVar ? 'primary' : 'default'}
              onClick={() => setWithVar(v => !v)}
              variant={withVar ? 'filled' : 'outlined'}
              sx={{ cursor: 'pointer' }}
            />
          </Box>
        </CardContent>
      </Card>

      {error && <Alert severity="warning" sx={{ mb: 2 }}>{error}</Alert>}

      {result && (
        <>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} md={8}>
              <Card variant="outlined">
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <ShowChart color="primary" />
                    <Typography variant="subtitle1" fontWeight={600}>
                      Bandas de percentiles — {result.pair} ({result.market}, {result.method})
                    </Typography>
                  </Box>
                  <ResponsiveContainer width="100%" height={340}>
                    <AreaChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                      <XAxis dataKey="day" tick={{ fontSize: 12 }}
                             label={{ value: 'día', position: 'insideBottomRight', offset: -2, fontSize: 12 }} />
                      <YAxis tick={{ fontSize: 12 }} domain={['auto', 'auto']}
                             tickFormatter={(v: number) => v.toFixed(2)} />
                      <RTooltip formatter={(v: number, name: string) => [v.toFixed(4), name]} />
                      <Area type="monotone" dataKey="p95" stroke="none" fill="#1976d2" fillOpacity={0.10} />
                      <Area type="monotone" dataKey="p75" stroke="none" fill="#1976d2" fillOpacity={0.18} />
                      <Line type="monotone" dataKey="p50" stroke="#1976d2" strokeWidth={2} dot={false} />
                      <Area type="monotone" dataKey="p25" stroke="none" fill="#ffffff" fillOpacity={0.5} />
                      <Area type="monotone" dataKey="p5"  stroke="none" fill="#ffffff" fillOpacity={0.8} />
                    </AreaChart>
                  </ResponsiveContainer>
                  <Typography variant="caption" color="text.secondary">
                    Calibrado con {result.calibration.n_days} días reales
                    ({result.calibration.from} → {result.calibration.to}) ·
                    tasa actual {result.calibration.last_rate} ·
                    σ anualizada {result.params.sigma_annual_pct}%
                    {result.params.shock_pct !== 0 &&
                      ` · shock inicial ${result.params.shock_pct > 0 ? '+' : ''}${result.params.shock_pct}%`}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>

            <Grid item xs={12} md={4}>
              <Card variant="outlined" sx={{ mb: 2 }}>
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Casino color="secondary" />
                    <Typography variant="subtitle1" fontWeight={600}>
                      Distribución a {result.params.horizon_days} días
                    </Typography>
                  </Box>
                  {fd && (
                    <Grid container spacing={1}>
                      {[
                        ['Pesimista (p5)', fd.p5],
                        ['Mediana (p50)', fd.p50],
                        ['Optimista (p95)', fd.p95],
                        ['Media', fd.mean],
                      ].map(([label, v]) => (
                        <Grid item xs={6} key={label as string}>
                          <Typography variant="caption" color="text.secondary">{label}</Typography>
                          <Typography variant="h6" fontWeight={600}>{(v as number).toFixed(4)}</Typography>
                        </Grid>
                      ))}
                      <Grid item xs={12}>
                        <Divider sx={{ my: 1 }} />
                        <Tooltip title="Probabilidad de que la tasa termine por encima de la actual">
                          <Chip
                            label={`P(tasa sube) = ${((fd.prob_above_last ?? 0) * 100).toFixed(1)}%`}
                            color={(fd.prob_above_last ?? 0) >= 0.5 ? 'success' : 'warning'}
                            size="small"
                          />
                        </Tooltip>
                      </Grid>
                    </Grid>
                  )}
                </CardContent>
              </Card>

              {result.position_risk && (
                <Card variant="outlined">
                  <CardContent>
                    <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
                      Riesgo de la posición real
                    </Typography>
                    {result.position_risk.note || result.position_risk.error ? (
                      <Alert severity="info">
                        {result.position_risk.note ?? result.position_risk.error}
                      </Alert>
                    ) : (
                      <Grid container spacing={1}>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">Posición</Typography>
                          <Typography fontWeight={600}>
                            {result.position_risk.position_amount?.toLocaleString()} {result.pair.split('/')[0]}
                          </Typography>
                        </Grid>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">Valuación</Typography>
                          <Typography fontWeight={600}>{fmtBs(result.position_risk.valuation_bob)}</Typography>
                        </Grid>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">
                            VaR 95% ({result.params.horizon_days}d)
                          </Typography>
                          <Typography fontWeight={700} color="error.main">
                            {fmtBs(result.position_risk.var_bob)}
                          </Typography>
                        </Grid>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">Expected Shortfall</Typography>
                          <Typography fontWeight={700} color="error.main">
                            {fmtBs(result.position_risk.expected_shortfall_bob)}
                          </Typography>
                        </Grid>
                        <Grid item xs={12}>
                          <Typography variant="caption" color="text.secondary">
                            P&L esperado: {fmtBs(result.position_risk.pnl_mean_bob)}
                          </Typography>
                        </Grid>
                      </Grid>
                    )}
                  </CardContent>
                </Card>
              )}
            </Grid>
          </Grid>
        </>
      )}

      {!result && !loading && !error && (
        <Alert severity="info">
          Configura los parámetros y pulsa <b>Simular</b>. Prueba un shock de −15%
          para estresar una devaluación del paralelo.
        </Alert>
      )}
    </Box>
  );
};

export default Simulator;
