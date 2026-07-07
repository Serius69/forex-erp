import React, { useMemo, memo } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Skeleton,
  Alert, Button, Chip, LinearProgress, Tooltip,
} from '@mui/material';
import {
  AccountBalance, TrendingUp, TrendingDown, ShowChart,
  SwapHoriz, Warning, CheckCircle, Assessment, Savings,
  CurrencyExchange, BarChart as BarChartIcon, ArrowUpward, ArrowDownward,
} from '@mui/icons-material';
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  FunnelChart, Funnel, LabelList,
  XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts';
import { alpha } from '@mui/material/styles';
import { motion } from 'framer-motion';
import { TOKENS } from '../../styles/theme';
import { formatCurrency, formatNumber, formatCompactNumber, formatPercentage } from '../../utils/formatters';
import { useCEODashboard } from '../../hooks/useCEODashboard';
import KPIBox from '../common/KPIBox';
import ChartCard from '../common/ChartCard';
import InsightCard, { Insight } from '../common/InsightCard';
import AlertBanner, { AlertItem } from '../common/AlertBanner';
import DashboardLayout from '../common/DashboardLayout';

// ── Constants ─────────────────────────────────────────────────────────────────
const PIE_COLORS = [TOKENS.blue, TOKENS.green, TOKENS.amber, TOKENS.red, '#8B5CF6', '#06B6D4'];

const TOOLTIP_STYLE = {
  borderRadius: 8,
  border: `1px solid ${TOKENS.border}`,
  boxShadow: '0 4px 16px rgba(15,23,42,0.1)',
  fontSize: 12,
  fontWeight: 500,
  background: TOKENS.surface,
};

const DAYS  = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
const HOURS = ['0h', '3h', '6h', '9h', '12h', '15h', '18h', '21h'];

// ── Chart Tooltip ─────────────────────────────────────────────────────────────
const ChartTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <Box sx={{
      bgcolor: TOKENS.surface,
      border: `1px solid ${TOKENS.border}`,
      borderRadius: 2, px: 2, py: 1.5,
      boxShadow: '0 4px 16px rgba(15,23,42,0.1)',
    }}>
      {label && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
          {label}
        </Typography>
      )}
      {payload.map((p: any, i: number) => (
        <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.25 }}>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: p.color, flexShrink: 0 }} />
          <Typography variant="body2" fontWeight={600}>
            {p.name}: {formatCurrency(p.value)}
          </Typography>
        </Box>
      ))}
    </Box>
  );
};

// ── Activity Heatmap ──────────────────────────────────────────────────────────
const ActivityHeatmap = memo(({
  heatmap,
  loading,
}: {
  heatmap: { day: number; hour: number; count: number }[];
  loading: boolean;
}) => {
  const maxCount = useMemo(() => Math.max(...heatmap.map(h => h.count), 1), [heatmap]);

  const getCount = (day: number, hour: number) =>
    heatmap.find(h => h.day === day && h.hour === hour)?.count ?? 0;

  const getColor = (count: number) => {
    if (count === 0) return alpha(TOKENS.border, 0.5);
    const intensity = count / maxCount;
    if (intensity > 0.75) return TOKENS.blue;
    if (intensity > 0.5)  return alpha(TOKENS.blue, 0.7);
    if (intensity > 0.25) return alpha(TOKENS.blue, 0.45);
    return alpha(TOKENS.blue, 0.2);
  };

  if (loading) {
    return <Skeleton variant="rectangular" height={148} sx={{ borderRadius: 2 }} />;
  }

  if (heatmap.length === 0) {
    return (
      <Box sx={{
        height: 148, display: 'flex', alignItems: 'center', justifyContent: 'center',
        bgcolor: TOKENS.bg, borderRadius: 2,
      }}>
        <Typography variant="body2" color="text.secondary">Sin datos de actividad</Typography>
      </Box>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 0.5, mb: 0.75 }}>
        <Box sx={{ width: 28 }} />
        {Array.from({ length: 24 }, (_, h) => (
          <Box key={h} sx={{ flex: 1, textAlign: 'center' }}>
            {h % 3 === 0 && (
              <Typography variant="caption" sx={{ fontSize: '0.6rem', color: TOKENS.muted }}>
                {h}h
              </Typography>
            )}
          </Box>
        ))}
      </Box>
      {DAYS.map((day, d) => (
        <Box key={day} sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
          <Typography variant="caption" sx={{ width: 28, fontSize: '0.65rem', color: TOKENS.muted, flexShrink: 0 }}>
            {day}
          </Typography>
          {Array.from({ length: 24 }, (_, h) => {
            const count = getCount(d, h);
            return (
              <Tooltip
                key={h}
                title={`${day} ${h}h: ${count} operaciones`}
                placement="top"
                arrow
              >
                <Box sx={{
                  flex: 1,
                  height: 14,
                  borderRadius: '3px',
                  bgcolor: getColor(count),
                  cursor: 'default',
                  transition: 'transform 0.1s',
                  '&:hover': { transform: 'scale(1.3)' },
                }} />
              </Tooltip>
            );
          })}
        </Box>
      ))}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 0.75, mt: 1 }}>
        <Typography variant="caption" sx={{ fontSize: '0.65rem', color: TOKENS.muted }}>Menos</Typography>
        {[0, 0.25, 0.5, 0.75, 1].map(intensity => (
          <Box
            key={intensity}
            sx={{
              width: 12, height: 12, borderRadius: '3px',
              bgcolor: intensity === 0 ? alpha(TOKENS.border, 0.5) : alpha(TOKENS.blue, intensity),
            }}
          />
        ))}
        <Typography variant="caption" sx={{ fontSize: '0.65rem', color: TOKENS.muted }}>Más</Typography>
      </Box>
    </Box>
  );
});
ActivityHeatmap.displayName = 'ActivityHeatmap';

// ── Inventory Status ──────────────────────────────────────────────────────────
const InventoryStatus = memo(({
  inventory,
  loading,
}: {
  inventory: { currency: string; branch: string; stock: number; stock_pct: number; status: string }[];
  loading: boolean;
}) => (
  <Card sx={{ height: '100%' }}>
    <CardContent>
      <Typography variant="h6" fontWeight={700} mb={2}>Estado de Inventario</Typography>
      {loading ? (
        <Grid container spacing={1}>
          {Array.from({ length: 6 }).map((_, i) => (
            <Grid item key={i} xs={6} sm={4}>
              <Skeleton variant="rectangular" height={72} sx={{ borderRadius: 2 }} />
            </Grid>
          ))}
        </Grid>
      ) : inventory.length === 0 ? (
        <Box sx={{ py: 3, textAlign: 'center' }}>
          <Typography variant="body2" color="text.secondary">Sin datos de inventario</Typography>
        </Box>
      ) : (
        <Grid container spacing={1}>
          {inventory.map((inv, i) => (
            <Grid item key={i} xs={6} sm={4} md={3}>
              <Box sx={{
                p: 1.5, borderRadius: 2,
                border: `1px solid ${
                  inv.status === 'CRITICAL' ? alpha(TOKENS.red, 0.3) :
                  inv.status === 'LOW'      ? alpha(TOKENS.amber, 0.3) :
                  TOKENS.border
                }`,
                bgcolor: inv.status === 'CRITICAL' ? alpha(TOKENS.red, 0.04) :
                         inv.status === 'LOW'      ? alpha(TOKENS.amber, 0.04) : 'transparent',
              }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.75 }}>
                  <Typography variant="body2" fontWeight={700}>{inv.currency}</Typography>
                  <Chip
                    label={inv.status}
                    size="small"
                    color={inv.status === 'CRITICAL' ? 'error' : inv.status === 'LOW' ? 'warning' : 'success'}
                  />
                </Box>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
                  {inv.branch || 'Principal'}
                </Typography>
                <LinearProgress
                  variant="determinate"
                  value={Math.min(inv.stock_pct, 100)}
                  color={inv.status === 'CRITICAL' ? 'error' : inv.status === 'LOW' ? 'warning' : 'primary'}
                  sx={{ mb: 0.5 }}
                />
                <Typography variant="caption" color="text.secondary">
                  {inv.stock_pct.toFixed(0)}% del máximo
                </Typography>
              </Box>
            </Grid>
          ))}
        </Grid>
      )}
    </CardContent>
  </Card>
));
InventoryStatus.displayName = 'InventoryStatus';

// ── CEO Dashboard ─────────────────────────────────────────────────────────────
const ExecutiveDashboard: React.FC = () => {
  const { data, loading, refreshing, error, refresh } = useCEODashboard();

  const safeNum = (v: any) => (v == null || isNaN(Number(v)) ? 0 : Number(v));

  // ── Insights ───────────────────────────────────────────────────────────────
  const insights = useMemo((): Insight[] => {
    if (!data) return [];
    const items: Insight[] = [];
    const all = data.currencies.all ?? [];
    const total = all.reduce((s, c) => s + safeNum(c.ganancia_bob), 0);

    if (data.currencies.best && total > 0) {
      const pct = (safeNum(data.currencies.best.ganancia) / total * 100).toFixed(0);
      items.push({
        text: `${data.currencies.best.currency_code} genera el ${pct}% de los ingresos del mes`,
        type: 'positive',
      });
    }

    const growth = safeNum(data.kpis?.monthly_growth_pct);
    if (growth !== 0) {
      items.push({
        text: growth > 0
          ? `Creciste ${growth.toFixed(1)}% vs el mes anterior`
          : `Caída del ${Math.abs(growth).toFixed(1)}% vs el mes anterior`,
        type: growth > 0 ? 'positive' : 'negative',
      });
    }

    const netMargin = safeNum(data.kpis?.net_margin);
    if (netMargin > 0) {
      items.push({
        text: `Margen neto del ${netMargin.toFixed(1)}% este mes`,
        type: netMargin > 5 ? 'positive' : netMargin > 2 ? 'neutral' : 'warning',
      });
    }

    if (data.exposure.critical_count > 0) {
      items.push({
        text: `${data.exposure.critical_count} posición(es) en estado crítico requieren atención`,
        type: 'warning',
      });
    }

    if (data.currencies.worst) {
      items.push({
        text: `${data.currencies.worst.currency_code} es la divisa con menor rendimiento`,
        type: 'neutral',
      });
    }

    const monthPnl = safeNum(data.pnl.month.ganancia_neta);
    const prevPnl  = safeNum(data.pnl.prev_month?.ganancia_neta);
    if (prevPnl > 0 && monthPnl > 0) {
      const diff = ((monthPnl - prevPnl) / prevPnl * 100).toFixed(1);
      items.push({
        text: `P&L del mes ${Number(diff) >= 0 ? 'superior' : 'inferior'} al mes anterior en ${Math.abs(Number(diff))}%`,
        type: Number(diff) >= 0 ? 'positive' : 'negative',
      });
    }

    return items.slice(0, 5);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Alerts ─────────────────────────────────────────────────────────────────
  const alerts = useMemo((): AlertItem[] =>
    (data?.alerts ?? []).map((a, i) => ({
      id:       `ceo-alert-${i}`,
      message:  a.message,
      severity: a.severity === 'CRITICAL' ? 'critical' : a.severity === 'WARNING' ? 'warning' : 'info',
    })),
  [data]);

  // ── Chart data ─────────────────────────────────────────────────────────────
  const currencyChartData = useMemo(
    () => (data?.currencies.all ?? [])
      .map(c => ({ name: c.currency, ganancia: Math.round(safeNum(c.ganancia_bob) * 100) / 100 }))
      .sort((a, b) => b.ganancia - a.ganancia)
      .slice(0, 8),
    [data], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const inventoryPie = useMemo(
    () => (data?.inventory ?? []).slice(0, 6).map((inv, i) => ({
      name:  `${inv.currency}${inv.branch ? ` (${inv.branch})` : ''}`,
      value: inv.stock,
      color: PIE_COLORS[i % PIE_COLORS.length],
    })),
    [data],
  );

  const monthlyComparison = data?.monthly_comparison ?? [];

  const funnelData = useMemo(() => {
    if (!data) return [];
    const month = data.transactions.month;
    return [
      { name: 'Volumen total', value: Math.round(safeNum(month.volume_bob)), fill: TOKENS.blue },
      { name: 'Transacciones', value: month.count * 1000,                   fill: TOKENS.blueMid },
      { name: 'Completadas',   value: (month.count - 1) * 1000,             fill: TOKENS.green },
      { name: 'Con ganancia',  value: Math.round(safeNum(data.pnl.month.ganancia_neta)), fill: '#10B981' },
    ].filter(d => d.value > 0);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── KPIs ───────────────────────────────────────────────────────────────────
  const strategicKPIs = useMemo(() => {
    if (!data) return [];
    return [
      {
        title:    'ROI Mensual',
        value:    data.kpis?.roi_monthly != null
          ? formatPercentage(safeNum(data.kpis.roi_monthly))
          : data.capital.total_bob > 0
            ? formatPercentage(safeNum(data.pnl.month.ganancia_neta) / safeNum(data.capital.total_bob) * 100)
            : '—',
        icon:     <ShowChart />,
        accent:   TOKENS.blue,
      },
      {
        title:    'Margen neto',
        value:    data.kpis?.net_margin != null
          ? formatPercentage(safeNum(data.kpis.net_margin))
          : data.pnl.month.ingreso_ventas > 0
            ? formatPercentage(safeNum(data.pnl.month.ganancia_neta) / safeNum(data.pnl.month.ingreso_ventas) * 100)
            : '—',
        icon:     <BarChartIcon />,
        accent:   TOKENS.green,
      },
      {
        title:    'EBITDA estimado',
        value:    data.kpis?.ebitda != null
          ? formatCurrency(data.kpis.ebitda)
          : formatCurrency(safeNum(data.pnl.month.ganancia_neta) + safeNum(data.pnl.month.gastos_operativos) * 0.3),
        icon:     <Assessment />,
        accent:   TOKENS.amber,
      },
      {
        title:    'Crecimiento mensual',
        value:    data.kpis?.monthly_growth_pct != null
          ? formatPercentage(safeNum(data.kpis.monthly_growth_pct))
          : '—',
        change:   data.kpis?.monthly_growth_pct,
        icon:     safeNum(data.kpis?.monthly_growth_pct) >= 0 ? <TrendingUp /> : <TrendingDown />,
        accent:   safeNum(data.kpis?.monthly_growth_pct) >= 0 ? TOKENS.green : TOKENS.red,
      },
      {
        title:    'Capital total',
        value:    formatCurrency(safeNum(data.capital.total_bob)),
        subtitle: `${data.capital.branches} sucursal(es)`,
        icon:     <AccountBalance />,
        accent:   TOKENS.blue,
      },
      {
        title:    'Ganancia acumulada',
        value:    data.kpis?.accumulated_profit != null
          ? formatCurrency(data.kpis.accumulated_profit)
          : formatCurrency(safeNum(data.pnl.month.ganancia_neta)),
        icon:     <Savings />,
        accent:   safeNum(data.pnl.month.ganancia_neta) >= 0 ? TOKENS.green : TOKENS.red,
      },
    ];
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const pnlKPIs = useMemo(() => {
    if (!data) return [];
    const { pnl, transactions } = data;
    return [
      {
        title:    'P&L Hoy',
        value:    formatCurrency(safeNum(pnl.today.ganancia_neta)),
        subtitle: `Ventas: ${formatCompactNumber(safeNum(pnl.today.ingreso_ventas))}`,
        icon:     safeNum(pnl.today.ganancia_neta) >= 0 ? <TrendingUp /> : <TrendingDown />,
        accent:   safeNum(pnl.today.ganancia_neta) >= 0 ? TOKENS.green : TOKENS.red,
      },
      {
        title:    'P&L Semana',
        value:    formatCurrency(safeNum(pnl.week.ganancia_neta)),
        subtitle: `${transactions.week.count} operaciones`,
        icon:     <ShowChart />,
        accent:   safeNum(pnl.week.ganancia_neta) >= 0 ? TOKENS.green : TOKENS.red,
      },
      {
        title:    'P&L Mes',
        value:    formatCurrency(safeNum(pnl.month.ganancia_neta)),
        subtitle: `${transactions.month.count} transacciones`,
        icon:     <Assessment />,
        accent:   safeNum(pnl.month.ganancia_neta) >= 0 ? TOKENS.green : TOKENS.red,
      },
      {
        title:    'Transacciones hoy',
        value:    formatNumber(transactions.today.count, 0),
        subtitle: `${transactions.today.buys} compras · ${transactions.today.sells} ventas`,
        icon:     <SwapHoriz />,
        accent:   TOKENS.blue,
      },
      {
        title:    'Volumen semana',
        value:    formatCurrency(safeNum(transactions.week.volume_bob)),
        subtitle: `${transactions.week.count} ops.`,
        icon:     <CurrencyExchange />,
        accent:   TOKENS.blue,
      },
      {
        title:    'Exposición total',
        value:    formatCurrency(safeNum(data.exposure.total_exposure_bob)),
        subtitle: `PnL no realizado: ${formatCompactNumber(safeNum(data.exposure.unrealized_pnl_bob))}`,
        icon:     data.exposure.critical_count > 0 ? <Warning /> : <CheckCircle />,
        accent:   data.exposure.critical_count > 0 ? TOKENS.red : TOKENS.green,
      },
    ];
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const cacheInfo = data
    ? `${data.from_cache ? 'Caché' : 'Tiempo real'} · ${new Date(data.generated_at).toLocaleTimeString('es-BO')}`
    : undefined;

  if (error && !loading) {
    return (
      <DashboardLayout title="Dashboard CEO" onRefresh={() => refresh(true)} refreshing={refreshing}>
        <Alert
          severity="error"
          action={<Button size="small" color="inherit" onClick={() => refresh(true)}>Reintentar</Button>}
        >
          {error}
        </Alert>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout
      title="Dashboard CEO"
      badge="ESTRATÉGICO"
      badgeColor={TOKENS.amber}
      subtitle={cacheInfo}
      onRefresh={() => refresh(true)}
      refreshing={refreshing}
    >
      {alerts.length > 0 && <AlertBanner alerts={alerts} />}

      <Grid container spacing={2.5}>
        {/* ── KPIs Estratégicos ── */}
        {loading
          ? Array.from({ length: 6 }).map((_, i) => (
            <Grid item key={i} xs={6} sm={4} md={2}>
              <Skeleton variant="rectangular" height={120} sx={{ borderRadius: '14px' }} />
            </Grid>
          ))
          : strategicKPIs.map((kpi, i) => (
            <Grid item key={kpi.title} xs={6} sm={4} md={2}>
              <KPIBox {...kpi} loading={false} delay={i * 0.04} />
            </Grid>
          ))
        }

        {/* ── P&L KPIs ── */}
        {loading
          ? Array.from({ length: 6 }).map((_, i) => (
            <Grid item key={i} xs={6} sm={4} md={2}>
              <Skeleton variant="rectangular" height={110} sx={{ borderRadius: '14px' }} />
            </Grid>
          ))
          : pnlKPIs.map((kpi, i) => (
            <Grid item key={kpi.title} xs={6} sm={4} md={2}>
              <KPIBox {...kpi} loading={false} delay={0.25 + i * 0.04} />
            </Grid>
          ))
        }

        {/* ── Monthly Comparison Line Chart ── */}
        <Grid item xs={12} md={8}>
          <ChartCard
            title="Comparación mensual"
            subtitle="Mes actual vs mes anterior (BOB)"
            loading={loading}
            height={240}
            isEmpty={monthlyComparison.length === 0}
            delay={0.15}
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={monthlyComparison} margin={{ top: 5, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke={TOKENS.border} />
                <XAxis
                  dataKey="month"
                  tick={{ fontSize: 10, fill: TOKENS.muted }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: TOKENS.muted }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={v => formatCompactNumber(v)}
                />
                <RTooltip content={<ChartTooltip />} />
                <Legend iconSize={8} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                <ReferenceLine y={0} stroke={TOKENS.border} />
                <Line
                  type="monotone"
                  dataKey="current"
                  name="Mes actual"
                  stroke={TOKENS.blue}
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: TOKENS.blue, strokeWidth: 0 }}
                  activeDot={{ r: 5, strokeWidth: 0 }}
                />
                <Line
                  type="monotone"
                  dataKey="previous"
                  name="Mes anterior"
                  stroke={TOKENS.muted}
                  strokeWidth={2}
                  strokeDasharray="5 3"
                  dot={{ r: 3, fill: TOKENS.muted, strokeWidth: 0 }}
                  activeDot={{ r: 5, strokeWidth: 0 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        </Grid>

        {/* ── Insights ── */}
        <Grid item xs={12} md={4}>
          <InsightCard insights={insights} loading={loading} />
        </Grid>

        {/* ── Profit by Currency ── */}
        <Grid item xs={12} md={7}>
          <ChartCard
            title="Ganancia por divisa"
            subtitle="Mes actual (BOB)"
            loading={loading}
            height={230}
            isEmpty={currencyChartData.length === 0}
            delay={0.2}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={currencyChartData} margin={{ top: 5, right: 8, left: -16, bottom: 0 }} barSize={28}>
                <CartesianGrid vertical={false} stroke={TOKENS.border} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 11, fill: TOKENS.muted }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: TOKENS.muted }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={v => formatCompactNumber(v)}
                />
                <RTooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [formatCurrency(v), 'Ganancia']}
                />
                <ReferenceLine y={0} stroke={TOKENS.border} />
                <Bar dataKey="ganancia" name="Ganancia" radius={[6, 6, 0, 0]}>
                  {currencyChartData.map((entry, i) => (
                    <Cell
                      key={i}
                      fill={entry.ganancia >= 0 ? TOKENS.blue : TOKENS.red}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </Grid>

        {/* ── Inventory Distribution Pie ── */}
        <Grid item xs={12} md={5}>
          <ChartCard
            title="Distribución inventario"
            subtitle="Stock por divisa"
            loading={loading}
            height={230}
            isEmpty={inventoryPie.length === 0}
            delay={0.25}
          >
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={inventoryPie}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={82}
                  innerRadius={38}
                  paddingAngle={2}
                >
                  {inventoryPie.map((entry, i) => (
                    <Cell key={i} fill={entry.color} />
                  ))}
                </Pie>
                <RTooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [formatNumber(v, 2), 'Stock']}
                />
                <Legend iconSize={8} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>
        </Grid>

        {/* ── Activity Heatmap ── */}
        <Grid item xs={12} md={8}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                  <Typography variant="h6" fontWeight={700}>Mapa de actividad</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Transacciones por día y hora
                  </Typography>
                </Box>
              </Box>
              <ActivityHeatmap
                heatmap={data?.activity_heatmap ?? []}
                loading={loading}
              />
            </CardContent>
          </Card>
        </Grid>

        {/* ── Operations Funnel ── */}
        <Grid item xs={12} md={4}>
          <ChartCard
            title="Funnel de operaciones"
            subtitle="Flujo del mes"
            loading={loading}
            height={240}
            isEmpty={funnelData.length === 0}
            delay={0.3}
          >
            <ResponsiveContainer width="100%" height="100%">
              <FunnelChart>
                <RTooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [formatCompactNumber(v), '']}
                />
                <Funnel dataKey="value" data={funnelData} isAnimationActive>
                  {funnelData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                  <LabelList
                    dataKey="name"
                    position="right"
                    fontSize={11}
                    fill={TOKENS.textSub}
                    fontWeight={600}
                  />
                </Funnel>
              </FunnelChart>
            </ResponsiveContainer>
          </ChartCard>
        </Grid>

        {/* ── AI Pricing ── */}
        {(data?.ai_pricing?.length ?? 0) > 0 && (
          <Grid item xs={12} md={6}>
            <Card>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                  <Typography variant="h6" fontWeight={700}>Precios sugeridos por IA</Typography>
                  <Chip label="AI" size="small" color="primary" sx={{ height: 18, fontSize: '0.6rem', fontWeight: 800 }} />
                </Box>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {data!.ai_pricing.map((p, i) => (
                    <motion.div
                      key={p.currency}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05 }}
                    >
                      <Box sx={{
                        display: 'flex', alignItems: 'center', gap: 2,
                        px: 2, py: 1.25, borderRadius: 2,
                        border: `1px solid ${TOKENS.border}`,
                        '&:hover': { bgcolor: alpha(TOKENS.blue, 0.025) },
                        transition: 'background-color 0.1s',
                      }}>
                        <Typography variant="body2" fontWeight={800} sx={{ width: 40, flexShrink: 0 }}>
                          {p.currency}
                        </Typography>
                        <Box sx={{ flex: 1, display: 'flex', gap: 2 }}>
                          <Typography variant="caption" color="text.secondary">
                            Compra:{' '}
                            <Box component="span" sx={{ color: TOKENS.green, fontWeight: 700 }}>
                              {p.suggested_buy?.toFixed(4)}
                            </Box>
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            Venta:{' '}
                            <Box component="span" sx={{ color: TOKENS.red, fontWeight: 700 }}>
                              {p.suggested_sell?.toFixed(4)}
                            </Box>
                          </Typography>
                        </Box>
                        <Chip
                          label={`${p.spread_pct?.toFixed(2)}%`}
                          size="small"
                          color={p.spread_pct > 0.5 ? 'success' : p.spread_pct > 0.3 ? 'warning' : 'error'}
                        />
                      </Box>
                    </motion.div>
                  ))}
                </Box>
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* ── Inventory Status ── */}
        {(data?.inventory?.length ?? 0) > 0 && (
          <Grid item xs={12} md={(data?.ai_pricing?.length ?? 0) > 0 ? 6 : 12}>
            <InventoryStatus inventory={data!.inventory} loading={loading} />
          </Grid>
        )}
      </Grid>
    </DashboardLayout>
  );
};

export default ExecutiveDashboard;
