// src/components/capital/Capital.tsx
import React, { useState, useEffect } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, Chip,
  Table, TableHead, TableBody, TableRow, TableCell, TableContainer,
  Paper, Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, FormControl, InputLabel, Select, MenuItem,
  Tabs, Tab, Skeleton, Alert, IconButton, Tooltip, Divider,
} from '@mui/material';
import {
  Add, Refresh, AccountBalance, Receipt,
  CameraAlt, Assessment, Inventory2,
} from '@mui/icons-material';
import {
  PieChart, Pie, Cell, Tooltip as RTooltip,
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatCurrency, formatNumber } from '../../utils/formatters';
import { useAuth } from '../../contexts/AuthContext';
import CapitalCaja from './CapitalCaja';
import CapitalDashboard from './CapitalDashboard';
import CapitalTimeline from './CapitalTimeline';
import { useDashboard } from '../../hooks/useDashboard';
import type { CapitalActual, Gasto, ResumenGastos, CapitalSnapshot } from '../../hooks/useDashboard';

const CATEGORIAS = [
  'ALQUILER', 'SERVICIOS', 'SALARIOS', 'SUMINISTROS',
  'MANTENIMIENTO', 'IMPUESTOS', 'PUBLICIDAD', 'SEGUROS',
  'TRANSPORTE', 'CAPACITACION', 'TECNOLOGIA', 'OTROS',
];

const CATEGORIA_COLOR: Record<string, string> = {
  ALQUILER: '#1976d2', SERVICIOS: '#388e3c', SALARIOS: '#f57c00',
  SUMINISTROS: '#7b1fa2', MANTENIMIENTO: '#d32f2f', IMPUESTOS: '#0288d1',
  PUBLICIDAD: '#c2185b', SEGUROS: '#00796b', TRANSPORTE: '#5d4037',
  CAPACITACION: '#455a64', TECNOLOGIA: '#283593', OTROS: '#757575',
};

// ── Capital Actual Card ───────────────────────────────────────────────────────
const CapitalActualCard = ({ capital, loading }: { capital: CapitalActual | null; loading: boolean }) => (
  <Card sx={{ borderTop: '4px solid #1976d2' }}>
    <CardContent>
      <Box display="flex" alignItems="center" gap={1} mb={2}>
        <AccountBalance color="primary" />
        <Typography variant="h6" fontWeight={700}>Capital en Tiempo Real</Typography>
      </Box>
      {loading ? (
        <>
          <Skeleton height={60} />
          <Skeleton height={40} />
          <Skeleton height={40} />
        </>
      ) : capital ? (
        <>
          <Typography variant="h3" fontWeight={800} color="primary" mb={1}>
            {formatCurrency(parseFloat(capital.total_bob))}
          </Typography>
          <Divider sx={{ my: 1.5 }} />
          {[
            { label: 'Efectivo BOB', value: parseFloat(capital.efectivo_bob), color: '#2e7d32' },
            { label: 'Divisas (val. venta)', value: parseFloat(capital.divisas_bob), color: '#1976d2' },
            { label: 'Tarjetas', value: parseFloat(capital.tarjetas_bob), color: '#7b1fa2' },
          ].map(item => (
            <Box key={item.label} display="flex" justifyContent="space-between" py={0.5}>
              <Typography variant="body2" color="text.secondary">{item.label}</Typography>
              <Typography variant="body2" fontWeight={700} color={item.color}>
                {formatCurrency(item.value)}
              </Typography>
            </Box>
          ))}
          {Object.keys(capital.detalle_divisas ?? {}).length > 0 && (
            <>
              <Divider sx={{ my: 1 }} />
              <Typography variant="caption" color="text.secondary" fontWeight={600}>DESGLOSE POR DIVISA</Typography>
              {Object.entries(capital.detalle_divisas).map(([code, d]) => (
                <Box key={code} display="flex" justifyContent="space-between" py={0.3}>
                  <Typography variant="caption" color="text.secondary">{code}: {formatNumber(parseFloat(d.stock), 2)}</Typography>
                  <Typography variant="caption" fontWeight={600}>{formatCurrency(parseFloat(d.valor_bob))}</Typography>
                </Box>
              ))}
            </>
          )}
        </>
      ) : (
        <Alert severity="info">No hay datos de capital disponibles</Alert>
      )}
    </CardContent>
  </Card>
);

// ── Dialog: Nuevo Gasto ──────────────────────────────────────────────────────
const GastoDialog = ({ open, onClose, onSuccess }: {
  open: boolean; onClose: () => void; onSuccess: () => void;
}) => {
  const [form, setForm] = useState({
    fecha: new Date().toISOString().split('T')[0],
    categoria: 'OTROS',
    descripcion: '',
    monto_bob: '',
    medio_pago: 'CASH',
    proveedor: '',
    nro_factura: '',
  });
  const [loading, setLoading] = useState(false);
  const { enqueueSnackbar } = useSnackbar();

  useEffect(() => {
    if (open) setForm({
      fecha: new Date().toISOString().split('T')[0],
      categoria: 'OTROS', descripcion: '', monto_bob: '',
      medio_pago: 'CASH', proveedor: '', nro_factura: '',
    });
  }, [open]);

  const submit = async () => {
    if (!form.descripcion || !form.monto_bob) return;
    setLoading(true);
    try {
      await api.post('/capital/gastos/', {
        ...form,
        monto_bob: parseFloat(form.monto_bob),
      });
      enqueueSnackbar('Gasto registrado', { variant: 'success' });
      onSuccess();
      onClose();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al registrar gasto', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <Receipt color="error" /> Registrar Gasto
        </Box>
      </DialogTitle>
      <DialogContent>
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Grid item xs={6}>
            <TextField fullWidth label="Fecha" type="date" value={form.fecha}
              onChange={e => setForm(p => ({ ...p, fecha: e.target.value }))}
              InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid item xs={6}>
            <FormControl fullWidth>
              <InputLabel>Categoría</InputLabel>
              <Select value={form.categoria} label="Categoría"
                onChange={e => setForm(p => ({ ...p, categoria: e.target.value }))}>
                {CATEGORIAS.map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12}>
            <TextField fullWidth label="Descripción" required value={form.descripcion}
              onChange={e => setForm(p => ({ ...p, descripcion: e.target.value }))} />
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="Monto (Bs.)" type="number" required value={form.monto_bob}
              onChange={e => setForm(p => ({ ...p, monto_bob: e.target.value }))}
              inputProps={{ min: 0.01, step: 0.01 }} />
          </Grid>
          <Grid item xs={6}>
            <FormControl fullWidth>
              <InputLabel>Medio de Pago</InputLabel>
              <Select value={form.medio_pago} label="Medio de Pago"
                onChange={e => setForm(p => ({ ...p, medio_pago: e.target.value }))}>
                <MenuItem value="CASH">Efectivo</MenuItem>
                <MenuItem value="TRANSFER">Transferencia</MenuItem>
                <MenuItem value="QR">QR</MenuItem>
                <MenuItem value="CHECK">Cheque</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="Proveedor" value={form.proveedor}
              onChange={e => setForm(p => ({ ...p, proveedor: e.target.value }))} />
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="N° Factura" value={form.nro_factura}
              onChange={e => setForm(p => ({ ...p, nro_factura: e.target.value }))} />
          </Grid>
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" color="error" onClick={submit}
          disabled={loading || !form.descripcion || !form.monto_bob}>
          Registrar Gasto
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// ── Dialog: Snapshot ─────────────────────────────────────────────────────────
const SnapshotDialog = ({ open, onClose, onSuccess }: {
  open: boolean; onClose: () => void; onSuccess: () => void;
}) => {
  const [form, setForm] = useState({ tipo: 'CIERRE', efectivo_bob: '', qr_bob: '0', pasivos_bob: '0', notas: '' });
  const [loading, setLoading] = useState(false);
  const { enqueueSnackbar } = useSnackbar();

  const submit = async () => {
    setLoading(true);
    try {
      await api.post('/capital/snapshots/generar/', {
        tipo: form.tipo,
        efectivo_bob: parseFloat(form.efectivo_bob || '0'),
        qr_bob: parseFloat(form.qr_bob || '0'),
        pasivos_bob: parseFloat(form.pasivos_bob || '0'),
        notas: form.notas,
      });
      enqueueSnackbar('Snapshot generado correctamente', { variant: 'success' });
      onSuccess();
      onClose();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al generar snapshot', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <CameraAlt color="primary" /> Generar Snapshot de Capital
        </Box>
      </DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>
          Las divisas y tarjetas se calcularán automáticamente. Ingresa el efectivo físico contado.
        </Alert>
        <Grid container spacing={2}>
          <Grid item xs={12}>
            <FormControl fullWidth>
              <InputLabel>Tipo</InputLabel>
              <Select value={form.tipo} label="Tipo"
                onChange={e => setForm(p => ({ ...p, tipo: e.target.value }))}>
                <MenuItem value="APERTURA">Apertura</MenuItem>
                <MenuItem value="CIERRE">Cierre</MenuItem>
                <MenuItem value="MANUAL">Manual</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="Efectivo BOB" type="number" value={form.efectivo_bob}
              onChange={e => setForm(p => ({ ...p, efectivo_bob: e.target.value }))}
              inputProps={{ min: 0, step: 0.01 }} />
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="QR / Digital BOB" type="number" value={form.qr_bob}
              onChange={e => setForm(p => ({ ...p, qr_bob: e.target.value }))}
              inputProps={{ min: 0, step: 0.01 }} />
          </Grid>
          <Grid item xs={12}>
            <TextField fullWidth label="Pasivos / Deudas BOB" type="number" value={form.pasivos_bob}
              onChange={e => setForm(p => ({ ...p, pasivos_bob: e.target.value }))}
              inputProps={{ min: 0, step: 0.01 }} />
          </Grid>
          <Grid item xs={12}>
            <TextField fullWidth label="Notas" multiline rows={2} value={form.notas}
              onChange={e => setForm(p => ({ ...p, notas: e.target.value }))} />
          </Grid>
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" onClick={submit} disabled={loading}>
          Generar Snapshot
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────
const Capital: React.FC = () => {
  const [tab, setTab]                   = useState(0);
  const [gastoDialog, setGastoDialog]   = useState(false);
  const [snapshotDialog, setSnapshotDialog] = useState(false);
  const [dateFrom]                      = useState(new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0]);
  const [dateTo]                        = useState(new Date().toISOString().split('T')[0]);

  const { capital, gastos, resumenGastos, snapshots, loading, canSnapshot, refresh: load } =
    useDashboard(dateFrom, dateTo);

  const pieData = resumenGastos?.por_categoria.map(c => ({
    name: c.categoria,
    value: parseFloat(c.total),
    color: CATEGORIA_COLOR[c.categoria] ?? '#757575',
  })) ?? [];

  return (
    <Box>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={800}>Capital & Gastos</Typography>
          <Typography variant="body2" color="text.secondary">Control financiero interno de la sucursal</Typography>
        </Box>
        <Box display="flex" gap={1}>
          {canSnapshot && (
            <Button variant="outlined" startIcon={<CameraAlt />} onClick={() => setSnapshotDialog(true)}>
              Snapshot
            </Button>
          )}
          <Button variant="contained" color="error" startIcon={<Add />} onClick={() => setGastoDialog(true)}>
            Nuevo Gasto
          </Button>
          <Tooltip title="Actualizar">
            <IconButton onClick={load}><Refresh /></IconButton>
          </Tooltip>
        </Box>
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3 }}>
        <Tab icon={<Assessment />} iconPosition="start" label="Dashboard" />
        <Tab icon={<AccountBalance />} iconPosition="start" label="Capital Actual" />
        <Tab icon={<Receipt />} iconPosition="start" label="Gastos" />
        {canSnapshot && <Tab icon={<CameraAlt />} iconPosition="start" label="Snapshots" />}
        <Tab icon={<Inventory2 />} iconPosition="start" label="Caja Manual" value={canSnapshot ? 4 : 3} />
      </Tabs>

      {/* Tab 0: Dashboard */}
      {tab === 0 && (
        <Box display="flex" flexDirection="column" gap={3}>
          <CapitalDashboard />
          <CapitalTimeline />
        </Box>
      )}

      {/* Tab 1: Capital Actual */}
      {tab === 1 && (
        <Grid container spacing={3}>
          <Grid item xs={12} md={5}>
            <CapitalActualCard capital={capital} loading={loading} />
          </Grid>
          <Grid item xs={12} md={7}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="h6" fontWeight={700} mb={2}>
                  Composición del Capital
                </Typography>
                {loading ? (
                  <Skeleton variant="rectangular" height={280} />
                ) : capital ? (
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={[
                      { name: 'Efectivo', value: parseFloat(capital.efectivo_bob) },
                      { name: 'Divisas', value: parseFloat(capital.divisas_bob) },
                      { name: 'Tarjetas', value: parseFloat(capital.tarjetas_bob) },
                    ]}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                      <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `Bs.${(v / 1000).toFixed(0)}k`} />
                      <RTooltip formatter={(v: any) => [formatCurrency(v), 'Valor']} />
                      <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                        {['#2e7d32', '#1976d2', '#7b1fa2'].map((color, i) => (
                          <Cell key={i} fill={color} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <Alert severity="warning">Sin datos de capital. Configure el inventario primero.</Alert>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Tab 2: Gastos */}
      {tab === 2 && (
        <Grid container spacing={3}>
          {/* Resumen pie chart */}
          {resumenGastos && parseFloat(resumenGastos.total_bob) > 0 && (
            <Grid item xs={12} md={4}>
              <Card>
                <CardContent>
                  <Typography fontWeight={700} mb={1}>Gastos por Categoría</Typography>
                  <Typography variant="h5" fontWeight={800} color="error.main">
                    {formatCurrency(parseFloat(resumenGastos.total_bob))}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {resumenGastos.total_gastos} gastos registrados
                  </Typography>
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie data={pieData} cx="50%" cy="50%" outerRadius={80}
                        dataKey="value" nameKey="name">
                        {pieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                      </Pie>
                      <RTooltip formatter={(v: any) => [formatCurrency(v), '']} />
                    </PieChart>
                  </ResponsiveContainer>
                  {resumenGastos.por_categoria.slice(0, 4).map(c => (
                    <Box key={c.categoria} display="flex" justifyContent="space-between" py={0.3}>
                      <Box display="flex" alignItems="center" gap={0.5}>
                        <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: CATEGORIA_COLOR[c.categoria] }} />
                        <Typography variant="caption">{c.categoria}</Typography>
                      </Box>
                      <Typography variant="caption" fontWeight={600}>{formatCurrency(parseFloat(c.total))}</Typography>
                    </Box>
                  ))}
                </CardContent>
              </Card>
            </Grid>
          )}

          {/* Tabla gastos */}
          <Grid item xs={12} md={resumenGastos && parseFloat(resumenGastos.total_bob) > 0 ? 8 : 12}>
            <TableContainer component={Paper}>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ bgcolor: 'grey.100' }}>
                    <TableCell><strong>Fecha</strong></TableCell>
                    <TableCell><strong>Categoría</strong></TableCell>
                    <TableCell><strong>Descripción</strong></TableCell>
                    <TableCell align="right"><strong>Monto</strong></TableCell>
                    <TableCell><strong>Pago</strong></TableCell>
                    <TableCell><strong>Proveedor</strong></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {loading ? (
                    Array.from({ length: 5 }).map((_, i) => (
                      <TableRow key={i}><TableCell colSpan={6}><Skeleton /></TableCell></TableRow>
                    ))
                  ) : gastos.length === 0 ? (
                    <TableRow><TableCell colSpan={6} align="center">
                      <Typography color="text.secondary" py={2}>Sin gastos en el período</Typography>
                    </TableCell></TableRow>
                  ) : gastos.map(g => (
                    <TableRow key={g.id} hover>
                      <TableCell>{g.fecha}</TableCell>
                      <TableCell>
                        <Chip label={g.categoria} size="small"
                          sx={{ bgcolor: CATEGORIA_COLOR[g.categoria] ?? '#757575', color: 'white', fontSize: 10 }} />
                      </TableCell>
                      <TableCell>{g.descripcion}</TableCell>
                      <TableCell align="right">
                        <Typography fontWeight={700} color="error.main">
                          {formatCurrency(parseFloat(g.monto_bob))}
                        </Typography>
                      </TableCell>
                      <TableCell><Chip label={g.medio_pago} size="small" variant="outlined" /></TableCell>
                      <TableCell>{g.proveedor || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Grid>
        </Grid>
      )}

      {/* Tab 3: Snapshots */}
      {tab === 3 && canSnapshot && (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: 'grey.100' }}>
                <TableCell><strong>Fecha</strong></TableCell>
                <TableCell><strong>Tipo</strong></TableCell>
                <TableCell align="right"><strong>Efectivo</strong></TableCell>
                <TableCell align="right"><strong>Divisas</strong></TableCell>
                <TableCell align="right"><strong>Tarjetas</strong></TableCell>
                <TableCell align="right"><strong>Total</strong></TableCell>
                <TableCell><strong>Generado por</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}><TableCell colSpan={7}><Skeleton /></TableCell></TableRow>
                ))
              ) : snapshots.length === 0 ? (
                <TableRow><TableCell colSpan={7} align="center">
                  <Typography color="text.secondary" py={2}>Sin snapshots en el período</Typography>
                </TableCell></TableRow>
              ) : snapshots.map(s => (
                <TableRow key={s.id} hover>
                  <TableCell>{s.fecha}</TableCell>
                  <TableCell>
                    <Chip label={s.tipo} size="small"
                      color={s.tipo === 'CIERRE' ? 'primary' : s.tipo === 'APERTURA' ? 'success' : 'default'} />
                  </TableCell>
                  <TableCell align="right">{formatCurrency(parseFloat(s.efectivo_bob))}</TableCell>
                  <TableCell align="right">{formatCurrency(parseFloat(s.divisas_bob))}</TableCell>
                  <TableCell align="right">{formatCurrency(parseFloat(s.tarjetas_bob))}</TableCell>
                  <TableCell align="right">
                    <Typography fontWeight={700} color="primary">{formatCurrency(parseFloat(s.total_bob))}</Typography>
                  </TableCell>
                  <TableCell>{s.generado_por_nombre}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Tab: Caja Manual */}
      {tab === (canSnapshot ? 4 : 3) && (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <CapitalCaja />
        </Paper>
      )}

      {/* Dialogs */}
      <GastoDialog open={gastoDialog} onClose={() => setGastoDialog(false)} onSuccess={load} />
      <SnapshotDialog open={snapshotDialog} onClose={() => setSnapshotDialog(false)} onSuccess={load} />
    </Box>
  );
};

export default Capital;
