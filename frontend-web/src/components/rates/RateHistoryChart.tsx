/**
 * RateHistoryChart — Gráfico histórico de tasas de cambio.
 * Muestra la evolución del tipo de cambio (compra/venta) en el tiempo.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, FormControl, InputLabel, Select, MenuItem,
  ToggleButton, ToggleButtonGroup, CircularProgress, Alert, Chip,
  Grid, Skeleton,
} from '@mui/material';
import { Refresh } from '@mui/icons-material';
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

const CURRENCIES = ['USD', 'EUR', 'CLP', 'PEN', 'BRL', 'ARS', 'GBP'];
const DAYS_OPTIONS = [7, 14, 30, 60, 90, 180, 365];
const MARKET_OPTIONS = [
  { value: '', label: 'Todos los mercados' },
  { value: 'paralelo_digital', label: 'Mercado paralelo' },
  { value: 'parallel', label: 'Paralelo (legacy)' },
  { value: 'digital', label: 'Digital' },
];

interface HistoryPoint {
  period: string;
  market_type: string;
  avg_buy: number;
  avg_sell: number;
  min_buy: number;
  max_sell: number;
}

interface HistoryResponse {
  currency: string;
  currency_name: string;
  scale_factor: number;
  days: number;
  aggregated: HistoryPoint[];
  total_points: number;
}

// Custom tooltip
const CustomTooltip = ({ active, payload, label, currency, scaleFactor }: any) => {
  if (!active || !payload?.length) return null;
  const scaleLabel = scaleFactor > 1 ? ` (por ${scaleFactor.toLocaleString()} ${currency})` : '';
  return (
    <Paper sx={{ p: 1.5, minWidth: 180 }}>
      <Typography variant="caption" fontWeight="bold" display="block" mb={0.5}>
        {label}
      </Typography>
      {payload.map((p: any) => (
        <Box key={p.dataKey} display="flex" justifyContent="space-between" gap={2}>
          <Typography variant="caption" color={p.color}>{p.name}</Typography>
          <Typography variant="caption" fontWeight="bold" sx={{ fontVariantNumeric: 'tabular-nums' }}>
            Bs. {Number(p.value).toFixed(4)}{scaleLabel}
          </Typography>
        </Box>
      ))}
    </Paper>
  );
};

const RateHistoryChart: React.FC = () => {
  const [currency,    setCurrency]    = useState('USD');
  const [days,        setDays]        = useState(30);
  const [market,      setMarket]      = useState('parallel');
  const [chartType,   setChartType]   = useState<'area' | 'line'>('area');
  const [data,        setData]        = useState<HistoryResponse | null>(null);
  const [loading,     setLoading]     = useState(false);
  const { enqueueSnackbar } = useSnackbar();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/rates/history/', {
        params: { currency, days, market, granularity: 'daily' },
      });
      setData(res.data);
    } catch {
      enqueueSnackbar('Error al cargar historial de tasas', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [currency, days, market, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  // Prepare chart data from aggregated per market_type
  const chartData = React.useMemo(() => {
    if (!data?.aggregated?.length) return [];

    // Group by period
    const map = new Map<string, any>();
    for (const p of data.aggregated) {
      const key = p.period?.substring(0, 10) ?? '';
      if (!map.has(key)) {
        map.set(key, { period: key, label: '' });
      }
      const entry = map.get(key)!;
      const prefix = p.market_type;
      entry[`${prefix}_buy`]  = p.avg_buy;
      entry[`${prefix}_sell`] = p.avg_sell;
    }

    return Array.from(map.values())
      .sort((a, b) => a.period.localeCompare(b.period))
      .map(d => ({
        ...d,
        label: (() => {
          try { return format(parseISO(d.period), 'dd/MM', { locale: es }); }
          catch { return d.period; }
        })(),
      }));
  }, [data]);

  // Determine which lines to show based on selected market
  const marketKey = market || 'parallel';
  const hasData = chartData.length > 0 && chartData.some(
    d => d[`${marketKey}_buy`] || d[`${marketKey}_sell`]
  );

  // Summary stats
  const lastPoint = chartData[chartData.length - 1];
  const firstPoint = chartData[0];
  const currentBuy  = lastPoint?.[`${marketKey}_buy`]  || 0;
  const currentSell = lastPoint?.[`${marketKey}_sell`] || 0;
  const changeBuy   = firstPoint ? currentBuy - (firstPoint[`${marketKey}_buy`] || currentBuy) : 0;
  const spread      = currentSell - currentBuy;
  const scaleFactor = data?.scale_factor || 1;

  const ChartComponent = chartType === 'area' ? AreaChart : LineChart;
  const DataComponent  = chartType === 'area' ? Area : Line as React.ComponentType<any>;

  return (
    <Box>
      {/* Controls */}
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={3}>
            <FormControl fullWidth size="small">
              <InputLabel>Divisa</InputLabel>
              <Select value={currency} label="Divisa"
                onChange={e => setCurrency(e.target.value)}>
                {CURRENCIES.map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={3}>
            <FormControl fullWidth size="small">
              <InputLabel>Mercado</InputLabel>
              <Select value={market} label="Mercado"
                onChange={e => setMarket(e.target.value)}>
                {MARKET_OPTIONS.map(m => (
                  <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={3}>
            <FormControl fullWidth size="small">
              <InputLabel>Período</InputLabel>
              <Select value={days} label="Período"
                onChange={e => setDays(Number(e.target.value))}>
                {DAYS_OPTIONS.map(d => (
                  <MenuItem key={d} value={d}>
                    {d < 30 ? `${d} días` : d === 30 ? '1 mes' : d === 60 ? '2 meses'
                      : d === 90 ? '3 meses' : d === 180 ? '6 meses' : '1 año'}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={3}>
            <ToggleButtonGroup value={chartType} exclusive size="small" fullWidth
              onChange={(_, v) => { if (v) setChartType(v); }}>
              <ToggleButton value="area">Área</ToggleButton>
              <ToggleButton value="line">Líneas</ToggleButton>
            </ToggleButtonGroup>
          </Grid>
        </Grid>
      </Paper>

      {/* KPI Cards */}
      {!loading && data && (
        <Grid container spacing={2} mb={2}>
          {[
            {
              label: 'Compra actual',
              value: `Bs. ${currentBuy.toFixed(4)}`,
              color: '#2e7d32',
              sub: changeBuy !== 0
                ? `${changeBuy >= 0 ? '+' : ''}${changeBuy.toFixed(4)} vs ${days}d atrás`
                : `Sin cambio`,
            },
            {
              label: 'Venta actual',
              value: `Bs. ${currentSell.toFixed(4)}`,
              color: '#1976d2',
              sub: `Spread: Bs. ${spread.toFixed(4)}`,
            },
            {
              label: 'Puntos de datos',
              value: data.total_points.toLocaleString(),
              color: '#7b1fa2',
              sub: `${days} días · ${data.aggregated.length} períodos`,
            },
          ].map(kpi => (
            <Grid item xs={12} sm={4} key={kpi.label}>
              <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                <Typography variant="caption" color="text.secondary" display="block">
                  {kpi.label}{scaleFactor > 1 ? ` (por ${scaleFactor.toLocaleString()})` : ''}
                </Typography>
                <Typography variant="h5" fontWeight="bold" color={kpi.color}
                  sx={{ fontVariantNumeric: 'tabular-nums' }}>
                  {kpi.value}
                </Typography>
                <Typography variant="caption" color="text.secondary">{kpi.sub}</Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
      )}

      {/* Chart */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
          <Typography variant="subtitle1" fontWeight="bold">
            Evolución {currency}/BOB
            {scaleFactor > 1 && (
              <Chip label={`por ${scaleFactor.toLocaleString()} unidades`}
                size="small" sx={{ ml: 1 }} />
            )}
          </Typography>
          {loading && <CircularProgress size={20} />}
        </Box>

        {loading ? (
          <Skeleton variant="rectangular" height={320} sx={{ borderRadius: 1 }} />
        ) : !hasData ? (
          <Alert severity="info">
            No hay datos históricos para {currency} en los últimos {days} días.
            Las tasas se registran automáticamente cuando el sistema está activo.
            También puedes importar datos históricos desde Excel.
          </Alert>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <ChartComponent data={chartData}>
              <defs>
                <linearGradient id="buyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#2e7d32" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#2e7d32" stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="sellGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#1976d2" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#1976d2" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11 }}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 11 }}
                tickFormatter={v => `${Number(v).toFixed(2)}`}
                domain={['auto', 'auto']}
                width={60}
              />
              <RTooltip
                content={<CustomTooltip currency={currency} scaleFactor={scaleFactor} />}
              />
              <Legend />
              <DataComponent
                type="monotone"
                dataKey={`${marketKey}_buy`}
                name="Compra"
                stroke="#2e7d32"
                strokeWidth={2}
                fill={chartType === 'area' ? 'url(#buyGrad)' : undefined}
                dot={false}
                connectNulls
              />
              <DataComponent
                type="monotone"
                dataKey={`${marketKey}_sell`}
                name="Venta"
                stroke="#1976d2"
                strokeWidth={2}
                fill={chartType === 'area' ? 'url(#sellGrad)' : undefined}
                dot={false}
                connectNulls
              />
            </ChartComponent>
          </ResponsiveContainer>
        )}
      </Paper>
    </Box>
  );
};

export default RateHistoryChart;
