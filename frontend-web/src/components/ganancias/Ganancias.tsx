// src/components/ganancias/Ganancias.tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button,
  Paper, Skeleton, Alert, IconButton, Tooltip, Divider,
  TextField, Table, TableHead, TableBody, TableRow,
  TableCell, TableContainer, Chip,
} from '@mui/material';
import {
  Refresh, TrendingUp, TrendingDown, AttachMoney,
  ShowChart, CurrencyExchange,
} from '@mui/icons-material';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, Cell, PieChart, Pie, Legend,
} from 'recharts';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { useBranchScope } from '../../contexts/BranchScopeContext';
import { formatCurrency, formatNumber } from '../../utils/formatters';

// ── Types ─────────────────────────────────────────────────────────────────────
// Keys match the actual backend response from GananciaService.resumen_financiero()
interface GananciaDivisa {
  divisa:              string;
  ops_compra:          number;
  ops_venta:           number;
  unidades_compradas:  string;
  unidades_vendidas:   string;
  costo_bob:           string;
  ingreso_bob:         string;
  ganancia_bob:        string;
  tc_compra_prom:      string;
  tc_venta_prom:       string;
  spread_prom:         string;
  margen_pct:          string;
}

interface ResumenFinanciero {
  periodo: { desde: string; hasta: string };
  ganancias_divisas: {
    total:   string;
    detalle: GananciaDivisa[];
  };
  ganancias_tarjetas: {
    total:    string;
    ventas:   number;
    ingresos: string;
  };
  gastos: {
    total:          string;
    count:          number;
    por_categoria:  { categoria: string; total: string; count: number }[];
  };
  ganancia_bruta: string;
  ganancia_neta:  string;
}

const CURRENCY_COLORS: Record<string, string> = {
  USD: '#1976d2', EUR: '#388e3c', CLP: '#f57c00', PEN: '#7b1fa2',
  BRL: '#00796b', ARS: '#d32f2f', USS: '#5d4037', US1: '#455a64',
};

// ── KPI Card ──────────────────────────────────────────────────────────────────
const KPI = ({ label, value, sub, color, icon, loading }: {
  label: string; value: string; sub?: string;
  color: string; icon: React.ReactNode; loading: boolean;
}) => (
  <Card sx={{ borderTop: `3px solid ${color}` }}>
    <CardContent>
      <Box display="flex" justifyContent="space-between" alignItems="flex-start">
        <Box>
          <Typography variant="caption" color="text.secondary" textTransform="uppercase" fontWeight={600} letterSpacing={0.5}>
            {label}
          </Typography>
          {loading ? <Skeleton width={120} height={40} /> : (
            <Typography variant="h5" fontWeight={800} sx={{ color }}>{value}</Typography>
          )}
          {sub && !loading && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
        </Box>
        <Box sx={{ color, opacity: 0.7 }}>{icon}</Box>
      </Box>
    </CardContent>
  </Card>
);

// ── Main ─────────────────────────────────────────────────────────────────────
const Ganancias: React.FC = () => {
  const [resumen, setResumen] = useState<ResumenFinanciero | null>(null);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState(
    new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0]
  );
  const [dateTo, setDateTo] = useState(new Date().toISOString().split('T')[0]);
  const { enqueueSnackbar } = useSnackbar();
  const { branchParams } = useBranchScope();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/capital/resumen/', {
        params: { date_from: dateFrom, date_to: dateTo, ...branchParams },
      });
      setResumen(res.data);
    } catch {
      enqueueSnackbar('Error al cargar resumen financiero', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, enqueueSnackbar, branchParams]);

  useEffect(() => { load(); }, [load]);

  const divisas = resumen?.ganancias_divisas?.detalle ?? [];
  const pieData = divisas
    .filter(d => parseFloat(d.ganancia_bob) > 0)
    .map(d => ({ name: d.divisa, value: parseFloat(d.ganancia_bob), color: CURRENCY_COLORS[d.divisa] ?? '#607d8b' }));

  const gananciaTotal = parseFloat(resumen?.ganancia_neta ?? '0');
  const gananciaPositiva = gananciaTotal >= 0;

  return (
    <Box>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={800}>Ganancias & Rentabilidad</Typography>
          <Typography variant="body2" color="text.secondary">
            Análisis financiero por período y divisa
          </Typography>
        </Box>
        <Tooltip title="Actualizar">
          <IconButton onClick={load}><Refresh /></IconButton>
        </Tooltip>
      </Box>

      {/* Filtros fecha */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box display="flex" gap={2} alignItems="center" flexWrap="wrap">
          <TextField label="Desde" type="date" size="small" value={dateFrom}
            onChange={e => setDateFrom(e.target.value)}
            InputLabelProps={{ shrink: true }} />
          <TextField label="Hasta" type="date" size="small" value={dateTo}
            onChange={e => setDateTo(e.target.value)}
            InputLabelProps={{ shrink: true }} />
          <Button variant="contained" onClick={load} startIcon={<ShowChart />}>
            Analizar
          </Button>
          {resumen && (
            <Chip
              icon={gananciaPositiva ? <TrendingUp /> : <TrendingDown />}
              label={`Ganancia neta: ${formatCurrency(Math.abs(gananciaTotal))}`}
              color={gananciaPositiva ? 'success' : 'error'}
              variant="outlined"
            />
          )}
        </Box>
      </Paper>

      {/* KPIs */}
      <Grid container spacing={2} mb={3}>
        {[
          {
            label: 'Ganancia Divisas',
            value: formatCurrency(parseFloat(resumen?.ganancias_divisas?.total ?? '0')),
            sub: `${divisas.reduce((s, d) => s + d.ops_compra + d.ops_venta, 0)} operaciones`,
            color: '#1976d2',
            icon: <CurrencyExchange />,
          },
          {
            label: 'Ganancia Tarjetas',
            value: formatCurrency(parseFloat(resumen?.ganancias_tarjetas?.total ?? '0')),
            sub: `${resumen?.ganancias_tarjetas?.ventas ?? 0} ventas`,
            color: '#7b1fa2',
            icon: <AttachMoney />,
          },
          {
            label: 'Gastos Operativos',
            value: formatCurrency(parseFloat(resumen?.gastos?.total ?? '0')),
            color: '#c62828',
            icon: <TrendingDown />,
          },
          {
            label: 'Ganancia Neta',
            value: formatCurrency(Math.abs(gananciaTotal)),
            sub: gananciaPositiva ? 'Positivo ✓' : 'Negativo ✗',
            color: gananciaPositiva ? '#2e7d32' : '#c62828',
            icon: <TrendingUp />,
          },
        ].map(k => (
          <Grid item key={k.label} xs={6} md={3}>
            <KPI {...k} loading={loading} />
          </Grid>
        ))}
      </Grid>

      <Grid container spacing={3}>
        {/* Ganancia por divisa — tabla */}
        <Grid item xs={12} md={7}>
          <Card>
            <CardContent>
              <Typography variant="h6" fontWeight={700} mb={2}>
                Detalle por Divisa
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow sx={{ bgcolor: 'grey.50' }}>
                      <TableCell><strong>Divisa</strong></TableCell>
                      <TableCell align="center"><strong>Ops.</strong></TableCell>
                      <TableCell align="right"><strong>Compra prom.</strong></TableCell>
                      <TableCell align="right"><strong>Venta prom.</strong></TableCell>
                      <TableCell align="right"><strong>Volumen BOB</strong></TableCell>
                      <TableCell align="right"><strong>Ganancia</strong></TableCell>
                      <TableCell align="right"><strong>Margen</strong></TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading ? (
                      Array.from({ length: 5 }).map((_, i) => (
                        <TableRow key={i}><TableCell colSpan={7}><Skeleton /></TableCell></TableRow>
                      ))
                    ) : divisas.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={7} align="center">
                          <Typography color="text.secondary" py={2}>Sin operaciones en el período</Typography>
                        </TableCell>
                      </TableRow>
                    ) : divisas.map(d => {
                      const ganancia  = parseFloat(d.ganancia_bob);
                      const margen    = parseFloat(d.margen_pct);
                      const ingresos  = parseFloat(d.ingreso_bob);
                      return (
                      <TableRow key={d.divisa} hover>
                        <TableCell>
                          <Box display="flex" alignItems="center" gap={1}>
                            <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: CURRENCY_COLORS[d.divisa] ?? '#607d8b' }} />
                            <Typography variant="body2" fontWeight={700}>{d.divisa}</Typography>
                          </Box>
                        </TableCell>
                        <TableCell align="center">{d.ops_compra + d.ops_venta}</TableCell>
                        <TableCell align="right">{parseFloat(d.tc_compra_prom).toFixed(4)}</TableCell>
                        <TableCell align="right">{parseFloat(d.tc_venta_prom).toFixed(4)}</TableCell>
                        <TableCell align="right">{formatCurrency(ingresos)}</TableCell>
                        <TableCell align="right">
                          <Typography fontWeight={700}
                            color={ganancia >= 0 ? 'success.main' : 'error.main'}>
                            {formatCurrency(ganancia)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Chip label={`${margen.toFixed(2)}%`} size="small"
                            color={margen > 0 ? 'success' : 'error'} variant="outlined" />
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

        {/* Pie chart distribución */}
        <Grid item xs={12} md={5}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" fontWeight={700} mb={2}>
                Distribución de Ganancias
              </Typography>
              {loading ? (
                <Skeleton variant="circular" width={200} height={200} sx={{ mx: 'auto' }} />
              ) : pieData.length === 0 ? (
                <Box textAlign="center" py={4}>
                  <CurrencyExchange sx={{ fontSize: 48, color: 'action.disabled' }} />
                  <Typography color="text.secondary" mt={1}>Sin datos disponibles</Typography>
                </Box>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" outerRadius={90}
                      dataKey="value" nameKey="name" label={({ name, percent }) =>
                        `${name} ${(percent * 100).toFixed(1)}%`}>
                      {pieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                    </Pie>
                    <RTooltip formatter={(v: any) => [formatCurrency(v), 'Ganancia']} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              )}

              {/* Gastos por categoría */}
              {(resumen?.gastos?.por_categoria?.length ?? 0) > 0 && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Typography variant="subtitle2" fontWeight={700} mb={1}>Gastos por Categoría</Typography>
                  {resumen!.gastos.por_categoria.slice(0, 5).map(c => (
                    <Box key={c.categoria} display="flex" justifyContent="space-between" py={0.3}>
                      <Typography variant="caption" color="text.secondary">{c.categoria}</Typography>
                      <Typography variant="caption" fontWeight={600} color="error.main">
                        {formatCurrency(parseFloat(c.total))}
                      </Typography>
                    </Box>
                  ))}
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Ganancia bar chart por divisa */}
        {divisas.length > 0 && (
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" fontWeight={700} mb={2}>
                  Ganancia vs Volumen por Divisa
                </Typography>
                {loading ? (
                  <Skeleton variant="rectangular" height={250} />
                ) : (
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart
                      data={divisas.map(d => ({
                        divisa:      d.divisa,
                        ingreso_bob: parseFloat(d.ingreso_bob),
                        ganancia_bob: parseFloat(d.ganancia_bob),
                      }))}
                      margin={{ top: 0, right: 20, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis dataKey="divisa" tick={{ fontSize: 12 }} />
                      <YAxis yAxisId="left" tick={{ fontSize: 10 }} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                      <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }}
                        tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                      <RTooltip formatter={(v: any, name: string) => [formatCurrency(v), name]} />
                      <Bar yAxisId="left" dataKey="ingreso_bob" name="Ingresos" fill="#90caf9" radius={[4, 4, 0, 0]} />
                      <Bar yAxisId="right" dataKey="ganancia_bob" name="Ganancia" radius={[4, 4, 0, 0]}>
                        {divisas.map((d, i) => (
                          <Cell key={i} fill={parseFloat(d.ganancia_bob) >= 0 ? '#2e7d32' : '#c62828'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </Grid>
        )}
      </Grid>
    </Box>
  );
};

export default Ganancias;
