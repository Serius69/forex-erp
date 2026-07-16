/**
 * Panel Macroeconómico de Bolivia — datos REALES.
 *
 * Fuentes (backend /api/macro/): World Bank (inflación, reservas, PIB, deuda,
 * tasa de interés, TC oficial promedio — anuales), open.er-api (USD internacional
 * diario) y brecha oficial↔paralelo calculada de las tasas propias del sistema.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Box, Card, CardContent, Chip, CircularProgress, Grid,
  MenuItem, Skeleton, TextField, Typography,
} from '@mui/material';
import {
  Public, TrendingUp, TrendingDown, AccountBalance, Savings,
  Percent, CompareArrows, Timeline as TimelineIcon,
} from '@mui/icons-material';
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip as RTooltip,
  XAxis, YAxis,
} from 'recharts';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatNumber, formatCompactNumber, formatPercent } from '../../utils/formatters';

interface IndicatorSummary {
  series: string;
  series_label: string;
  date: string;
  value: string;
  unit: string;
  source: string;
  age_days: number;
}

interface SeriesPoint { date: string; value: string; }

// Formateo por indicador — todo es-BO (coma decimal). % para tasas/brecha,
// US$ compacto para reservas/deuda, Bs para tipos de cambio.
const CARD_META: Record<string, { icon: React.ReactNode; fmt: (v: number) => string; hint: string }> = {
  inflacion_yoy:       { icon: <TrendingUp color="error" />,   fmt: v => formatPercent(v, 1), hint: 'Inflación anual (World Bank)' },
  reservas_usd:        { icon: <Savings color="primary" />,    fmt: v => `US$ ${formatCompactNumber(v)}`, hint: 'Reservas internacionales' },
  pib_crecimiento:     { icon: <TimelineIcon color="info" />,  fmt: v => formatPercent(v, 1), hint: 'Crecimiento del PIB' },
  deuda_externa_usd:   { icon: <AccountBalance color="warning" />, fmt: v => `US$ ${formatCompactNumber(v)}`, hint: 'Deuda externa total' },
  tasa_interes_activa: { icon: <Percent color="secondary" />,  fmt: v => formatPercent(v, 1), hint: 'Tasa de interés activa' },
  tc_oficial_promedio: { icon: <Public color="action" />,      fmt: v => `Bs ${formatNumber(v, 2)}`, hint: 'TC oficial promedio anual' },
  usd_internacional:   { icon: <CompareArrows color="primary" />, fmt: v => `Bs ${formatNumber(v, 3)}`, hint: 'USD/BOB internacional (er-api)' },
  brecha_oficial_pct:  { icon: <TrendingDown color="error" />, fmt: v => formatPercent(v, 2), hint: 'Brecha oficial ↔ paralelo digital' },
};

// ¿La serie seleccionada se expresa en porcentaje? (ejes/tooltip con % y coma)
const isPctSeries = (series: string, unit?: string) =>
  unit?.includes('%') ||
  ['inflacion_yoy', 'pib_crecimiento', 'tasa_interes_activa', 'brecha_oficial_pct'].includes(series);

const MacroPanel: React.FC = () => {
  const { enqueueSnackbar } = useSnackbar();
  const [summary, setSummary] = useState<IndicatorSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState('inflacion_yoy');
  const [points, setPoints] = useState<SeriesPoint[]>([]);
  const [seriesLoading, setSeriesLoading] = useState(false);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/macro/indicators/summary/');
      setSummary(res.data.indicators ?? []);
    } catch {
      enqueueSnackbar('No se pudieron cargar los indicadores macro', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar]);

  const loadSeries = useCallback(async (series: string) => {
    setSeriesLoading(true);
    try {
      const res = await api.get('/macro/indicators/series/', { params: { series } });
      setPoints(res.data.points ?? []);
    } catch {
      enqueueSnackbar('No se pudo cargar la serie', { variant: 'error' });
    } finally {
      setSeriesLoading(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { loadSeries(selected); }, [selected, loadSeries]);

  const chartData = points.map(p => ({ date: p.date, value: parseFloat(p.value) }));
  const selectedMeta = summary.find(s => s.series === selected);

  return (
    <Box sx={{ p: { xs: 2, md: 3 } }}>
      <Typography variant="h5" fontWeight={700} gutterBottom>
        Macro Bolivia
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Indicadores macroeconómicos reales (World Bank · er-api · tasas propias).
        La brecha oficial↔paralelo y el USD internacional se actualizan a diario.
      </Typography>

      {loading ? (
        <Grid container spacing={2}>
          {Array.from({ length: 8 }).map((_, i) => (
            <Grid item xs={12} sm={6} md={3} key={i}>
              <Skeleton variant="rounded" height={110} />
            </Grid>
          ))}
        </Grid>
      ) : summary.length === 0 ? (
        <Alert severity="info">
          Sin indicadores cargados. Ejecuta <code>python manage.py fetch_macro</code> en el backend.
        </Alert>
      ) : (
        <Grid container spacing={2}>
          {summary.map(ind => {
            const meta = CARD_META[ind.series];
            const value = parseFloat(ind.value);
            const isSelected = ind.series === selected;
            return (
              <Grid item xs={12} sm={6} md={3} key={ind.series}>
                <Card
                  variant={isSelected ? 'elevation' : 'outlined'}
                  sx={{
                    cursor: 'pointer', height: '100%',
                    borderColor: isSelected ? 'primary.main' : undefined,
                    boxShadow: isSelected ? 4 : undefined,
                  }}
                  onClick={() => setSelected(ind.series)}
                >
                  <CardContent sx={{ pb: '12px !important' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                      {meta?.icon}
                      <Typography variant="caption" color="text.secondary" noWrap>
                        {meta?.hint ?? ind.series_label}
                      </Typography>
                    </Box>
                    <Typography variant="h6" fontWeight={700}>
                      {meta ? meta.fmt(value) : ind.value}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap' }}>
                      <Chip size="small" label={ind.date} variant="outlined" />
                      <Chip
                        size="small"
                        color={ind.age_days > 400 ? 'warning' : 'success'}
                        label={ind.age_days === 0 ? 'hoy' : `hace ${ind.age_days}d`}
                      />
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      )}

      <Card variant="outlined" sx={{ mt: 3 }}>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 1 }}>
            <Typography variant="subtitle1" fontWeight={600}>
              {selectedMeta?.series_label ?? selected}
            </Typography>
            <TextField
              select size="small" value={selected} sx={{ minWidth: 260 }}
              onChange={e => setSelected(e.target.value)}
              label="Serie"
            >
              {summary.map(s => (
                <MenuItem key={s.series} value={s.series}>{s.series_label}</MenuItem>
              ))}
            </TextField>
          </Box>
          {seriesLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
              <CircularProgress />
            </Box>
          ) : chartData.length === 0 ? (
            <Alert severity="info">Serie sin datos aún.</Alert>
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={40} />
                <YAxis tick={{ fontSize: 12 }} domain={['auto', 'auto']}
                       tickFormatter={(v: number) => isPctSeries(selected, selectedMeta?.unit)
                         ? formatPercent(v, 1)
                         : Math.abs(v) >= 1e6 ? formatCompactNumber(v) : formatNumber(v, 2)} />
                <RTooltip formatter={(v: number) => [
                  isPctSeries(selected, selectedMeta?.unit) ? formatPercent(v, 2) : formatNumber(v, 2),
                  selectedMeta?.unit || 'valor',
                ]} />
                <Line type="monotone" dataKey="value" stroke="#1976d2" strokeWidth={2} dot={chartData.length < 40} />
              </LineChart>
            </ResponsiveContainer>
          )}
          {selectedMeta && (
            <Typography variant="caption" color="text.secondary">
              Fuente: {selectedMeta.source}
            </Typography>
          )}
        </CardContent>
      </Card>
    </Box>
  );
};

export default MacroPanel;
