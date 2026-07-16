import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Grid, Card, CardContent, Paper, Tabs, Tab,
  FormControl, InputLabel, Select, MenuItem, Button, Chip,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  CircularProgress, Alert, Tooltip, IconButton, LinearProgress, Skeleton,
} from '@mui/material';
import {
  TrendingUp, TrendingDown, TrendingFlat, Refresh, Psychology,
  BarChart as BarChartIcon, CheckCircle, Warning, Info, ErrorOutline,
} from '@mui/icons-material';
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';

// ── Types ─────────────────────────────────────────────────────────────────────
interface ForecastPoint {
  date: string;
  predicted_transactions: number;
  predicted_volume: number;
}

interface Anomaly {
  date: string;
  value: number;
  expected: number;
  z_score: number;
  type: 'high' | 'low';
}

interface DashboardData {
  forecast_next_days: ForecastPoint[];
  trend: 'up' | 'down' | 'stable';
  anomalies: Anomaly[];
}

interface MLPredictionPoint {
  date: string;
  rate: number;
  buy_rate: number;
  sell_rate: number;
  confidence_lower: number;
  confidence_upper: number;
  confidence_score: number;
}

interface MLPredictionsData {
  currency_pair: string;
  predictions: Record<string, MLPredictionPoint[]>;
  generated_at: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────
const GREEN  = '#22c55e';
const RED    = '#ef4444';
const BLUE   = '#3b82f6';
const AMBER  = '#f59e0b';
const PURPLE = '#8b5cf6';

const MODEL_COLORS: Record<string, string> = {
  PROPHET:  BLUE,
  LSTM:     PURPLE,
  ARIMA:    AMBER,
  ENSEMBLE: GREEN,
};

const CURRENCY_PAIRS = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'ARS/BOB'];

const TOOLTIP_STYLE = {
  borderRadius: 8,
  border: '1px solid #e2e8f0',
  boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
  fontSize: 12,
  fontWeight: 500,
  background: '#fff',
};

// ── Sub-components ────────────────────────────────────────────────────────────
const TrendBadge = ({ trend }: { trend: 'up' | 'down' | 'stable' }) => {
  const cfg = {
    up:     { icon: <TrendingUp  />, label: 'Al alza',    color: GREEN,  bg: '#dcfce7' },
    down:   { icon: <TrendingDown/>, label: 'A la baja',  color: RED,    bg: '#fee2e2' },
    stable: { icon: <TrendingFlat/>, label: 'Estable',    color: BLUE,   bg: '#dbeafe' },
  }[trend];

  return (
    <Box sx={{
      display: 'inline-flex', alignItems: 'center', gap: 1,
      px: 2, py: 0.75, borderRadius: 99,
      bgcolor: cfg.bg, color: cfg.color, fontWeight: 700,
    }}>
      {cfg.icon}
      <Typography fontWeight={700} fontSize={14}>{cfg.label}</Typography>
    </Box>
  );
};

const ForecastChart = ({ data, loading }: { data: ForecastPoint[]; loading: boolean }) => {
  if (loading) return <Skeleton variant="rectangular" height={260} sx={{ borderRadius: 2 }} />;
  if (data.length === 0) return (
    <Box sx={{ py: 6, textAlign: 'center' }}>
      <Typography color="text.secondary">Sin datos de forecast disponibles</Typography>
    </Box>
  );
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 5, right: 10, left: -10, bottom: 0 }} barSize={28}>
        <CartesianGrid vertical={false} stroke="#f1f5f9" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 11, fill: '#94a3b8' }}
          tickFormatter={d => format(parseISO(d), 'dd/MM', { locale: es })}
          axisLine={false} tickLine={false}
        />
        <YAxis
          yAxisId="tx"
          tick={{ fontSize: 11, fill: '#94a3b8' }}
          axisLine={false} tickLine={false}
          label={{ value: 'Transacciones', angle: -90, position: 'insideLeft', offset: 14, fontSize: 10, fill: '#94a3b8' }}
        />
        <YAxis
          yAxisId="vol"
          orientation="right"
          tick={{ fontSize: 11, fill: '#94a3b8' }}
          axisLine={false} tickLine={false}
          tickFormatter={v => `${Math.round(v / 1000)}k`}
        />
        <RTooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={l => format(parseISO(l), 'EEEE dd/MM', { locale: es })}
          formatter={(v: any, name: string) =>
            name === 'Transacciones'
              ? [formatNumber(v, 0), name]
              : [formatCurrency(v), name]
          }
        />
        <Legend iconSize={8} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
        <Bar yAxisId="tx"  dataKey="predicted_transactions" name="Transacciones" fill={BLUE}  radius={[5,5,0,0]} />
        <Bar yAxisId="vol" dataKey="predicted_volume"        name="Volumen (BOB)" fill={GREEN} radius={[5,5,0,0]} />
      </BarChart>
    </ResponsiveContainer>
  );
};

const AnomaliesTable = ({ anomalies, loading }: { anomalies: Anomaly[]; loading: boolean }) => {
  if (loading) return <Skeleton variant="rectangular" height={120} sx={{ borderRadius: 2 }} />;
  if (anomalies.length === 0) return (
    <Alert severity="success" icon={<CheckCircle />}>
      Sin anomalías detectadas en los últimos 90 días.
    </Alert>
  );
  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow sx={{ '& th': { fontWeight: 700, color: '#64748b', fontSize: 12 } }}>
            <TableCell>Fecha</TableCell>
            <TableCell align="right">Transacciones</TableCell>
            <TableCell align="right">Esperado</TableCell>
            <TableCell align="right">Z-Score</TableCell>
            <TableCell align="center">Tipo</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {anomalies.map((a, i) => (
            <TableRow key={i} hover>
              <TableCell sx={{ fontFamily: 'monospace', fontSize: 13 }}>
                {format(parseISO(a.date), 'dd/MM/yyyy', { locale: es })}
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 700 }}>
                {formatNumber(a.value, 0)}
              </TableCell>
              <TableCell align="right" sx={{ color: '#64748b' }}>
                {a.expected}
              </TableCell>
              <TableCell align="right" sx={{
                fontFamily: 'monospace',
                fontWeight: 700,
                color: a.z_score > 0 ? GREEN : RED,
              }}>
                {a.z_score > 0 ? '+' : ''}{a.z_score}
              </TableCell>
              <TableCell align="center">
                <Chip
                  label={a.type === 'high' ? 'Alto' : 'Bajo'}
                  size="small"
                  sx={{
                    bgcolor: a.type === 'high' ? '#dcfce7' : '#fee2e2',
                    color:   a.type === 'high' ? GREEN : RED,
                    fontWeight: 700, fontSize: 11,
                  }}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
};

// ── Main component ────────────────────────────────────────────────────────────
const Predictions: React.FC = () => {
  const [tab,           setTab]           = useState(0);
  const [currencyPair,  setCurrencyPair]  = useState('USD/BOB');
  const [activeModels,  setActiveModels]  = useState<string[]>(['PROPHET','LSTM','ENSEMBLE']);

  // Simple dashboard state
  const [dashboard,  setDashboard]  = useState<DashboardData | null>(null);
  const [dashLoading, setDashLoading] = useState(true);
  const [dashError,   setDashError]   = useState<string | null>(null);

  // ML state
  const [mlPredictions, setMlPredictions] = useState<MLPredictionsData | null>(null);
  const [performance,   setPerformance]   = useState<any[]>([]);
  const [accuracy,      setAccuracy]      = useState<Record<string, any>>({});
  const [models,        setModels]        = useState<any[]>([]);
  const [mlLoading,     setMlLoading]     = useState(false);
  const [generating,    setGenerating]    = useState(false);
  const [training,      setTraining]      = useState(false);

  const { user }            = useAuth();
  const { enqueueSnackbar } = useSnackbar();

  // ── Load simple dashboard data ────────────────────────────────────────────
  const loadDashboard = useCallback(async () => {
    setDashLoading(true);
    setDashError(null);
    try {
      const res = await api.get('/predictions/dashboard/');
      setDashboard(res.data);
    } catch {
      setDashError('No se pudo cargar el resumen de predicciones.');
    } finally {
      setDashLoading(false);
    }
  }, []);

  // ── Load ML predictions ───────────────────────────────────────────────────
  const loadML = useCallback(async () => {
    setMlLoading(true);
    try {
      const [predRes, perfRes, accRes, modRes] = await Promise.allSettled([
        api.get('/predictions/predictions/current/', { params: { currency_pair: currencyPair } }),
        api.get('/predictions/models/performance/'),
        api.get('/predictions/predictions/accuracy-report/'),
        api.get('/predictions/models/'),
      ]);
      if (predRes.status === 'fulfilled') setMlPredictions(predRes.value.data);
      if (perfRes.status === 'fulfilled') setPerformance(perfRes.value.data);
      if (accRes.status  === 'fulfilled') setAccuracy(accRes.value.data);
      if (modRes.status  === 'fulfilled') setModels(modRes.value.data?.results ?? modRes.value.data ?? []);
    } finally {
      setMlLoading(false);
    }
  }, [currencyPair]);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);
  useEffect(() => {
    if (tab === 1 || tab === 2 || tab === 3) loadML();
  }, [tab, loadML]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await api.post('/predictions/predictions/generate/', { currency_pair: currencyPair, horizon: 24 });
      enqueueSnackbar('Predicciones ML generadas', { variant: 'success' });
      loadML();
    } catch {
      enqueueSnackbar('Error al generar predicciones ML', { variant: 'error' });
    } finally {
      setGenerating(false);
    }
  };

  const handleTrainAll = async () => {
    setTraining(true);
    try {
      await api.post('/predictions/models/train-all/');
      enqueueSnackbar('Entrenamiento iniciado en segundo plano', { variant: 'info' });
    } catch {
      enqueueSnackbar('Error al iniciar entrenamiento', { variant: 'error' });
    } finally {
      setTraining(false);
    }
  };

  // ── ML chart data ─────────────────────────────────────────────────────────
  const mlChartData = React.useMemo(() => {
    if (!mlPredictions?.predictions) return [];
    const allDates = new Set<string>();
    Object.values(mlPredictions.predictions).forEach(pts => pts.forEach(p => allDates.add(p.date as string)));
    return Array.from(allDates).sort().map(dateStr => {
      const point: any = { date: format(parseISO(dateStr), 'HH:mm', { locale: es }), full_date: dateStr };
      Object.entries(mlPredictions.predictions).forEach(([modelType, pts]) => {
        const m = pts.find(p => p.date === dateStr);
        if (m) {
          point[`${modelType}_rate`]  = m.rate;
          point[`${modelType}_buy`]   = m.buy_rate;
          point[`${modelType}_sell`]  = m.sell_rate;
          point[`${modelType}_lower`] = m.confidence_lower;
          point[`${modelType}_upper`] = m.confidence_upper;
        }
      });
      return point;
    });
  }, [mlPredictions]);

  const mlModelKeys = mlPredictions ? Object.keys(mlPredictions.predictions) : [];

  // ── KPIs for Tab 0 ────────────────────────────────────────────────────────
  const avgForecastTx  = dashboard?.forecast_next_days.length
    ? Math.round(dashboard.forecast_next_days.reduce((s, d) => s + d.predicted_transactions, 0) / dashboard.forecast_next_days.length)
    : null;
  const avgForecastVol = dashboard?.forecast_next_days.length
    ? Math.round(dashboard.forecast_next_days.reduce((s, d) => s + d.predicted_volume, 0) / dashboard.forecast_next_days.length)
    : null;

  return (
    <Box>
      {/* ── Header ── */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3} flexWrap="wrap" gap={1}>
        <Box display="flex" alignItems="center" gap={1.5}>
          <Psychology sx={{ fontSize: 32, color: BLUE }} />
          <Box>
            <Typography variant="h5" fontWeight={800} lineHeight={1.2}>Predicciones</Typography>
            <Typography variant="caption" color="text.secondary">
              Análisis predictivo de transacciones
            </Typography>
          </Box>
        </Box>
        <Box display="flex" gap={1} flexWrap="wrap">
          <Button
            variant="outlined"
            size="small"
            startIcon={<Refresh />}
            onClick={tab === 0 ? loadDashboard : loadML}
            disabled={dashLoading || mlLoading}
          >
            Actualizar
          </Button>
          {(tab === 1 || tab === 2) && (
            <>
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <InputLabel>Par de divisas</InputLabel>
                <Select value={currencyPair} onChange={e => setCurrencyPair(e.target.value)} label="Par de divisas">
                  {CURRENCY_PAIRS.map(p => <MenuItem key={p} value={p}>{p}</MenuItem>)}
                </Select>
              </FormControl>
              <Button
                variant="outlined"
                size="small"
                color="secondary"
                startIcon={generating ? <CircularProgress size={14} /> : <TrendingUp />}
                onClick={handleGenerate}
                disabled={generating}
              >
                Generar ML
              </Button>
              {user?.role === 'ADMIN' && (
                <Button
                  variant="contained"
                  size="small"
                  color="warning"
                  startIcon={training ? <CircularProgress size={14} /> : <Psychology />}
                  onClick={handleTrainAll}
                  disabled={training}
                >
                  Entrenar
                </Button>
              )}
            </>
          )}
        </Box>
      </Box>

      {/* ── Tabs ── */}
      <Paper sx={{ mb: 3, borderRadius: 2 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto">
          <Tab icon={<TrendingUp   sx={{ fontSize: 18 }} />} iconPosition="start" label="Resumen" />
          <Tab icon={<Psychology   sx={{ fontSize: 18 }} />} iconPosition="start" label="Modelo ML" />
          <Tab icon={<BarChartIcon sx={{ fontSize: 18 }} />} iconPosition="start" label="Precisión" />
          <Tab icon={<Info         sx={{ fontSize: 18 }} />} iconPosition="start" label="Gestión" />
        </Tabs>
      </Paper>

      {/* ══════════════════════════════════════════════════════════════════
          TAB 0 — Resumen: trend, forecast, anomalías
         ══════════════════════════════════════════════════════════════════ */}
      {tab === 0 && (
        <Box>
          {dashError && (
            <Alert severity="error" sx={{ mb: 2 }}
              action={<Button size="small" color="inherit" onClick={loadDashboard}>Reintentar</Button>}>
              {dashError}
            </Alert>
          )}

          {/* KPI cards */}
          <Grid container spacing={2} mb={3}>
            {/* Tendencia */}
            <Grid item xs={12} sm={6} md={3}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="body2" color="text.secondary" gutterBottom>Tendencia</Typography>
                  {dashLoading
                    ? <Skeleton width={120} height={40} />
                    : <TrendBadge trend={dashboard?.trend ?? 'stable'} />
                  }
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                    Últimos 14 días vs anteriores
                  </Typography>
                </CardContent>
              </Card>
            </Grid>

            {/* Tx promedio */}
            <Grid item xs={12} sm={6} md={3}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Tx promedio / día (próx. 7d)
                  </Typography>
                  {dashLoading
                    ? <Skeleton width={80} height={40} />
                    : <Typography variant="h4" fontWeight={800} color={BLUE}>
                        {avgForecastTx ?? '—'}
                      </Typography>
                  }
                </CardContent>
              </Card>
            </Grid>

            {/* Volumen promedio */}
            <Grid item xs={12} sm={6} md={3}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Volumen promedio / día
                  </Typography>
                  {dashLoading
                    ? <Skeleton width={100} height={40} />
                    : <Typography variant="h5" fontWeight={800} color={GREEN}>
                        {avgForecastVol != null ? formatCurrency(avgForecastVol) : '—'}
                      </Typography>
                  }
                </CardContent>
              </Card>
            </Grid>

            {/* Anomalías detectadas */}
            <Grid item xs={12} sm={6} md={3}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Anomalías (90 días)
                  </Typography>
                  {dashLoading
                    ? <Skeleton width={60} height={40} />
                    : <Typography variant="h4" fontWeight={800}
                        color={(dashboard?.anomalies.length ?? 0) > 0 ? AMBER : GREEN}>
                        {dashboard?.anomalies.length ?? 0}
                      </Typography>
                  }
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          {/* Forecast chart */}
          <Paper sx={{ p: 2.5, mb: 3, borderRadius: 2 }}>
            <Typography variant="h6" fontWeight={700} mb={2}>
              Forecast próximos 7 días
            </Typography>
            <ForecastChart data={dashboard?.forecast_next_days ?? []} loading={dashLoading} />
          </Paper>

          {/* Anomalies */}
          <Paper sx={{ p: 2.5, borderRadius: 2 }}>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
              <Typography variant="h6" fontWeight={700}>Anomalías detectadas</Typography>
              <Chip
                label={`Z-score > 2σ`}
                size="small"
                sx={{ bgcolor: '#f1f5f9', color: '#475569', fontWeight: 600 }}
              />
            </Box>
            <AnomaliesTable anomalies={dashboard?.anomalies ?? []} loading={dashLoading} />
          </Paper>
        </Box>
      )}

      {/* ══════════════════════════════════════════════════════════════════
          TAB 1 — Modelo ML: predicciones de tasas (24h)
         ══════════════════════════════════════════════════════════════════ */}
      {tab === 1 && (
        <Box>
          {mlLoading && (
            <Box display="flex" justifyContent="center" py={4}>
              <CircularProgress />
            </Box>
          )}

          {!mlLoading && mlChartData.length === 0 && (
            <Alert severity="info" sx={{ mb: 2 }}>
              No hay predicciones ML para {currencyPair}. Haz clic en "Generar ML" para crearlas.
              Los modelos deben estar entrenados.
            </Alert>
          )}

          {/* Model selector */}
          {!mlLoading && mlChartData.length > 0 && (
            <>
              <Box display="flex" gap={1} mb={2} flexWrap="wrap" alignItems="center">
                <Typography variant="body2" color="text.secondary">Modelos activos:</Typography>
                {Object.entries(MODEL_COLORS).map(([type, color]) => (
                  <Chip key={type} label={type} size="small"
                    onClick={() => setActiveModels(prev =>
                      prev.includes(type) ? prev.filter(m => m !== type) : [...prev, type]
                    )}
                    sx={{
                      bgcolor: activeModels.includes(type) ? color : 'transparent',
                      color:   activeModels.includes(type) ? 'white' : color,
                      border:  `2px solid ${color}`, fontWeight: 700, cursor: 'pointer',
                    }}
                  />
                ))}
              </Box>

              <Paper sx={{ p: 2, mb: 3, borderRadius: 2 }}>
                <Typography variant="h6" fontWeight={700} mb={2}>
                  Predicción de tasas — {currencyPair} (próximas 24h)
                </Typography>
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={mlChartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11 }}
                      tickFormatter={v => v.toFixed(3)} />
                    <RTooltip contentStyle={TOOLTIP_STYLE}
                      formatter={(v: any) => [Number(v).toFixed(4), '']} />
                    <Legend />
                    {mlModelKeys.filter(m => activeModels.includes(m)).map(modelType => (
                      <Line key={modelType} type="monotone" dataKey={`${modelType}_rate`}
                        name={modelType} stroke={MODEL_COLORS[modelType] ?? '#999'}
                        strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </Paper>

              {/* Confidence bands for first model */}
              {mlModelKeys.length > 0 && activeModels.includes(mlModelKeys[0]) && (
                <Paper sx={{ p: 2, borderRadius: 2 }}>
                  <Typography variant="h6" fontWeight={700} mb={2}>
                    Compra / Venta con intervalo de confianza — {mlModelKeys[0]}
                  </Typography>
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={mlChartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                      <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11 }}
                        tickFormatter={v => v.toFixed(3)} />
                      <RTooltip contentStyle={TOOLTIP_STYLE}
                        formatter={(v: any) => [Number(v).toFixed(4), '']} />
                      <Legend />
                      <Area type="monotone" dataKey={`${mlModelKeys[0]}_upper`}
                        name="Límite superior" stroke="transparent"
                        fill={MODEL_COLORS[mlModelKeys[0]] ?? BLUE} fillOpacity={0.12} />
                      <Area type="monotone" dataKey={`${mlModelKeys[0]}_lower`}
                        name="Límite inferior" stroke="transparent" fill="white" fillOpacity={1} />
                      <Line type="monotone" dataKey={`${mlModelKeys[0]}_buy`}
                        name="Compra" stroke={GREEN} strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey={`${mlModelKeys[0]}_sell`}
                        name="Venta" stroke={RED} strokeWidth={2} dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </Paper>
              )}
            </>
          )}
        </Box>
      )}

      {/* ══════════════════════════════════════════════════════════════════
          TAB 2 — Precisión de modelos
         ══════════════════════════════════════════════════════════════════ */}
      {tab === 2 && (
        <Box>
          {mlLoading && <Box display="flex" justifyContent="center" py={4}><CircularProgress /></Box>}
          {!mlLoading && Object.keys(accuracy).length === 0 && (
            <Alert severity="info">
              Sin datos de precisión. Los modelos necesitan predicciones evaluadas contra tasas reales.
            </Alert>
          )}
          {!mlLoading && Object.keys(accuracy).length > 0 && (
            <Grid container spacing={2}>
              {Object.entries(accuracy).map(([modelType, data]) => (
                <Grid item xs={12} md={6} lg={4} key={modelType}>
                  <Card>
                    <CardContent>
                      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                        <Typography variant="h6" fontWeight={700}
                          sx={{ color: MODEL_COLORS[modelType] }}>{modelType}</Typography>
                        <Chip
                          label={data.average_error < 1 ? 'Excelente' : data.average_error < 3 ? 'Bueno' : 'Mejorable'}
                          color={data.average_error < 1 ? 'success' : data.average_error < 3 ? 'warning' : 'error'}
                          size="small"
                        />
                      </Box>
                      {[
                        ['Total predicciones',  data.total_predictions],
                        ['Error promedio',       formatPercent(data.average_error)],
                        ['Error máximo',         formatPercent(data.max_error)],
                        ['Error mínimo',         formatPercent(data.min_error)],
                        ['Dentro del intervalo', data.within_confidence_interval],
                        ['Precisión confianza',  formatPercent(data.confidence_accuracy, 1)],
                      ].map(([label, value]) => (
                        <Box key={label as string} display="flex" justifyContent="space-between"
                          py={0.5} borderBottom="1px solid" borderColor="divider">
                          <Typography variant="body2" color="text.secondary">{label as string}</Typography>
                          <Typography variant="body2" fontWeight={700}>{String(value)}</Typography>
                        </Box>
                      ))}
                      <Box mt={1.5}>
                        <LinearProgress
                          variant="determinate"
                          value={data.confidence_accuracy ?? 0}
                          color={data.confidence_accuracy > 80 ? 'success' : data.confidence_accuracy > 60 ? 'warning' : 'error'}
                          sx={{ height: 6, borderRadius: 3 }}
                        />
                      </Box>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          )}
        </Box>
      )}

      {/* ══════════════════════════════════════════════════════════════════
          TAB 3 — Gestión de modelos ML
         ══════════════════════════════════════════════════════════════════ */}
      {tab === 3 && (
        <Box>
          {mlLoading && <Box display="flex" justifyContent="center" py={4}><CircularProgress /></Box>}
          {!mlLoading && models.length === 0 && (
            <Alert severity="info">
              No hay modelos ML entrenados. Usa "Entrenar" para iniciar el proceso (requiere datos históricos).
            </Alert>
          )}
          {!mlLoading && models.length > 0 && (
            <TableContainer component={Paper} sx={{ borderRadius: 2 }}>
              <Table>
                <TableHead>
                  <TableRow sx={{ '& th': { fontWeight: 700, color: '#64748b' } }}>
                    <TableCell>Nombre</TableCell>
                    <TableCell>Tipo</TableCell>
                    <TableCell>Par</TableCell>
                    <TableCell>Estado</TableCell>
                    <TableCell>Último entrenamiento</TableCell>
                    <TableCell>Métricas</TableCell>
                    {user?.role === 'ADMIN' && <TableCell>Acciones</TableCell>}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {models.map(model => (
                    <TableRow key={model.id} hover>
                      <TableCell><Typography fontWeight={700}>{model.name}</Typography></TableCell>
                      <TableCell>
                        <Chip label={model.model_type} size="small"
                          sx={{ bgcolor: MODEL_COLORS[model.model_type] ?? '#999', color: 'white' }} />
                      </TableCell>
                      <TableCell>{model.currency_pair}</TableCell>
                      <TableCell>
                        <Chip icon={model.is_active ? <CheckCircle /> : <Warning />}
                          label={model.is_active ? 'Activo' : 'Inactivo'}
                          color={model.is_active ? 'success' : 'default'} size="small" />
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption">
                          {model.last_trained
                            ? format(parseISO(model.last_trained), 'dd/MM/yyyy HH:mm', { locale: es })
                            : 'Nunca'}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        {model.metrics && Object.keys(model.metrics).length > 0 ? (
                          <Tooltip title={JSON.stringify(model.metrics, null, 2)}>
                            <IconButton size="small"><Info /></IconButton>
                          </Tooltip>
                        ) : (
                          <Typography variant="caption" color="text.secondary">—</Typography>
                        )}
                      </TableCell>
                      {user?.role === 'ADMIN' && (
                        <TableCell>
                          <Button size="small" variant="outlined"
                            color={model.is_active ? 'error' : 'success'}
                            onClick={async () => {
                              try {
                                await api.post(`/predictions/models/${model.id}/activate/`, { is_active: !model.is_active });
                                enqueueSnackbar(`Modelo ${model.is_active ? 'desactivado' : 'activado'}`, { variant: 'success' });
                                loadML();
                              } catch {
                                enqueueSnackbar('Error', { variant: 'error' });
                              }
                            }}
                          >
                            {model.is_active ? 'Desactivar' : 'Activar'}
                          </Button>
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Box>
      )}
    </Box>
  );
};

export default Predictions;
