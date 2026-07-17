// src/components/analytics/Analytics.tsx
/**
 * Dashboard de Analytics Financiero — Kapitalya
 *
 * Paneles:
 *   0) P&L — Ganancia/Pérdida real con serie temporal y top divisas
 *   1) Exposición — Riesgo de mercado por divisa (pie chart + alertas)
 *   2) Spread — Spreads actuales y series históricas
 *   3) Decisiones — Motor de recomendaciones BUY/SELL/HOLD
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Tabs, Tab, Chip,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Paper, Alert, Skeleton, CircularProgress, Divider, LinearProgress,
  Tooltip, IconButton,
} from '@mui/material';
import {
  TrendingUp, TrendingDown, TrendingFlat, Refresh,
  AccountBalance, CurrencyExchange, ShowChart, Psychology,
  Warning, CheckCircle, Error as ErrorIcon,
} from '@mui/icons-material';
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatCurrency, formatCompactNumber } from '../../utils/formatters';
import { useWebSocket } from '../../contexts/WebSocketContext';

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (v: any, d = 2) => {
  const n = parseFloat(String(v || 0));
  return isNaN(n) ? '0.00'
    : new Intl.NumberFormat('es-BO', {
        minimumFractionDigits: d, maximumFractionDigits: d,
      }).format(n);
};
const fmtBOB  = (v: any) => `Bs. ${fmt(v)}`;
const fmtPct  = (v: any) => `${fmt(v, 4)}%`;
const fmtSign = (v: any) => {
  const n = parseFloat(String(v || 0));
  return `${n >= 0 ? '+' : ''}${fmt(Math.abs(n))}`;
};

const CHART_COLORS = ['#1976d2', '#2e7d32', '#e65100', '#7b1fa2', '#00838f', '#c62828'];

const alertColor = (level: string) =>
  level === 'CRITICAL' ? 'error' : level === 'WARNING' ? 'warning' : 'success';

const decisionColor = (accion: string) =>
  accion === 'COMPRAR' ? '#2e7d32'
  : accion === 'VENDER' ? '#b71c1c'
  : '#e65100';

const decisionIcon = (accion: string) =>
  accion === 'COMPRAR' ? <TrendingUp />
  : accion === 'VENDER' ? <TrendingDown />
  : <TrendingFlat />;

// ── Types ─────────────────────────────────────────────────────────────────────

interface PnLSerie {
  fecha: string;
  ingreso_ventas_bob: string;
  ganancia_bruta_bob: string;
  ganancia_neta_bob: string;
  gastos_operativos_bob: string;
  num_ventas: number;
}

interface PnLData {
  resumen: {
    ganancia_neta_bob: string;
    ganancia_bruta_bob: string;
    ingreso_ventas_bob: string;
    margen_neto_pct: string;
    total_ventas: number;
  };
  series: PnLSerie[];
  top_divisas: { currency_code: string; ganancia_bob: string; ops: number }[];
}

interface DivisaExposicion {
  currency_code: string;
  currency_name: string;
  stock_units: string;
  exposure_bob: string;
  pct_of_capital: string;
  unrealized_pnl_bob: string;
  wac_unit: string;
  sell_rate_unit: string;
  alert_level: 'OK' | 'WARNING' | 'CRITICAL';
}

interface ExposureData {
  divisas: DivisaExposicion[];
  total_exposure_bob: string;
  alertas: string[];
  calculado_en: string;
}

interface SpreadRow {
  currency_code: string;
  market_type: string;
  buy_rate: string;
  sell_rate: string;
  spread_bob: string;
  spread_pct: string;
  prima_oficial_pct: string;
  spread_prom_30d: string;
  spread_pct_prom_30d: string;
  alerta_spread_bajo: boolean;
}

interface Recomendacion {
  currency_code: string;
  accion: 'COMPRAR' | 'VENDER' | 'MANTENER';
  score: number;
  razon: string;
  señales: string[];
  alertas: string[];
  stock_actual: string;
  wac: string;
}

// ── Sub-components ────────────────────────────────────────────────────────────

const KpiCard = ({
  label, value, sub, color, loading,
}: {
  label: string; value: string; sub?: string; color?: string; loading: boolean;
}) => (
  <Card sx={{ borderLeft: `4px solid ${color ?? '#1976d2'}` }}>
    <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
      {loading ? <Skeleton height={60} /> : (
        <>
          <Typography variant="caption" color="text.secondary" fontWeight={600}>
            {label.toUpperCase()}
          </Typography>
          <Typography variant="h5" fontWeight={800} color={color ?? 'primary.main'}>
            {value}
          </Typography>
          {sub && (
            <Typography variant="caption" color="text.secondary">{sub}</Typography>
          )}
        </>
      )}
    </CardContent>
  </Card>
);

// ── Tab 0: P&L ────────────────────────────────────────────────────────────────

const PnLPanel: React.FC<{ loading: boolean; data: PnLData | null }> = ({ loading, data }) => {
  if (loading) return <Skeleton variant="rectangular" height={400} />;
  if (!data) return <Alert severity="info">Sin datos de P&L. Registre transacciones primero.</Alert>;

  const { resumen, series, top_divisas } = data;
  const netaColor = parseFloat(resumen?.ganancia_neta_bob || '0') >= 0 ? '#2e7d32' : '#b71c1c';

  const chartData = series.map(s => ({
    fecha:         s.fecha?.slice(5),   // MM-DD
    ingreso:       parseFloat(s.ingreso_ventas_bob),
    bruta:         parseFloat(s.ganancia_bruta_bob),
    neta:          parseFloat(s.ganancia_neta_bob),
    gastos:        parseFloat(s.gastos_operativos_bob),
    ops:           s.num_ventas,
  }));

  return (
    <Box>
      <Grid container spacing={2} mb={3}>
        <Grid item xs={6} md={3}>
          <KpiCard label="Ganancia Neta" value={fmtBOB(resumen?.ganancia_neta_bob)}
            color={netaColor} loading={false} />
        </Grid>
        <Grid item xs={6} md={3}>
          <KpiCard label="Ganancia Bruta" value={fmtBOB(resumen?.ganancia_bruta_bob)}
            color="#1976d2" loading={false} />
        </Grid>
        <Grid item xs={6} md={3}>
          <KpiCard label="Ingresos Ventas" value={fmtBOB(resumen?.ingreso_ventas_bob)}
            color="#1565c0" loading={false} />
        </Grid>
        <Grid item xs={6} md={3}>
          <KpiCard label="Margen Neto" value={fmtPct(resumen?.margen_neto_pct)}
            sub={`${resumen?.total_ventas ?? 0} ventas`} color="#7b1fa2" loading={false} />
        </Grid>
      </Grid>

      {/* Serie temporal */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" fontWeight={700} mb={2}>P&L Diario</Typography>
          {chartData.length === 0 ? (
            <Alert severity="info">Sin datos suficientes para graficar el P&L diario.</Alert>
          ) : (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="fecha" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `Bs. ${formatCompactNumber(v)}`} />
              <RTooltip formatter={(v: any, name: string) => [fmtBOB(v), name]} />
              <Legend />
              <ReferenceLine y={0} stroke="#ccc" strokeDasharray="3 3" />
              <Line type="monotone" dataKey="neta"   name="Neta"   stroke="#2e7d32" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="bruta"  name="Bruta"  stroke="#1976d2" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="gastos" name="Gastos" stroke="#e53935" strokeWidth={1.5} strokeDasharray="4 4" dot={false} />
            </LineChart>
          </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Top divisas */}
      {top_divisas.length > 0 && (
        <Card>
          <CardContent>
            <Typography variant="h6" fontWeight={700} mb={2}>Top Divisas por Ganancia</Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ bgcolor: 'grey.100' }}>
                    <TableCell><strong>Divisa</strong></TableCell>
                    <TableCell align="right"><strong>Ganancia BOB</strong></TableCell>
                    <TableCell align="right"><strong>Operaciones</strong></TableCell>
                    <TableCell><strong>Rendimiento</strong></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {top_divisas.map((d, i) => {
                    const ganancia = parseFloat(d.ganancia_bob);
                    const maxGanancia = parseFloat(top_divisas[0]?.ganancia_bob || '1');
                    return (
                      <TableRow key={d.currency_code} hover>
                        <TableCell>
                          <Box display="flex" alignItems="center" gap={1}>
                            <Box sx={{ width: 10, height: 10, borderRadius: '50%',
                              bgcolor: CHART_COLORS[i % CHART_COLORS.length] }} />
                            <Typography fontWeight={700}>{d.currency_code}</Typography>
                          </Box>
                        </TableCell>
                        <TableCell align="right">
                          <Typography fontWeight={700}
                            color={ganancia >= 0 ? 'success.main' : 'error.main'}>
                            {fmtSign(ganancia)} Bs.
                          </Typography>
                        </TableCell>
                        <TableCell align="right">{d.ops}</TableCell>
                        <TableCell sx={{ width: 140 }}>
                          <LinearProgress
                            variant="determinate"
                            value={maxGanancia > 0 ? Math.max(0, (ganancia / maxGanancia) * 100) : 0}
                            sx={{ height: 8, borderRadius: 4,
                              bgcolor: 'grey.200',
                              '& .MuiLinearProgress-bar': {
                                bgcolor: CHART_COLORS[i % CHART_COLORS.length],
                              }
                            }}
                          />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>
      )}
    </Box>
  );
};

// ── Tab 1: Exposición ─────────────────────────────────────────────────────────

const ExposurePanel: React.FC<{ loading: boolean; data: ExposureData | null }> = ({ loading, data }) => {
  if (loading) return <Skeleton variant="rectangular" height={400} />;
  if (!data) return <Alert severity="info">Sin datos de exposición.</Alert>;

  const pieData = data.divisas.map((d, i) => ({
    name:  d.currency_code,
    value: parseFloat(d.exposure_bob),
    color: CHART_COLORS[i % CHART_COLORS.length],
  }));

  return (
    <Box>
      {data.alertas.map((a, i) => (
        <Alert key={`exposure-alert-${i}-${a.slice(0, 20)}`} severity="warning" sx={{ mb: 1 }}>{a}</Alert>
      ))}

      <Grid container spacing={3}>
        {/* Pie chart */}
        <Grid item xs={12} md={5}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" fontWeight={700} mb={1}>Distribución de Exposición</Typography>
              <Typography variant="h4" fontWeight={800} color="primary">
                {fmtBOB(data.total_exposure_bob)}
              </Typography>
              <Typography variant="caption" color="text.secondary">Total en riesgo de mercado</Typography>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" outerRadius={90}
                    dataKey="value" nameKey="name" label={({ name, percent }) =>
                      `${name} ${(percent * 100).toFixed(1)}%`
                    }>
                    {pieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                  </Pie>
                  <RTooltip formatter={(v: any) => [fmtBOB(v), 'Exposición']} />
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </Grid>

        {/* Tabla */}
        <Grid item xs={12} md={7}>
          <Card>
            <CardContent>
              <Typography variant="h6" fontWeight={700} mb={2}>Detalle por Divisa</Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow sx={{ bgcolor: 'grey.100' }}>
                      <TableCell><strong>Divisa</strong></TableCell>
                      <TableCell align="right"><strong>Stock</strong></TableCell>
                      <TableCell align="right"><strong>Exposición BOB</strong></TableCell>
                      <TableCell align="right"><strong>% Capital</strong></TableCell>
                      <TableCell align="right"><strong>P&L Latente</strong></TableCell>
                      <TableCell><strong>Alerta</strong></TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.divisas.map(d => {
                      const pnl = parseFloat(d.unrealized_pnl_bob);
                      return (
                        <TableRow key={d.currency_code} hover>
                          <TableCell>
                            <Typography fontWeight={700}>{d.currency_code}</Typography>
                            <Typography variant="caption" color="text.secondary">
                              WAC: {fmt(d.wac_unit, 4)}
                            </Typography>
                          </TableCell>
                          <TableCell align="right">{fmt(d.stock_units, 2)}</TableCell>
                          <TableCell align="right">
                            <Typography fontWeight={600}>{fmtBOB(d.exposure_bob)}</Typography>
                          </TableCell>
                          <TableCell align="right">
                            <Chip label={`${fmt(d.pct_of_capital, 2)}%`} size="small"
                              color={alertColor(d.alert_level) as any} />
                          </TableCell>
                          <TableCell align="right">
                            <Typography fontWeight={700}
                              color={pnl >= 0 ? 'success.main' : 'error.main'}>
                              {pnl >= 0 ? '+' : ''}{fmt(pnl)} Bs.
                            </Typography>
                          </TableCell>
                          <TableCell>
                            {d.alert_level === 'OK'
                              ? <CheckCircle fontSize="small" color="success" />
                              : d.alert_level === 'WARNING'
                              ? <Warning fontSize="small" color="warning" />
                              : <ErrorIcon fontSize="small" color="error" />
                            }
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
};

// ── Tab 2: Spread ─────────────────────────────────────────────────────────────

const SpreadPanel: React.FC<{ loading: boolean; data: SpreadRow[] }> = ({ loading, data }) => {
  if (loading) return <Skeleton variant="rectangular" height={300} />;
  if (!data.length) return <Alert severity="info">Sin datos de spread activos.</Alert>;

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" fontWeight={700} mb={2}>Spreads Actuales por Divisa</Typography>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: 'grey.100' }}>
                <TableCell><strong>Divisa</strong></TableCell>
                <TableCell><strong>Mercado</strong></TableCell>
                <TableCell align="right"><strong>Compra</strong></TableCell>
                <TableCell align="right"><strong>Venta</strong></TableCell>
                <TableCell align="right"><strong>Spread</strong></TableCell>
                <TableCell align="right"><strong>Spread %</strong></TableCell>
                <TableCell align="right"><strong>Prom. 30d</strong></TableCell>
                <TableCell align="right"><strong>Prima Oficial</strong></TableCell>
                <TableCell><strong>Estado</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.map((s, i) => (
                <TableRow key={`${s.currency_code}_${s.market_type}_${i}`} hover>
                  <TableCell>
                    <Typography fontWeight={700}>{s.currency_code}</Typography>
                  </TableCell>
                  <TableCell>
                    <Chip label={s.market_type.replace(/_/g, ' ')} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell align="right">{fmt(s.buy_rate, 4)}</TableCell>
                  <TableCell align="right">{fmt(s.sell_rate, 4)}</TableCell>
                  <TableCell align="right">
                    <Typography fontWeight={600} color="primary">
                      {fmt(s.spread_bob, 4)}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography fontWeight={700}
                      color={s.alerta_spread_bajo ? 'error.main' : 'success.main'}>
                      {fmtPct(s.spread_pct)}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">{fmtPct(s.spread_pct_prom_30d)}</TableCell>
                  <TableCell align="right">{fmtPct(s.prima_oficial_pct)}</TableCell>
                  <TableCell>
                    {s.alerta_spread_bajo
                      ? <Chip label="Spread bajo" size="small" color="error" />
                      : <Chip label="OK" size="small" color="success" variant="outlined" />
                    }
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent>
    </Card>
  );
};

// ── Tab 3: Decisiones ─────────────────────────────────────────────────────────

const DecisionPanel: React.FC<{
  loading: boolean; data: Recomendacion[];
}> = ({ loading, data }) => {
  if (loading) return <Skeleton variant="rectangular" height={300} />;
  if (!data.length) return <Alert severity="info">Sin posiciones activas para analizar.</Alert>;

  return (
    <Grid container spacing={2}>
      {data.map(r => (
        <Grid item xs={12} md={6} lg={4} key={r.currency_code}>
          <Card sx={{ borderTop: `4px solid ${decisionColor(r.accion)}` }}>
            <CardContent>
              <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
                <Box display="flex" alignItems="center" gap={1}>
                  <Box sx={{ color: decisionColor(r.accion) }}>{decisionIcon(r.accion)}</Box>
                  <Typography variant="h5" fontWeight={800}>{r.currency_code}</Typography>
                </Box>
                <Chip
                  label={r.accion}
                  sx={{ bgcolor: decisionColor(r.accion), color: 'white', fontWeight: 700 }}
                />
              </Box>

              {/* Score bar */}
              <Box mb={1.5}>
                <Box display="flex" justifyContent="space-between" mb={0.5}>
                  <Typography variant="caption" color="text.secondary">
                    Score: {r.score}/100
                  </Typography>
                  <Typography variant="caption" fontWeight={600}>
                    {r.accion === 'COMPRAR' ? '🟢 Alcista' : r.accion === 'VENDER' ? '🔴 Bajista' : '🟡 Neutro'}
                  </Typography>
                </Box>
                <LinearProgress
                  variant="determinate"
                  value={r.score}
                  sx={{
                    height: 10, borderRadius: 5,
                    bgcolor: 'grey.200',
                    '& .MuiLinearProgress-bar': { bgcolor: decisionColor(r.accion) },
                  }}
                />
              </Box>

              <Typography variant="body2" color="text.secondary" mb={1.5}>
                {r.razon}
              </Typography>

              <Box display="flex" justifyContent="space-between" mb={1}>
                <Typography variant="caption" color="text.secondary">
                  Stock: {fmt(r.stock_actual, 2)}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  WAC: {fmt(r.wac, 4)}
                </Typography>
              </Box>

              {r.alertas.length > 0 && (
                <Box mb={1}>
                  {r.alertas.map((a, i) => (
                    <Alert key={`${r.currency_code}-alert-${i}`} severity="warning" sx={{ py: 0.3, mb: 0.5, fontSize: 11 }}>
                      {a}
                    </Alert>
                  ))}
                </Box>
              )}

              {r.señales.length > 0 && (
                <Box>
                  <Typography variant="caption" color="text.secondary" fontWeight={600}>
                    SEÑALES
                  </Typography>
                  {r.señales.map((s, i) => (
                    <Typography key={`${r.currency_code}-signal-${i}`} variant="caption" display="block" color="text.secondary"
                      sx={{ pl: 1, borderLeft: '2px solid #e0e0e0', ml: 0.5, mb: 0.3 }}>
                      • {s}
                    </Typography>
                  ))}
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      ))}
    </Grid>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

// ── Anomalies panel ────────────────────────────────────────────────────────────
interface Anomaly {
  type: string; source: string; severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  title: string; description: string; value: string; threshold: string;
  deviation_pct: string; detected_at: string; recommendation: string;
}
interface AnomaliesData {
  anomalies: Anomaly[];
  summary: { total: number; critical: number; high: number; medium: number; low: number };
  last_checked: string;
}

const SEV_COLOR: Record<string, any> = { CRITICAL: 'error', HIGH: 'warning', MEDIUM: 'info', LOW: 'default' };
const SEV_LABEL: Record<string, string> = { CRITICAL: 'Crítico', HIGH: 'Alto', MEDIUM: 'Medio', LOW: 'Bajo' };

const AnomaliesPanel: React.FC<{ loading: boolean; data: AnomaliesData | null }> = ({ loading, data }) => {
  if (loading) return <Skeleton variant="rounded" height={280} />;
  if (!data || data.anomalies.length === 0)
    return (
      <Alert severity="success" icon={<CheckCircle />}>
        No se detectaron anomalías financieras en spreads, tasas, inventario ni capital.
      </Alert>
    );
  return (
    <Box>
      <Grid container spacing={2} mb={2}>
        {[
          { k: 'total', label: 'Total', color: 'default' },
          { k: 'critical', label: 'Críticas', color: 'error' },
          { k: 'high', label: 'Altas', color: 'warning' },
          { k: 'medium', label: 'Medias', color: 'info' },
          { k: 'low', label: 'Bajas', color: 'default' },
        ].map(s => (
          <Grid item xs={6} sm={2.4} key={s.k}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1.5 }}>
                <Typography variant="h5" fontWeight={800} color={`${s.color}.main` as any}>
                  {(data.summary as any)[s.k] ?? 0}
                </Typography>
                <Typography variant="caption" color="text.secondary">{s.label}</Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
      <Grid container spacing={2}>
        {data.anomalies.map((a, i) => (
          <Grid item xs={12} md={6} key={i}>
            <Card variant="outlined" sx={{ borderLeft: 4, borderLeftColor: `${SEV_COLOR[a.severity]}.main` }}>
              <CardContent>
                <Box display="flex" alignItems="center" justifyContent="space-between" mb={0.5} gap={1}>
                  <Box display="flex" alignItems="center" gap={1}>
                    <Warning color={SEV_COLOR[a.severity]} fontSize="small" />
                    <Typography variant="subtitle2" fontWeight={700}>{a.title}</Typography>
                  </Box>
                  <Chip size="small" color={SEV_COLOR[a.severity]} label={SEV_LABEL[a.severity] ?? a.severity} />
                </Box>
                <Typography variant="body2" color="text.secondary" mb={1}>{a.description}</Typography>
                <Box display="flex" gap={2} flexWrap="wrap" mb={1}>
                  <Chip size="small" variant="outlined" label={`Valor: ${a.value}`} />
                  <Chip size="small" variant="outlined" label={`Umbral: ${a.threshold}`} />
                  {a.deviation_pct && <Chip size="small" variant="outlined" label={`Desvío: ${a.deviation_pct}%`} />}
                  <Chip size="small" label={a.source} />
                </Box>
                {a.recommendation && (
                  <Typography variant="caption" color="primary" sx={{ display: 'block' }}>
                    → {a.recommendation}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
};

// ── Trends panel ───────────────────────────────────────────────────────────────
interface TrendsData {
  period: { desde: string; hasta: string; granularity: string };
  series: {
    pnl?: { fecha: string; ganancia_neta_bob: string; ganancia_bruta_bob: string }[];
    volume?: { fecha: string; volumen_bob: string; num_transacciones: number }[];
    transactions?: { fecha: string; buy_count: number; sell_count: number }[];
  };
  summary: { trend_direction?: string; growth_pct_mom?: string; best_day?: string; worst_day?: string };
}

const TrendsPanel: React.FC<{ loading: boolean; data: TrendsData | null }> = ({ loading, data }) => {
  if (loading) return <Skeleton variant="rounded" height={320} />;
  if (!data || !data.series?.pnl?.length)
    return <Alert severity="info">Sin datos de tendencia para el período seleccionado.</Alert>;

  const pnlSeries = (data.series.pnl ?? []).map(r => ({
    fecha: r.fecha,
    neta:  parseFloat(r.ganancia_neta_bob || '0'),
    bruta: parseFloat(r.ganancia_bruta_bob || '0'),
  }));
  const txSeries = (data.series.transactions ?? []).map(r => ({
    fecha: r.fecha, compras: r.buy_count, ventas: r.sell_count,
  }));
  const dir = data.summary?.trend_direction;

  return (
    <Box>
      <Grid container spacing={2} mb={2}>
        <Grid item xs={12} sm={4}>
          <Card variant="outlined"><CardContent sx={{ py: 1.5 }}>
            <Typography variant="caption" color="text.secondary">Tendencia</Typography>
            <Box display="flex" alignItems="center" gap={1}>
              {dir === 'up' ? <TrendingUp color="success" /> : dir === 'down' ? <TrendingDown color="error" /> : <TrendingFlat color="warning" />}
              <Typography variant="h6" fontWeight={700}>
                {dir === 'up' ? 'Al alza' : dir === 'down' ? 'A la baja' : 'Estable'}
              </Typography>
            </Box>
          </CardContent></Card>
        </Grid>
        <Grid item xs={12} sm={4}>
          <Card variant="outlined"><CardContent sx={{ py: 1.5 }}>
            <Typography variant="caption" color="text.secondary">Crecimiento MoM</Typography>
            <Typography variant="h6" fontWeight={700}>{fmtSign(data.summary?.growth_pct_mom)}%</Typography>
          </CardContent></Card>
        </Grid>
        <Grid item xs={12} sm={4}>
          <Card variant="outlined"><CardContent sx={{ py: 1.5 }}>
            <Typography variant="caption" color="text.secondary">Mejor / peor día</Typography>
            <Typography variant="body2" fontWeight={700}>{data.summary?.best_day ?? '—'} / {data.summary?.worst_day ?? '—'}</Typography>
          </CardContent></Card>
        </Grid>
      </Grid>

      <Card variant="outlined" sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle2" fontWeight={700} mb={1}>Ganancia neta vs bruta (BOB)</Typography>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={pnlSeries}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="fecha" fontSize={11} />
              <YAxis fontSize={11} tickFormatter={v => `Bs. ${formatCompactNumber(v)}`} />
              <RTooltip formatter={(v: any) => [fmtBOB(v), 'BOB']} />
              <Legend />
              <ReferenceLine y={0} stroke="#999" />
              <Line type="monotone" dataKey="neta" name="Neta" stroke="#2e7d32" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="bruta" name="Bruta" stroke="#1976d2" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {txSeries.length > 0 && (
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle2" fontWeight={700} mb={1}>Operaciones diarias</Typography>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={txSeries}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="fecha" fontSize={11} />
                <YAxis fontSize={11} />
                <RTooltip />
                <Legend />
                <Bar dataKey="compras" name="Compras" fill="#2e7d32" />
                <Bar dataKey="ventas" name="Ventas" fill="#c62828" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </Box>
  );
};

const Analytics: React.FC = () => {
  const [tab,          setTab]          = useState(0);
  const [pnlData,      setPnlData]      = useState<PnLData | null>(null);
  const [exposureData, setExposureData] = useState<ExposureData | null>(null);
  const [spreadData,   setSpreadData]   = useState<SpreadRow[]>([]);
  const [decisionData, setDecisionData] = useState<Recomendacion[]>([]);
  const [anomaliesData, setAnomaliesData] = useState<AnomaliesData | null>(null);
  const [trendsData,   setTrendsData]   = useState<TrendsData | null>(null);
  const [loading,      setLoading]      = useState(true);
  const [days,         setDays]         = useState(30);
  const { lastCapitalUpdate }           = useWebSocket();
  const { enqueueSnackbar }             = useSnackbar();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const dateFrom = new Date(Date.now() - days * 86400000).toISOString().split('T')[0];
      const dateTo   = new Date().toISOString().split('T')[0];

      // Decision endpoint requires ?currency= per call — fetch for each active currency
      // then merge into a recomendaciones array that DecisionPanel expects.
      const DECISION_CURRENCIES = ['USD', 'EUR', 'ARS', 'BRL'];

      const [pnlRes, expRes, spRes, anomRes, trendRes, ...decResults] = await Promise.allSettled([
        api.get('/analytics/pnl/',      { params: { date_from: dateFrom, date_to: dateTo } }),
        api.get('/analytics/exposure/'),
        api.get('/analytics/spread/'),
        api.get('/analytics/anomalies/'),
        api.get('/analytics/trends/',   { params: { date_from: dateFrom, date_to: dateTo } }),
        ...DECISION_CURRENCIES.map(c => api.get('/analytics/decision/', { params: { currency: c } })),
      ]);

      if (pnlRes.status === 'fulfilled') setPnlData(pnlRes.value.data);
      if (expRes.status === 'fulfilled') setExposureData(expRes.value.data);
      if (spRes.status === 'fulfilled')  setSpreadData(spRes.value.data.spreads ?? []);
      if (anomRes.status === 'fulfilled')  setAnomaliesData(anomRes.value.data);
      if (trendRes.status === 'fulfilled') setTrendsData(trendRes.value.data);

      // Map backend shape → Recomendacion interface
      // Backend: { currency, decision, motivo, score_total, señales, alertas, datos }
      // Frontend: { currency_code, accion, razon, score, señales, alertas, stock_actual, wac }
      const recomendaciones: Recomendacion[] = decResults
        .filter(r => r.status === 'fulfilled')
        .map(r => (r as PromiseFulfilledResult<any>).value.data)
        .filter(d => d.decision !== 'SIN_DATOS')
        .map(d => ({
          currency_code: d.currency,
          accion:        d.decision,
          razon:         d.motivo ?? '',
          score:         d.score_total ?? d.confianza ?? 0,
          señales:       d.señales ?? [],
          alertas:       d.alertas ?? [],
          stock_actual:  d.datos?.stock?.toString() ?? '0',
          wac:           d.datos?.wac?.toString() ?? '0',
        }));
      setDecisionData(recomendaciones);
    } catch {
      enqueueSnackbar('Error al cargar analytics', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [days, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  // Actualizar cuando cambia el capital (transacción procesada).
  // Coalescer los ticks WS a lo sumo un refetch cada 20s: en ráfagas de alto
  // volumen cada transacción emite `lastCapitalUpdate` y disparar los ~9 requests
  // por evento saturaría el backend. Refresco inmediato si ya pasó el intervalo;
  // si no, se agenda un refetch de cola (trailing) con los datos más recientes.
  const lastRefetchRef = useRef(0);
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!lastCapitalUpdate) return;
    const MIN_INTERVAL = 20000;
    const elapsed = Date.now() - lastRefetchRef.current;
    if (elapsed >= MIN_INTERVAL) {
      lastRefetchRef.current = Date.now();
      load();
    } else if (pendingTimerRef.current === null) {
      pendingTimerRef.current = setTimeout(() => {
        pendingTimerRef.current = null;
        lastRefetchRef.current = Date.now();
        load();
      }, MIN_INTERVAL - elapsed);
    }
    return () => {
      if (pendingTimerRef.current !== null) {
        clearTimeout(pendingTimerRef.current);
        pendingTimerRef.current = null;
      }
    };
  }, [lastCapitalUpdate, load]);

  const TABS = [
    { label: 'P&L', icon: <ShowChart fontSize="small" /> },
    { label: 'Exposición', icon: <AccountBalance fontSize="small" /> },
    { label: 'Spread', icon: <CurrencyExchange fontSize="small" /> },
    { label: 'Decisiones', icon: <Psychology fontSize="small" /> },
    { label: 'Anomalías', icon: <Warning fontSize="small" /> },
    { label: 'Tendencias', icon: <TrendingUp fontSize="small" /> },
  ];

  return (
    <Box>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={800}>Analytics Financiero</Typography>
          <Typography variant="body2" color="text.secondary">
            P&L real (WAC-based) · Exposición · Spreads · Motor de decisiones
          </Typography>
        </Box>
        <Box display="flex" gap={1} alignItems="center">
          {[7, 30, 90].map(d => (
            <Chip
              key={d}
              label={`${d}d`}
              onClick={() => setDays(d)}
              color={days === d ? 'primary' : 'default'}
              size="small"
            />
          ))}
          <Tooltip title="Actualizar">
            <IconButton onClick={load} size="small" disabled={loading}>
              {loading ? <CircularProgress size={18} /> : <Refresh />}
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3 }}
        variant="scrollable" scrollButtons="auto" allowScrollButtonsMobile>
        {TABS.map((t) => (
          <Tab key={t.label} icon={t.icon} iconPosition="start" label={t.label} />
        ))}
      </Tabs>

      {tab === 0 && <PnLPanel loading={loading} data={pnlData} />}
      {tab === 1 && <ExposurePanel loading={loading} data={exposureData} />}
      {tab === 2 && <SpreadPanel loading={loading} data={spreadData} />}
      {tab === 3 && <DecisionPanel loading={loading} data={decisionData} />}
      {tab === 4 && <AnomaliesPanel loading={loading} data={anomaliesData} />}
      {tab === 5 && <TrendsPanel loading={loading} data={trendsData} />}
    </Box>
  );
};

export default Analytics;
