import React, { useMemo, memo } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Skeleton,
  Alert, Button, Chip, Divider,
} from '@mui/material';
import {
  AttachMoney, AccountBalance, People, SwapHoriz,
  TrendingUp, HourglassEmpty, Receipt,
  ArrowUpward, ArrowDownward, Add,
} from '@mui/icons-material';
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area,
  PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { alpha } from '@mui/material/styles';
import { useNavigate } from 'react-router-dom';
import { TOKENS } from '../../styles/theme';
import { formatCurrency, formatNumber, formatCompactNumber } from '../../utils/formatters';
import { useOperativeDashboard } from '../../hooks/useOperativeDashboard';
import KPIBox from '../common/KPIBox';
import ChartCard from '../common/ChartCard';
import AlertBanner from '../common/AlertBanner';
import DashboardLayout from '../common/DashboardLayout';
import PredictionsChart from './PredictionsChart';
import DecisionPanel from './DecisionPanel';

// ── Constants ─────────────────────────────────────────────────────────────────
const FLAGS: Record<string, string> = {
  USD: '🇺🇸', EUR: '🇪🇺', CLP: '🇨🇱', PEN: '🇵🇪',
  BRL: '🇧🇷', ARS: '🇦🇷', GBP: '🇬🇧',
};
const MAIN_CURRENCIES = ['USD', 'EUR', 'CLP', 'PEN', 'BRL', 'ARS', 'GBP'];
const PIE_COLORS      = [TOKENS.blue, TOKENS.green, TOKENS.amber, TOKENS.red, '#8B5CF6', '#06B6D4'];

const TOOLTIP_STYLE = {
  borderRadius: 8,
  border: `1px solid ${TOKENS.border}`,
  boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
  fontSize: 12,
  fontWeight: 500,
  background: TOKENS.surface,
};

// ── Chart tooltip ─────────────────────────────────────────────────────────────
const ChartTooltip = ({ active, payload, label, isCurrency = true }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <Box sx={{
      bgcolor: TOKENS.surface, border: `1px solid ${TOKENS.border}`,
      borderRadius: 2, px: 2, py: 1.5,
      boxShadow: '0 4px 16px rgba(15,23,42,0.12)',
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
            {p.name}: {isCurrency ? formatCurrency(p.value) : formatNumber(p.value, 0)}
          </Typography>
        </Box>
      ))}
    </Box>
  );
};

// ── Rates Panel ───────────────────────────────────────────────────────────────
const RatesPanel = memo(({ rates, loading }: { rates: Record<string, any>; loading: boolean }) => {
  const entries = Object.entries(rates).filter(([c]) => MAIN_CURRENCIES.includes(c));

  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6" fontWeight={700}>Tasas de Cambio</Typography>
          <Chip
            label="EN VIVO"
            size="small"
            color="success"
            sx={{ height: 20, fontSize: '0.6rem', fontWeight: 800 }}
          />
        </Box>
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 76px 76px 58px', px: 0.5, mb: 1 }}>
          {['Divisa', 'Compra', 'Venta', 'Spread'].map(h => (
            <Typography
              key={h}
              variant="overline"
              color="text.secondary"
              textAlign={h === 'Divisa' ? 'left' : 'right'}
            >
              {h}
            </Typography>
          ))}
        </Box>
        <Divider />
        {loading
          ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={44} sx={{ my: 0.25 }} />)
          : entries.length === 0
            ? (
              <Box sx={{ py: 4, textAlign: 'center' }}>
                <Typography color="text.secondary" variant="body2">Sin tasas disponibles</Typography>
              </Box>
            )
            : entries.map(([code, rate]) => {
              const spreadPct = rate.buy > 0 ? ((rate.sell - rate.buy) / rate.buy * 100) : 0;
              return (
                <Box
                  key={code}
                  sx={{
                    display: 'grid', gridTemplateColumns: '1fr 76px 76px 58px',
                    alignItems: 'center', py: 0.875, px: 0.5,
                    borderBottom: `1px solid ${TOKENS.border}`,
                    '&:last-child': { borderBottom: 'none' },
                    '&:hover': { bgcolor: alpha(TOKENS.blue, 0.025), borderRadius: 1 },
                    transition: 'background-color 0.1s',
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography sx={{ fontSize: 16 }}>{FLAGS[code] ?? '🌐'}</Typography>
                    <Box>
                      <Typography variant="body2" fontWeight={700}>{code}</Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem' }}>
                        {rate.name ?? code}
                      </Typography>
                    </Box>
                  </Box>
                  <Typography
                    variant="body2"
                    fontWeight={700}
                    color={TOKENS.green}
                    textAlign="right"
                    sx={{ fontVariantNumeric: 'tabular-nums' }}
                  >
                    {rate.buy?.toFixed(4)}
                  </Typography>
                  <Typography
                    variant="body2"
                    fontWeight={700}
                    color={TOKENS.red}
                    textAlign="right"
                    sx={{ fontVariantNumeric: 'tabular-nums' }}
                  >
                    {rate.sell?.toFixed(4)}
                  </Typography>
                  <Typography
                    variant="caption"
                    textAlign="right"
                    sx={{ color: TOKENS.muted, fontVariantNumeric: 'tabular-nums' }}
                  >
                    {spreadPct.toFixed(2)}%
                  </Typography>
                </Box>
              );
            })
        }
      </CardContent>
    </Card>
  );
});
RatesPanel.displayName = 'RatesPanel';

// ── Activity Feed ─────────────────────────────────────────────────────────────
const ActivityFeed = memo(({ transactions, loading }: { transactions: any[]; loading: boolean }) => (
  <Card sx={{ height: '100%' }}>
    <CardContent>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6" fontWeight={700}>Actividad reciente</Typography>
        <Typography variant="caption" color="text.secondary">{transactions.length} ops.</Typography>
      </Box>
      {loading ? (
        Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} height={46} sx={{ mb: 0.5 }} />)
      ) : transactions.length === 0 ? (
        <Box sx={{ py: 4, textAlign: 'center' }}>
          <SwapHoriz sx={{ fontSize: 36, color: TOKENS.border, mb: 1 }} />
          <Typography variant="body2" color="text.secondary">Sin operaciones aún</Typography>
        </Box>
      ) : (
        <Box>
          {transactions.map((tx, i) => {
            const isBuy    = tx.transaction_type === 'BUY';
            const customer = typeof tx.customer === 'object'
              ? (tx.customer?.full_name ?? '—')
              : (tx.customer ?? '—');
            const currency = tx.currency_from?.code ?? tx.currency_from ?? '—';
            const amount   = tx.amount_to ?? tx.total_bob ?? 0;
            return (
              <Box
                key={i}
                sx={{
                  display: 'flex', alignItems: 'center', gap: 1.5, py: 0.875,
                  borderBottom: i < transactions.length - 1 ? `1px solid ${TOKENS.border}` : 'none',
                }}
              >
                <Box sx={{
                  width: 32, height: 32, borderRadius: '9px', flexShrink: 0,
                  bgcolor: isBuy ? alpha(TOKENS.green, 0.1) : alpha(TOKENS.blue, 0.1),
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  {isBuy
                    ? <ArrowDownward sx={{ fontSize: 15, color: TOKENS.green }} />
                    : <ArrowUpward   sx={{ fontSize: 15, color: TOKENS.blue }} />}
                </Box>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography variant="body2" fontWeight={600} noWrap>{customer}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {currency} · {isBuy ? 'Compra' : 'Venta'}
                  </Typography>
                </Box>
                <Typography
                  variant="body2"
                  fontWeight={700}
                  sx={{ fontVariantNumeric: 'tabular-nums', color: isBuy ? TOKENS.green : TOKENS.blue, flexShrink: 0 }}
                >
                  {formatCurrency(amount)}
                </Typography>
              </Box>
            );
          })}
        </Box>
      )}
    </CardContent>
  </Card>
));
ActivityFeed.displayName = 'ActivityFeed';

// ── Hourly bar chart ──────────────────────────────────────────────────────────
const HourlyChart = memo(({ data, loading }: { data: { hour: string; count: number }[]; loading: boolean }) => {
  const max    = Math.max(...data.map(d => d.count), 1);
  const hasData = data.some(d => d.count > 0);

  return (
    <ChartCard
      title="Actividad del día"
      subtitle={hasData ? `Pico: ${data.reduce((a, b) => b.count > a.count ? b : a, { hour: '—', count: 0 }).hour}h` : undefined}
      loading={loading}
      height={180}
      isEmpty={!hasData}
      emptyMessage="Sin operaciones hoy"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 0, right: 4, left: -24, bottom: 0 }} barSize={10}>
          <CartesianGrid vertical={false} stroke={TOKENS.border} />
          <XAxis dataKey="hour" tick={{ fontSize: 9, fill: TOKENS.muted }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fontSize: 9, fill: TOKENS.muted }} axisLine={false} tickLine={false} allowDecimals={false} />
          <RTooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: any) => [v, 'Transacciones']}
            cursor={{ fill: alpha(TOKENS.blue, 0.06) }}
          />
          <Bar dataKey="count" radius={[5, 5, 0, 0]}>
            {data.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.count === max ? TOKENS.blue : entry.count > 0 ? alpha(TOKENS.blue, 0.45) : TOKENS.border}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
});
HourlyChart.displayName = 'HourlyChart';

// ── Dashboard ─────────────────────────────────────────────────────────────────
const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { stats, charts, rates, loading, refreshing, error, refresh } = useOperativeDashboard();

  const safeNum = (v: any) => (v == null || isNaN(Number(v)) ? 0 : Number(v));

  // ── KPI Row 1 ─────────────────────────────────────────────────────────────
  const kpiRow1 = useMemo(() => [
    {
      title:    'Ingresos del día',
      value:    formatCurrency(safeNum(stats?.today_profit_bob)),
      change:   safeNum(stats?.volume_change_pct),
      icon:     <AttachMoney />,
      accent:   TOKENS.green,
    },
    {
      title:    'Ingresos del mes',
      value:    stats?.month_revenue != null ? formatCurrency(stats.month_revenue) : '—',
      icon:     <Receipt />,
      accent:   TOKENS.blue,
    },
    {
      title:    'Transacciones',
      value:    formatNumber(safeNum(stats?.today_transactions), 0),
      subtitle: 'operaciones hoy',
      change:   safeNum(stats?.count_change_pct),
      icon:     <SwapHoriz />,
      accent:   TOKENS.blue,
    },
    {
      title:    'Ticket promedio',
      value:    stats?.avg_ticket != null
        ? formatCurrency(stats.avg_ticket)
        : stats?.today_transactions
          ? formatCurrency(safeNum(stats.today_volume_bob) / Math.max(safeNum(stats.today_transactions), 1))
          : '—',
      icon:     <AttachMoney />,
      accent:   TOKENS.amber,
    },
    {
      title:    'Spread promedio',
      value:    stats?.avg_spread != null ? `${safeNum(stats.avg_spread).toFixed(2)}%` : '—',
      icon:     <TrendingUp />,
      accent:   TOKENS.navyLight,
    },
    {
      title:    'Clientes atendidos',
      value:    formatNumber(safeNum(stats?.unique_customers), 0),
      subtitle: 'clientes únicos hoy',
      icon:     <People />,
      accent:   TOKENS.amber,
    },
    {
      title:    'Pendientes',
      value:    stats?.pending_transactions != null ? formatNumber(stats.pending_transactions, 0) : '—',
      subtitle: 'por procesar',
      icon:     <HourglassEmpty />,
      accent:   TOKENS.red,
    },
  ], [stats]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── KPI Row 2: Financieros ────────────────────────────────────────────────
  const kpiRow2 = useMemo(() => [
    {
      title:  'Flujo de caja diario',
      value:  stats?.daily_cash_flow != null
        ? formatCurrency(stats.daily_cash_flow)
        : formatCurrency(safeNum(stats?.today_volume_bob)),
      icon:   <AccountBalance />,
      accent: TOKENS.green,
      size:   'lg' as const,
    },
    {
      title:  'Capital actual',
      value:  stats?.current_capital != null ? formatCurrency(stats.current_capital) : '—',
      icon:   <AccountBalance />,
      accent: TOKENS.blue,
      size:   'lg' as const,
    },
    {
      title:  'Variación diaria',
      value:  (() => {
        const pct = safeNum(stats?.daily_variation_pct ?? stats?.volume_change_pct);
        return pct !== 0 ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : '—';
      })(),
      icon:   safeNum(stats?.daily_variation_pct ?? stats?.volume_change_pct) >= 0
        ? <TrendingUp />
        : <ArrowDownward />,
      accent: safeNum(stats?.daily_variation_pct ?? stats?.volume_change_pct) >= 0
        ? TOKENS.green
        : TOKENS.red,
      size:   'lg' as const,
    },
  ], [stats]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Chart data ────────────────────────────────────────────────────────────
  const revenue30d         = charts.revenue_30d         ?? [];
  const volumeByCurrency   = charts.volume_by_currency  ?? [];
  const capitalTimeline    = charts.capital_timeline    ?? [];
  const incomeDistribution = charts.income_distribution ?? [];
  const alerts             = useMemo(
    () => (charts.alerts ?? []).map((a, i) => ({ ...a, id: `alert-${i}` })),
    [charts.alerts],
  );

  if (error && !loading) {
    return (
      <DashboardLayout title="Dashboard Operativo" onRefresh={refresh} refreshing={refreshing}>
        <Alert
          severity="error"
          action={<Button size="small" color="inherit" onClick={refresh}>Reintentar</Button>}
        >
          {error}
        </Alert>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout
      title="Dashboard Operativo"
      badge="TIEMPO REAL"
      subtitle={new Date().toLocaleDateString('es-BO', {
        weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
      })}
      onRefresh={refresh}
      refreshing={refreshing}
    >
      {alerts.length > 0 && <AlertBanner alerts={alerts} />}

      {!loading && safeNum(stats?.today_transactions) === 0 && (
        <Alert
          severity="info"
          sx={{ mb: 2.5 }}
          action={
            <Button size="small" color="inherit" onClick={() => navigate('/transactions')}>
              Nueva
            </Button>
          }
        >
          Sin operaciones hoy — registra la primera transacción del día.
        </Alert>
      )}

      <Grid container spacing={2.5}>
        {/* ── KPI Row 1 ── */}
        {kpiRow1.map((kpi, i) => (
          <Grid item key={kpi.title} xs={6} sm={4} md={3}>
            <KPIBox {...kpi} loading={loading} delay={i * 0.04} />
          </Grid>
        ))}

        {/* ── KPI Row 2: Financieros ── */}
        {kpiRow2.map((kpi, i) => (
          <Grid item key={kpi.title} xs={12} sm={4}>
            <KPIBox {...kpi} loading={loading} delay={0.3 + i * 0.05} />
          </Grid>
        ))}

        {/* ── Revenue 30d ── */}
        <Grid item xs={12} md={8}>
          <ChartCard
            title="Ingresos últimos 30 días"
            subtitle="Utilidad neta diaria (BOB)"
            loading={loading}
            height={220}
            isEmpty={revenue30d.length === 0}
            delay={0.15}
          >
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={revenue30d} margin={{ top: 5, right: 8, left: -16, bottom: 0 }}>
                <defs>
                  <linearGradient id="rev30-grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={TOKENS.green} stopOpacity={0.2} />
                    <stop offset="95%" stopColor={TOKENS.green} stopOpacity={0}   />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke={TOKENS.border} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: TOKENS.muted }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={d => (typeof d === 'string' ? d.slice(5) : d)}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: TOKENS.muted }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={v => formatCompactNumber(v)}
                />
                <RTooltip content={<ChartTooltip />} />
                <Area
                  type="monotone"
                  dataKey="revenue"
                  name="Ingresos"
                  stroke={TOKENS.green}
                  strokeWidth={2}
                  fill="url(#rev30-grad)"
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>
        </Grid>

        {/* ── Income Distribution Pie ── */}
        <Grid item xs={12} md={4}>
          <ChartCard
            title="Distribución de ingresos"
            subtitle="Por divisa"
            loading={loading}
            height={220}
            isEmpty={incomeDistribution.length === 0}
            delay={0.2}
          >
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={incomeDistribution}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={78}
                  innerRadius={36}
                  paddingAngle={2}
                >
                  {incomeDistribution.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <RTooltip
                  formatter={(v: number) => [formatCurrency(v), 'Ingresos']}
                  contentStyle={TOOLTIP_STYLE}
                />
                <Legend
                  iconSize={8}
                  iconType="circle"
                  wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>
        </Grid>

        {/* ── Volume by Currency ── */}
        <Grid item xs={12} md={7}>
          <ChartCard
            title="Volumen por divisa"
            subtitle="Total del mes (BOB)"
            loading={loading}
            height={220}
            isEmpty={volumeByCurrency.length === 0}
            delay={0.25}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={volumeByCurrency} margin={{ top: 5, right: 8, left: -16, bottom: 0 }} barSize={24}>
                <CartesianGrid vertical={false} stroke={TOKENS.border} />
                <XAxis
                  dataKey="currency"
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
                <RTooltip content={<ChartTooltip />} />
                <Legend iconSize={8} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="volume" name="Volumen"   fill={TOKENS.blue}  radius={[5, 5, 0, 0]} />
                <Bar dataKey="profit" name="Utilidad" fill={TOKENS.green} radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </Grid>

        {/* ── Capital Timeline ── */}
        <Grid item xs={12} md={5}>
          <ChartCard
            title="Capital acumulado"
            subtitle="Evolución mensual"
            loading={loading}
            height={220}
            isEmpty={capitalTimeline.length === 0}
            delay={0.3}
          >
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={capitalTimeline} margin={{ top: 5, right: 8, left: -16, bottom: 0 }}>
                <defs>
                  <linearGradient id="cap-grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={TOKENS.blue} stopOpacity={0.18} />
                    <stop offset="95%" stopColor={TOKENS.blue} stopOpacity={0}    />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke={TOKENS.border} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: TOKENS.muted }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={d => (typeof d === 'string' ? d.slice(5) : d)}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: TOKENS.muted }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={v => formatCompactNumber(v)}
                />
                <RTooltip content={<ChartTooltip />} />
                <Area
                  type="monotone"
                  dataKey="capital"
                  name="Capital"
                  stroke={TOKENS.blue}
                  strokeWidth={2}
                  fill="url(#cap-grad)"
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>
        </Grid>

        {/* ── Rates ── */}
        <Grid item xs={12} md={5}>
          <RatesPanel rates={rates} loading={loading} />
        </Grid>

        {/* ── Hourly Activity ── */}
        <Grid item xs={12} md={4}>
          <HourlyChart data={stats?.transactions_by_hour ?? []} loading={loading} />
        </Grid>

        {/* ── Activity Feed ── */}
        <Grid item xs={12} md={3}>
          <ActivityFeed transactions={stats?.recent_transactions ?? []} loading={loading} />
        </Grid>

        {/* ── Quick Actions ── */}
        <Grid item xs={12} md={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" fontWeight={700} mb={2}>Acciones rápidas</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
                {[
                  { label: 'Nueva transacción', icon: <Add />,        path: '/transactions', primary: true },
                  { label: 'Ver inventario',    icon: <AccountBalance />, path: '/inventory' },
                  { label: 'Clientes',          icon: <People />,     path: '/customers' },
                  { label: 'Reportes',          icon: <Receipt />,    path: '/reports' },
                ].map(a => (
                  <Button
                    key={a.label}
                    variant={a.primary ? 'contained' : 'outlined'}
                    startIcon={a.icon}
                    onClick={() => navigate(a.path)}
                    fullWidth
                    sx={{
                      justifyContent: 'flex-start',
                      fontWeight: 600,
                      fontSize: '0.8125rem',
                      ...(!a.primary ? {
                        borderColor: TOKENS.border,
                        color: TOKENS.text,
                        '&:hover': { borderColor: TOKENS.blue, color: TOKENS.blue, bgcolor: alpha(TOKENS.blue, 0.04) },
                      } : {}),
                    }}
                  >
                    {a.label}
                  </Button>
                ))}
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* ── Predictions ── */}
        <Grid item xs={12} md={9}>
          <PredictionsChart />
        </Grid>

        {/* ── AI Decisions ── */}
        <Grid item xs={12}>
          <DecisionPanel />
        </Grid>
      </Grid>
    </DashboardLayout>
  );
};

export default Dashboard;
