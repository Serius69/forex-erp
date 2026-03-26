import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Chip, IconButton, Tooltip, LinearProgress,
  Typography, Grid, Card, CardContent, Alert, Badge,
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField,
} from '@mui/material';
import { Tune, History, Refresh, Warning, CheckCircle } from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { api } from '../../services/api';
import { formatNumber } from '../../utils/formatters';
import { useAuth } from '../../contexts/AuthContext';

const InventoryStock: React.FC = () => {
  const [inventory,  setInventory]  = useState<any[]>([]);
  const [alerts,     setAlerts]     = useState<any[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [selected,   setSelected]   = useState<any>(null);
  const [adjValues,  setAdjValues]  = useState({ physical_count: '', digital_count: '', reason: '' });
  const { user }                    = useAuth();
  const { enqueueSnackbar }         = useSnackbar();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [invRes, alertRes] = await Promise.all([
        api.get('/inventory/stock/'),
        api.get('/inventory/alerts/', { params: { is_resolved: false } }),
      ]);
      setInventory(invRes.data.results   ?? invRes.data);
      setAlerts(alertRes.data.results    ?? alertRes.data);
    } catch {
      enqueueSnackbar('Error al cargar inventario', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const handleAdjust = async () => {
    if (!selected) return;
    try {
      await api.post(`/inventory/stock/${selected.id}/adjust/`, {
        physical_count: parseFloat(adjValues.physical_count),
        digital_count:  parseFloat(adjValues.digital_count),
        reason:         adjValues.reason,
      });
      enqueueSnackbar('Inventario ajustado', { variant: 'success' });
      setAdjustOpen(false);
      load();
    } catch {
      enqueueSnackbar('Error al ajustar', { variant: 'error' });
    }
  };

  const handleResolveAlert = async (alertId: number) => {
    try {
      await api.post(`/inventory/alerts/${alertId}/resolve/`, { notes: 'Resuelto manualmente' });
      enqueueSnackbar('Alerta resuelta', { variant: 'success' });
      load();
    } catch {
      enqueueSnackbar('Error', { variant: 'error' });
    }
  };

  const getStockColor = (item: any) => {
    if (item.needs_replenishment) return 'error';
    if (item.is_overstocked)      return 'warning';
    return 'success';
  };

  const criticalAlerts = alerts.filter(a =>
    a.severity === 'CRITICAL' || a.severity === 'HIGH');

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" mb={2}>
        <Box display="flex" gap={1}>
          {criticalAlerts.length > 0 && (
            <Alert severity="error" sx={{ py: 0.5 }}>
              {criticalAlerts.length} alerta(s) crítica(s)
            </Alert>
          )}
        </Box>
        <Button startIcon={<Refresh />} onClick={load} variant="outlined">
          Actualizar
        </Button>
      </Box>

      {/* KPIs */}
      <Grid container spacing={2} mb={3}>
        {[
          ['Total Divisas',  inventory.length,                                    'primary'],
          ['Stock Bajo',     inventory.filter(i => i.needs_replenishment).length, 'error'],
          ['Sobrestock',     inventory.filter(i => i.is_overstocked).length,      'warning'],
          ['Alertas Activas',alerts.length,                                        'warning'],
        ].map(([label, value, color]) => (
          <Grid xs={12} sm={6} md={3} key={label as string}>
            <Card sx={{ borderLeft: 4, borderColor: `${color}.main` }}>
              <CardContent sx={{ py: 1.5 }}>
                <Typography variant="body2" color="text.secondary">{label as string}</Typography>
                <Typography variant="h4" color={`${color}.main`}>{value as number}</Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Tabla stock */}
      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Divisa</TableCell>
              <TableCell>Sucursal</TableCell>
              <TableCell align="right">Físico</TableCell>
              <TableCell align="right">Digital</TableCell>
              <TableCell align="right">Total</TableCell>
              <TableCell>Nivel</TableCell>
              <TableCell>Estado</TableCell>
              <TableCell>Actualizado</TableCell>
              {user?.role !== 'CASHIER' && <TableCell>Acciones</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {inventory.map((item) => (
              <TableRow key={item.id} hover
                sx={{ bgcolor: item.needs_replenishment ? 'error.50' : 'inherit' }}>
                <TableCell>
                  <Typography fontWeight="bold">{item.currency?.code}</Typography>
                  <Typography variant="caption" color="text.secondary">{item.currency?.name}</Typography>
                </TableCell>
                <TableCell>{item.branch?.name}</TableCell>
                <TableCell align="right">{formatNumber(item.physical_balance)}</TableCell>
                <TableCell align="right">{formatNumber(item.digital_balance)}</TableCell>
                <TableCell align="right">
                  <Typography fontWeight="bold">{formatNumber(item.total_balance)}</Typography>
                </TableCell>
                <TableCell sx={{ minWidth: 120 }}>
                  <LinearProgress
                    variant="determinate"
                    value={Math.min(item.stock_level_percentage ?? 0, 100)}
                    color={getStockColor(item)}
                    sx={{ mb: 0.5, height: 6, borderRadius: 3 }}
                  />
                  <Typography variant="caption">
                    {(item.stock_level_percentage ?? 0).toFixed(0)}%
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    label={item.needs_replenishment ? 'Stock Bajo' :
                           item.is_overstocked      ? 'Sobrestock' : 'Normal'}
                    color={getStockColor(item)}
                    size="small"
                  />
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {format(new Date(item.last_updated), 'dd/MM HH:mm', { locale: es })}
                  </Typography>
                </TableCell>
                {user?.role !== 'CASHIER' && (
                  <TableCell>
                    <Tooltip title="Ajustar inventario">
                      <IconButton size="small" onClick={() => {
                        setSelected(item);
                        setAdjValues({
                          physical_count: String(item.physical_balance),
                          digital_count:  String(item.digital_balance),
                          reason: '',
                        });
                        setAdjustOpen(true);
                      }}>
                        <Tune />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Alertas activas */}
      {alerts.length > 0 && (
        <Box mt={3}>
          <Typography variant="h6" mb={1}>Alertas Activas</Typography>
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Tipo</TableCell>
                  <TableCell>Divisa / Sucursal</TableCell>
                  <TableCell>Severidad</TableCell>
                  <TableCell>Mensaje</TableCell>
                  <TableCell>Acciones</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {alerts.map((alert) => (
                  <TableRow key={alert.id} hover>
                    <TableCell>{alert.alert_type}</TableCell>
                    <TableCell>
                      {alert.inventory?.currency?.code} — {alert.inventory?.branch?.name}
                    </TableCell>
                    <TableCell>
                      <Chip label={alert.severity}
                        color={alert.severity === 'CRITICAL' ? 'error' :
                               alert.severity === 'HIGH'     ? 'warning' : 'default'}
                        size="small" />
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption">{alert.message}</Typography>
                    </TableCell>
                    <TableCell>
                      <Button size="small" onClick={() => handleResolveAlert(alert.id)}>
                        Resolver
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {/* Dialog ajuste */}
      <Dialog open={adjustOpen} onClose={() => setAdjustOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>
          Ajustar — {selected?.currency?.code} ({selected?.branch?.name})
        </DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid xs={6}>
              <TextField fullWidth label="Balance Físico" type="number"
                value={adjValues.physical_count}
                onChange={(e) => setAdjValues({ ...adjValues, physical_count: e.target.value })} />
            </Grid>
            <Grid xs={6}>
              <TextField fullWidth label="Balance Digital" type="number"
                value={adjValues.digital_count}
                onChange={(e) => setAdjValues({ ...adjValues, digital_count: e.target.value })} />
            </Grid>
            <Grid xs={12}>
              <TextField fullWidth label="Razón del ajuste" multiline rows={2}
                value={adjValues.reason}
                onChange={(e) => setAdjValues({ ...adjValues, reason: e.target.value })} />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAdjustOpen(false)}>Cancelar</Button>
          <Button variant="contained" onClick={handleAdjust} disabled={!adjValues.reason}>
            Confirmar
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default InventoryStock;