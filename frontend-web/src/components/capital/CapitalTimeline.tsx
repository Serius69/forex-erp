/**
 * CapitalTimeline — Area chart showing capital composition over time.
 *
 * Features:
 *  - Area/line chart (capital_neto + optional sub-series)
 *  - Recharts Brush for on-chart zoom / pan
 *  - Quick preset buttons: 7D · 30D · 90D · 6M · 1Y
 *  - Custom date range via text inputs
 *  - Toggle series visibility
 *  - KPI bar: latest, delta, max, snapshots count
 *  - OPENING / CLOSING / MANUAL reference lines
 */
import React, { useState, useCallback } from 'react';
import {
  Box, Paper, Typography, Chip, Skeleton, Alert,
  ToggleButton, ToggleButtonGroup, TextField, IconButton,
  Tooltip, Grid, Divider,
} from '@mui/material';
import {
  Refresh, TrendingUp, TrendingDown, TrendingFlat,
} from '@mui/icons-material';
import { alpha, useTheme } from '@mui/material/styles';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer,
  Brush, ReferenceLine,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { formatCurrency, formatCompactNumber, formatPercentage } from '../../utils/formatters';
import { useCapitalTimeline, type RangePreset } from '../../hooks/useCapitalTimeline';

// ── Series config ─────────────────────────────────────────────────────────────

interface SeriesCfg {
  key:   string;
  label: string;
  color: string;
  dashed?: boolean;
}

const ALL_SERIES: SeriesCfg[] = [
  { key: 'capital_neto', label: 'Capital Neto',   color: '#2e7d32' },
  { key: 'efectivo_bob', label: 'Efectivo',        color: '#e65100' },
  { key: 'divisas_bob',  label: 'Divisas',         color: '#1565c0' },
  { key: 'tarjetas_bob', label: 'Tarjetas',        color: '#6a1b9a' },
  { key: 'qr_bob',       label: 'QR / Digital',   color: '#00695c', dashed: true },
  { key: 'pasivos_bob',  label: 'Pasivos',         color: '#b71c1c', dashed: true },
];

const PRESETS: { label: string; value: RangePreset }[] = [
  { label: '7D',  value: '7D'  },
  { label: '30D', value: '30D' },
  { label: '90D', value: '90D' },
  { label: '6M',  value: '6M'  },
  { label: '1Y',  value: '1Y'  },
];

// ── Custom tooltip ─────────────────────────────────────────────────────────────

const ChartTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  return (
    <Paper sx={{ p: 1.5, minWidth: 220, boxShadow: 3 }}>
      <Typography variant="caption" fontWeight={700} display="block" mb={0.5}>
        {point?.fecha ? format(parseISO(point.fecha), 'dd MMM yyyy') : label}
      </Typography>
      {point?.tipo && (
        <Chip
          label={point.tipo}
          size="small"
          color={point.tipo === 'CLOSING' ? 'primary' : point.tipo === 'OPENING' ? 'success' : 'default'}
          sx={{ mb: 0.75, height: 18, fontSize: '0.65rem' }}
        />
      )}
      {payload.map((p: any) => (
        <Box key={p.dataKey} display="flex" justifyContent="space-between" gap={2} py={0.15}>
          <Box display="flex" alignItems="center" gap={0.5}>
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: p.color }} />
            <Typography variant="caption" color="text.secondary">{p.name}</Typography>
          </Box>
          <Typography variant="caption" fontWeight={700}
            sx={{ fontVariantNumeric: 'tabular-nums', color: p.color }}>
            {formatCurrency(p.value)}
          </Typography>
        </Box>
      ))}
      {point?.generado_por && (
        <Typography variant="caption" color="text.disabled" display="block" mt={0.5}>
          {point.generado_por}
        </Typography>
      )}
    </Paper>
  );
};

// ── KPI chip ──────────────────────────────────────────────────────────────────

const KpiBlock = ({
  label, value, sub, color,
}: { label: string; value: string; sub?: string; color?: string }) => (
  <Box>
    <Typography variant="caption" color="text.secondary"
      textTransform="uppercase" fontWeight={700} letterSpacing={0.5}>
      {label}
    </Typography>
    <Typography variant="h6" fontWeight={800}
      sx={{ color: color ?? 'text.primary', fontVariantNumeric: 'tabular-nums', lineHeight: 1.2 }}>
      {value}
    </Typography>
    {sub && (
      <Typography variant="caption" color="text.secondary">{sub}</Typography>
    )}
  </Box>
);

// ── Main component ─────────────────────────────────────────────────────────────

interface CapitalTimelineProps {
  /** Show/hide the sub-series toggles (default: true) */
  showSeriesToggle?: boolean;
  /** Chart height in px (default: 340) */
  height?: number;
}

const CapitalTimeline: React.FC<CapitalTimelineProps> = ({
  showSeriesToggle = true,
  height = 340,
}) => {
  const theme = useTheme();
  const [visibleSeries, setVisibleSeries] = useState<string[]>(['capital_neto']);
  const [customFrom, setCustomFrom]       = useState('');
  const [customTo, setCustomTo]           = useState('');

  const {
    data, loading, error,
    dateFrom, dateTo, preset,
    setPreset, setCustomRange, refresh,
    stats,
  } = useCapitalTimeline('30D');

  const handlePreset = useCallback((_: React.MouseEvent, val: RangePreset | null) => {
    if (!val || val === 'custom') return;
    setPreset(val);
  }, [setPreset]);

  const handleCustomApply = useCallback(() => {
    if (!customFrom || !customTo || customFrom > customTo) return;
    setCustomRange(customFrom, customTo);
  }, [customFrom, customTo, setCustomRange]);

  const toggleSeries = useCallback((_: React.MouseEvent, keys: string[]) => {
    // Always keep at least capital_neto visible
    if (keys.length === 0) return;
    setVisibleSeries(keys);
  }, []);

  // Delta color/icon
  const deltaColor = !stats ? 'text.secondary'
    : stats.delta > 0 ? '#2e7d32'
    : stats.delta < 0 ? '#b71c1c'
    : 'text.secondary';

  const DeltaIcon = !stats ? TrendingFlat
    : stats.delta > 0 ? TrendingUp
    : stats.delta < 0 ? TrendingDown
    : TrendingFlat;

  return (
    <Paper variant="outlined" sx={{ p: 0, overflow: 'hidden' }}>
      {/* ── Header ── */}
      <Box
        px={2.5} py={1.75}
        display="flex" justifyContent="space-between" alignItems="center"
        sx={{ borderBottom: '1px solid', borderColor: 'divider' }}
      >
        <Typography variant="subtitle1" fontWeight={700}>
          Evolución del Capital
        </Typography>
        <Tooltip title="Actualizar">
          <span>
            <IconButton size="small" onClick={refresh} disabled={loading}>
              <Refresh fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {/* ── KPI bar ── */}
      {stats && !loading && (
        <Box
          px={2.5} py={1.5}
          display="flex" gap={4} flexWrap="wrap"
          sx={{ borderBottom: '1px solid', borderColor: 'divider',
                bgcolor: alpha(theme.palette.success.main, 0.03) }}
        >
          <KpiBlock
            label="Capital actual"
            value={formatCurrency(stats.latest)}
            color="#2e7d32"
          />
          <KpiBlock
            label="Variación período"
            value={formatPercentage(stats.deltaPct)}
            sub={`${stats.delta >= 0 ? '+' : ''}${formatCurrency(stats.delta)}`}
            color={deltaColor as string}
          />
          <KpiBlock
            label="Máximo"
            value={formatCurrency(stats.max)}
          />
          <KpiBlock
            label="Mínimo"
            value={formatCurrency(stats.min)}
          />
          <KpiBlock
            label="Snapshots"
            value={String(stats.count)}
            sub={`${dateFrom} → ${dateTo}`}
          />
        </Box>
      )}

      <Box p={2.5}>
        {/* ── Controls ── */}
        <Box display="flex" flexWrap="wrap" gap={1.5} alignItems="center" mb={2}>
          {/* Preset selector */}
          <ToggleButtonGroup
            value={preset !== 'custom' ? preset : null}
            exclusive
            onChange={handlePreset}
            size="small"
            sx={{ '& .MuiToggleButton-root': { px: 1.5, py: 0.4, fontSize: '0.75rem', fontWeight: 600 } }}
          >
            {PRESETS.map(p => (
              <ToggleButton key={p.value} value={p.value}>{p.label}</ToggleButton>
            ))}
          </ToggleButtonGroup>

          {/* Custom range */}
          <Box display="flex" gap={1} alignItems="center">
            <TextField
              type="date" size="small" label="Desde"
              value={customFrom || dateFrom}
              onChange={e => setCustomFrom(e.target.value)}
              InputLabelProps={{ shrink: true }}
              sx={{ width: 150 }}
              inputProps={{ max: dateTo }}
            />
            <TextField
              type="date" size="small" label="Hasta"
              value={customTo || dateTo}
              onChange={e => setCustomTo(e.target.value)}
              InputLabelProps={{ shrink: true }}
              sx={{ width: 150 }}
              inputProps={{ min: customFrom || dateFrom, max: new Date().toISOString().split('T')[0] }}
            />
            <Chip
              label="Aplicar"
              clickable
              onClick={handleCustomApply}
              disabled={!customFrom || !customTo || customFrom > customTo}
              color={preset === 'custom' ? 'primary' : 'default'}
              size="small"
              sx={{ fontWeight: 700 }}
            />
          </Box>
        </Box>

        {/* ── Series toggles ── */}
        {showSeriesToggle && (
          <Box mb={2}>
            <ToggleButtonGroup
              value={visibleSeries}
              onChange={toggleSeries}
              size="small"
              sx={{ flexWrap: 'wrap', gap: 0.5,
                '& .MuiToggleButton-root': { px: 1.25, py: 0.3, fontSize: '0.72rem', fontWeight: 600 } }}
            >
              {ALL_SERIES.map(s => (
                <ToggleButton
                  key={s.key} value={s.key}
                  sx={{
                    borderLeft: '1px solid !important',
                    borderRadius: '4px !important',
                    '&.Mui-selected': {
                      bgcolor: alpha(s.color, 0.12),
                      color: s.color,
                      borderColor: `${alpha(s.color, 0.4)} !important`,
                    },
                  }}
                >
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: s.color, mr: 0.6 }} />
                  {s.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Box>
        )}

        {/* ── Chart ── */}
        {error ? (
          <Alert severity="error">{error}</Alert>
        ) : loading ? (
          <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 1 }} />
        ) : data.length === 0 ? (
          <Alert severity="info">
            Sin snapshots registrados en el período seleccionado.
          </Alert>
        ) : (
          <ResponsiveContainer width="100%" height={height}>
            <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <defs>
                {ALL_SERIES.map(s => (
                  <linearGradient key={s.key} id={`grad-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={s.color} stopOpacity={0.18} />
                    <stop offset="95%" stopColor={s.color} stopOpacity={0} />
                  </linearGradient>
                ))}
              </defs>

              <CartesianGrid strokeDasharray="3 3" stroke={alpha(theme.palette.divider, 0.7)} />

              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: theme.palette.text.secondary }}
                tickLine={false}
                axisLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                tickFormatter={v => `${formatCompactNumber(v)}`}
                tick={{ fontSize: 11, fill: theme.palette.text.secondary }}
                tickLine={false}
                axisLine={false}
                width={56}
              />

              <RTooltip content={<ChartTooltip />} />

              <Legend
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
              />

              {/* CLOSING snapshots as reference lines */}
              {data
                .filter(d => d.tipo === 'CLOSING')
                .map(d => (
                  <ReferenceLine
                    key={d.fecha}
                    x={d.label}
                    stroke={alpha('#1565c0', 0.3)}
                    strokeDasharray="4 4"
                  />
                ))}

              {ALL_SERIES.filter(s => visibleSeries.includes(s.key)).map(s => (
                <Area
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color}
                  strokeWidth={s.key === 'capital_neto' ? 2.5 : 1.5}
                  strokeDasharray={s.dashed ? '5 3' : undefined}
                  fill={`url(#grad-${s.key})`}
                  dot={data.length <= 15}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
              ))}

              {/* Brush: on-chart zoom — start at last 30% of dataset */}
              <Brush
                dataKey="label"
                height={24}
                startIndex={Math.max(0, Math.floor(data.length * 0.7))}
                stroke={alpha(theme.palette.primary.main, 0.4)}
                fill={alpha(theme.palette.background.paper, 0.9)}
                travellerWidth={6}
                tickFormatter={() => ''}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </Box>
    </Paper>
  );
};

export default CapitalTimeline;
