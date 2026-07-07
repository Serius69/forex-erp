import React, { useEffect, useState } from 'react';
import {
  Box, Grid, Typography, Card, CardContent, Divider,
  CircularProgress, Chip, Table, TableHead, TableRow,
  TableCell, TableBody, Select, MenuItem, FormControl,
} from '@mui/material';
import { Store, TrendingUp, SwapHoriz, AccountBalance } from '@mui/icons-material';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { TOKENS } from '../../styles/theme';
import { alpha } from '@mui/material/styles';
import { Branch } from '../../types';

interface BranchStat {
  branch_id:     number;
  branch_name:   string;
  tx_count:      number;
  tx_volume_bob: number;
  profit_bob:    number;
  margin_pct:    number;
  cashier_count: number;
}

export default function BranchAnalytics() {
  const { user } = useAuth();
  const [branches,    setBranches]    = useState<Branch[]>([]);
  const [stats,       setStats]       = useState<BranchStat[]>([]);
  const [selectedBr,  setSelectedBr]  = useState<number | 'all'>('all');
  const [loading,     setLoading]     = useState(true);
  const [period,      setPeriod]      = useState<'today' | 'week' | 'month'>('today');

  useEffect(() => {
    api.get('/users/branches/')
      .then(r => setBranches(r.data?.results ?? r.data ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    const params: Record<string, string> = { period };
    if (selectedBr !== 'all') params.branch = String(selectedBr);

    api.get('/analytics/branch-stats/', { params })
      .then(r => setStats(r.data?.results ?? r.data ?? []))
      .catch(() => setStats([]))
      .finally(() => setLoading(false));
  }, [period, selectedBr]);

  const totalTx     = stats.reduce((s, b) => s + b.tx_count,      0);
  const totalVolume = stats.reduce((s, b) => s + b.tx_volume_bob, 0);
  const totalProfit = stats.reduce((s, b) => s + b.profit_bob,    0);
  const avgMargin   = stats.length ? stats.reduce((s, b) => s + b.margin_pct, 0) / stats.length : 0;

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Store sx={{ color: TOKENS.blue, fontSize: 28 }} />
          <Box>
            <Typography variant="h5" fontWeight={800}>Analítica de Sucursales</Typography>
            <Typography variant="caption" color="text.secondary">
              {user?.company?.name} · Comparativa entre sucursales
            </Typography>
          </Box>
        </Box>

        <Box sx={{ display: 'flex', gap: 1.5 }}>
          {/* Period selector */}
          <FormControl size="small">
            <Select value={period} onChange={e => setPeriod(e.target.value as any)}>
              <MenuItem value="today">Hoy</MenuItem>
              <MenuItem value="week">Esta semana</MenuItem>
              <MenuItem value="month">Este mes</MenuItem>
            </Select>
          </FormControl>

          {/* Branch filter (ADMIN/SUPERVISOR only) */}
          {user?.role !== 'CASHIER' && (
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <Select value={selectedBr} onChange={e => setSelectedBr(e.target.value as any)} displayEmpty>
                <MenuItem value="all"><em>Todas las sucursales</em></MenuItem>
                {branches.map(b => (
                  <MenuItem key={b.id} value={b.id}>{b.name}</MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
        </Box>
      </Box>

      {/* Summary KPIs */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {[
          { label: 'Transacciones', value: totalTx.toLocaleString(), icon: <SwapHoriz />, color: TOKENS.blue },
          { label: 'Volumen BOB', value: `Bs ${totalVolume.toLocaleString('es-BO', { maximumFractionDigits: 0 })}`, icon: <AccountBalance />, color: TOKENS.green },
          { label: 'Ganancia BOB', value: `Bs ${totalProfit.toLocaleString('es-BO', { maximumFractionDigits: 0 })}`, icon: <TrendingUp />, color: TOKENS.amber },
          { label: 'Margen Promedio', value: `${avgMargin.toFixed(2)}%`, icon: <Store />, color: TOKENS.blue },
        ].map(kpi => (
          <Grid item xs={6} sm={3} key={kpi.label}>
            <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
              <CardContent sx={{ py: '12px !important' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Box sx={{ color: kpi.color, opacity: 0.7, '& svg': { fontSize: 18 } }}>{kpi.icon}</Box>
                  <Typography variant="caption" color="text.secondary">{kpi.label}</Typography>
                </Box>
                <Typography variant="h6" fontWeight={800} sx={{ color: kpi.color }}>
                  {kpi.value}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Branch comparison table */}
      <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 2 }}>
            Comparativa por Sucursal
          </Typography>
          <Divider sx={{ mb: 2 }} />

          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
              <CircularProgress size={32} />
            </Box>
          ) : stats.length === 0 ? (
            <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
              Sin datos para el período seleccionado
            </Typography>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell><strong>Sucursal</strong></TableCell>
                  <TableCell align="right"><strong>Transacciones</strong></TableCell>
                  <TableCell align="right"><strong>Volumen BOB</strong></TableCell>
                  <TableCell align="right"><strong>Ganancia BOB</strong></TableCell>
                  <TableCell align="right"><strong>Margen %</strong></TableCell>
                  <TableCell align="right"><strong>Cajeros</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {stats.map(b => (
                  <TableRow key={b.branch_id} hover>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Store sx={{ fontSize: 14, color: TOKENS.blue, opacity: 0.7 }} />
                        <Typography variant="body2" fontWeight={600}>{b.branch_name}</Typography>
                      </Box>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body2">{b.tx_count.toLocaleString()}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body2">
                        {b.tx_volume_bob.toLocaleString('es-BO', { maximumFractionDigits: 0 })}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body2" sx={{ color: b.profit_bob >= 0 ? TOKENS.green : TOKENS.red, fontWeight: 600 }}>
                        {b.profit_bob.toLocaleString('es-BO', { maximumFractionDigits: 0 })}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Chip
                        size="small"
                        label={`${b.margin_pct.toFixed(2)}%`}
                        sx={{
                          bgcolor: alpha(b.margin_pct >= 1 ? TOKENS.green : TOKENS.amber, 0.12),
                          color:   b.margin_pct >= 1 ? TOKENS.green : TOKENS.amber,
                          fontWeight: 700, fontSize: '0.7rem',
                        }}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body2">{b.cashier_count}</Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
