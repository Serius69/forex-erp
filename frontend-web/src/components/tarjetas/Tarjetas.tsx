// src/components/tarjetas/Tarjetas.tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, Chip,
  Table, TableHead, TableBody, TableRow, TableCell, TableContainer,
  Paper, Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, FormControl, InputLabel, Select, MenuItem,
  Tabs, Tab, Skeleton, Alert, IconButton, Tooltip,
  Divider, Badge, LinearProgress,
} from '@mui/material';
import {
  Add, Refresh, CreditCard, ShoppingCart, Sell,
  Inventory2, TrendingUp, AttachMoney,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { NumericFormat } from 'react-number-format';
import { api } from '../../services/api';
import { formatCurrency, formatNumber } from '../../utils/formatters';
import { useAuth } from '../../contexts/AuthContext';
import { useWebSocket } from '../../contexts/WebSocketContext';

// ── Types ────────────────────────────────────────────────────────────────────
interface TipoTarjeta {
  id: number;
  operadora: string;
  nombre: string;
  denominacion: number;
  stock_actual: number;
  costo_promedio: string;
  valor_inventario_bob: string;
  is_active: boolean;
}

interface LoteCompra {
  id: number;
  tipo_tarjeta: number;
  tipo_tarjeta_nombre: string;
  proveedor: string;
  cantidad_total: number;
  cantidad_restante: number;
  precio_costo: string;
  numero_factura: string;
  fecha_compra: string;
  is_active: boolean;
}

interface VentaTarjeta {
  id: number;
  numero_venta: string;
  tipo_tarjeta_nombre: string;
  operadora: string;
  cantidad: number;
  precio_venta: string;
  total_bob: string;
  costo_fifo_bob: string;
  ganancia_bob: string;
  medio_pago: string;
  cliente_nombre: string;
  created_at: string;
}

interface Resumen {
  totales: {
    total_ventas: number;
    total_unidades: number;
    total_ingresos: string;
    total_costo: string;
    total_ganancia: string;
  };
  por_tipo: { tipo_tarjeta__nombre: string; tipo_tarjeta__operadora: string; ventas: number; unidades: number; ingresos: string; ganancia: string }[];
}

// ── Operadora colors ──────────────────────────────────────────────────────────
const OPERADORA_COLOR: Record<string, string> = {
  TIGO: '#00A8E0', VIVA: '#E50914', CLARO: '#DA291C', ENTEL: '#FFB300',
};

// ── Inventario Card ───────────────────────────────────────────────────────────
const InventarioCard = ({ tipo, onCompra, onVenta, canManage }: {
  tipo: TipoTarjeta;
  onCompra: (tipo: TipoTarjeta) => void;
  onVenta: (tipo: TipoTarjeta) => void;
  canManage: boolean;
}) => {
  const color = OPERADORA_COLOR[tipo.operadora] ?? '#607d8b';
  const stockPct = Math.min((tipo.stock_actual / 200) * 100, 100);
  const stockLow = tipo.stock_actual < 20;

  return (
    <Card sx={{ borderTop: `4px solid ${color}`, height: '100%' }}>
      <CardContent>
        <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={1}>
          <Box>
            <Chip label={tipo.operadora} size="small"
              sx={{ bgcolor: color, color: 'white', fontWeight: 700, mb: 0.5 }} />
            <Typography variant="h6" fontWeight={700}>{tipo.nombre}</Typography>
            <Typography variant="caption" color="text.secondary">
              Bs. {formatNumber(tipo.denominacion)} c/u
            </Typography>
          </Box>
          <Box textAlign="right">
            <Typography variant="h4" fontWeight={800}
              color={stockLow ? 'error.main' : 'text.primary'}>
              {tipo.stock_actual}
            </Typography>
            <Typography variant="caption" color="text.secondary">en stock</Typography>
          </Box>
        </Box>

        <LinearProgress variant="determinate" value={stockPct}
          color={stockLow ? 'error' : 'success'}
          sx={{ mb: 1.5, height: 6, borderRadius: 3 }} />

        <Box display="flex" justifyContent="space-between" mb={2}>
          <Box>
            <Typography variant="caption" color="text.secondary">Costo prom.</Typography>
            <Typography variant="body2" fontWeight={600}>
              Bs. {parseFloat(tipo.costo_promedio || '0').toFixed(2)}
            </Typography>
          </Box>
          <Box textAlign="right">
            <Typography variant="caption" color="text.secondary">Valor inv.</Typography>
            <Typography variant="body2" fontWeight={600} color="primary">
              {formatCurrency(parseFloat(tipo.valor_inventario_bob || '0'))}
            </Typography>
          </Box>
        </Box>

        <Box display="flex" gap={1}>
          {canManage && (
            <Button fullWidth size="small" variant="outlined" startIcon={<ShoppingCart />}
              onClick={() => onCompra(tipo)}>
              Comprar
            </Button>
          )}
          <Button fullWidth size="small" variant="contained" startIcon={<Sell />}
            onClick={() => onVenta(tipo)}
            disabled={tipo.stock_actual === 0}
            color={stockLow ? 'warning' : 'primary'}>
            Vender
          </Button>
        </Box>
      </CardContent>
    </Card>
  );
};

// ── Dialog: Registrar Lote de Compra ─────────────────────────────────────────
const LoteDialog = ({ open, tipo, onClose, onSuccess }: {
  open: boolean; tipo: TipoTarjeta | null;
  onClose: () => void; onSuccess: () => void;
}) => {
  const [form, setForm] = useState({ cantidad: '', precio_costo: '', proveedor: '', numero_factura: '', fecha_compra: '' });
  const [loading, setLoading] = useState(false);
  const { enqueueSnackbar } = useSnackbar();

  useEffect(() => {
    if (open) setForm({ cantidad: '', precio_costo: '', proveedor: '', numero_factura: '', fecha_compra: new Date().toISOString().split('T')[0] });
  }, [open]);

  const submit = async () => {
    if (!tipo || !form.cantidad || !form.precio_costo) return;
    setLoading(true);
    try {
      await api.post(`/tarjetas/tipos/${tipo.id}/registrar-lote/`, {
        cantidad: parseInt(form.cantidad),
        precio_costo: parseFloat(form.precio_costo),
        proveedor: form.proveedor || 'Proveedor',
        numero_factura: form.numero_factura,
        fecha_compra: form.fecha_compra,
      });
      enqueueSnackbar('Lote registrado correctamente', { variant: 'success' });
      onSuccess();
      onClose();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al registrar lote', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const total = (parseInt(form.cantidad || '0') * parseFloat(form.precio_costo || '0'));

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <ShoppingCart color="primary" />
          Registrar Lote de Compra — {tipo?.nombre}
        </Box>
      </DialogTitle>
      <DialogContent>
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Grid item xs={6}>
            <TextField fullWidth label="Cantidad" type="number" value={form.cantidad}
              onChange={e => setForm(p => ({ ...p, cantidad: e.target.value }))}
              inputProps={{ min: 1 }} required />
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="Precio costo (Bs.)" type="number" value={form.precio_costo}
              onChange={e => setForm(p => ({ ...p, precio_costo: e.target.value }))}
              inputProps={{ min: 0.01, step: 0.01 }} required />
          </Grid>
          <Grid item xs={12}>
            <TextField fullWidth label="Proveedor" value={form.proveedor}
              onChange={e => setForm(p => ({ ...p, proveedor: e.target.value }))} />
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="N° Factura" value={form.numero_factura}
              onChange={e => setForm(p => ({ ...p, numero_factura: e.target.value }))} />
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="Fecha Compra" type="date" value={form.fecha_compra}
              onChange={e => setForm(p => ({ ...p, fecha_compra: e.target.value }))}
              InputLabelProps={{ shrink: true }} />
          </Grid>
          {total > 0 && (
            <Grid item xs={12}>
              <Paper sx={{ p: 2, bgcolor: 'primary.50' }}>
                <Typography align="center" fontWeight={700}>
                  Total inversión: {formatCurrency(total)}
                </Typography>
              </Paper>
            </Grid>
          )}
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" onClick={submit} disabled={loading || !form.cantidad || !form.precio_costo}>
          Registrar Lote
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// ── Dialog: Vender Tarjetas ──────────────────────────────────────────────────
const VentaDialog = ({ open, tipo, onClose, onSuccess }: {
  open: boolean; tipo: TipoTarjeta | null;
  onClose: () => void; onSuccess: () => void;
}) => {
  const [form, setForm] = useState({ cantidad: 1, precio_venta: '', medio_pago: 'CASH', cliente_nombre: '', cliente_tel: '' });
  const [loading, setLoading] = useState(false);
  const { enqueueSnackbar } = useSnackbar();

  useEffect(() => {
    if (open && tipo) {
      setForm({ cantidad: 1, precio_venta: tipo.denominacion.toString(), medio_pago: 'CASH', cliente_nombre: '', cliente_tel: '' });
    }
  }, [open, tipo]);

  const submit = async () => {
    if (!tipo) return;
    setLoading(true);
    try {
      await api.post(`/tarjetas/tipos/${tipo.id}/vender/`, {
        cantidad: form.cantidad,
        precio_venta: parseFloat(form.precio_venta),
        medio_pago: form.medio_pago,
        cliente_nombre: form.cliente_nombre,
        cliente_tel: form.cliente_tel,
      });
      enqueueSnackbar('Venta registrada correctamente', { variant: 'success' });
      onSuccess();
      onClose();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al registrar venta', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const total = form.cantidad * parseFloat(form.precio_venta || '0');
  const costo = form.cantidad * parseFloat(tipo?.costo_promedio || '0');
  const ganancia = total - costo;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <Sell color="success" />
          Vender Tarjetas — {tipo?.nombre}
        </Box>
      </DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>
          Stock disponible: <strong>{tipo?.stock_actual}</strong> unidades
        </Alert>
        <Grid container spacing={2}>
          <Grid item xs={6}>
            <TextField fullWidth label="Cantidad" type="number" value={form.cantidad}
              onChange={e => setForm(p => ({ ...p, cantidad: Math.min(parseInt(e.target.value) || 1, tipo?.stock_actual ?? 999) }))}
              inputProps={{ min: 1, max: tipo?.stock_actual }} />
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="Precio venta (Bs.)" type="number" value={form.precio_venta}
              onChange={e => setForm(p => ({ ...p, precio_venta: e.target.value }))}
              inputProps={{ min: 0.01, step: 0.01 }} />
          </Grid>
          <Grid item xs={12}>
            <FormControl fullWidth>
              <InputLabel>Medio de Pago</InputLabel>
              <Select value={form.medio_pago} label="Medio de Pago"
                onChange={e => setForm(p => ({ ...p, medio_pago: e.target.value }))}>
                <MenuItem value="CASH">Efectivo</MenuItem>
                <MenuItem value="QR">QR</MenuItem>
                <MenuItem value="TRANSFER">Transferencia</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="Nombre cliente (Opcional)" value={form.cliente_nombre}
              onChange={e => setForm(p => ({ ...p, cliente_nombre: e.target.value }))} />
          </Grid>
          <Grid item xs={6}>
            <TextField fullWidth label="Teléfono (Opcional)" value={form.cliente_tel}
              onChange={e => setForm(p => ({ ...p, cliente_tel: e.target.value }))} />
          </Grid>

          {total > 0 && (
            <Grid item xs={12}>
              <Paper sx={{ p: 2 }}>
                <Box display="flex" justifyContent="space-between" mb={0.5}>
                  <Typography variant="body2" color="text.secondary">Total venta</Typography>
                  <Typography variant="body2" fontWeight={700}>{formatCurrency(total)}</Typography>
                </Box>
                <Box display="flex" justifyContent="space-between" mb={0.5}>
                  <Typography variant="body2" color="text.secondary">Costo FIFO</Typography>
                  <Typography variant="body2" color="error.main">- {formatCurrency(costo)}</Typography>
                </Box>
                <Divider sx={{ my: 0.5 }} />
                <Box display="flex" justifyContent="space-between">
                  <Typography fontWeight={700}>Ganancia estimada</Typography>
                  <Typography fontWeight={700} color={ganancia >= 0 ? 'success.main' : 'error.main'}>
                    {formatCurrency(ganancia)}
                  </Typography>
                </Box>
              </Paper>
            </Grid>
          )}
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" color="success" onClick={submit}
          disabled={loading || !form.precio_venta || form.cantidad < 1}>
          Confirmar Venta
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────
const Tarjetas: React.FC = () => {
  const [tab, setTab] = useState(0);
  const [tipos, setTipos] = useState<TipoTarjeta[]>([]);
  const [lotes, setLotes] = useState<LoteCompra[]>([]);
  const [ventas, setVentas] = useState<VentaTarjeta[]>([]);
  const [resumen, setResumen] = useState<Resumen | null>(null);
  const [loading, setLoading] = useState(true);
  const [loteDialog, setLoteDialog] = useState<TipoTarjeta | null>(null);
  const [ventaDialog, setVentaDialog] = useState<TipoTarjeta | null>(null);
  const [dateFrom] = useState(new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0]);
  const [dateTo] = useState(new Date().toISOString().split('T')[0]);
  const { user } = useAuth();
  const { enqueueSnackbar } = useSnackbar();
  const { lastSheetsSync } = useWebSocket();

  const canManage = user?.role === 'ADMIN' || user?.role === 'SUPERVISOR';

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tiposRes, lotesRes, ventasRes, resumenRes] = await Promise.all([
        api.get('/tarjetas/tipos/inventario/'),
        api.get('/tarjetas/lotes/', { params: { activos: 'true' } }),
        api.get('/tarjetas/ventas/', { params: { date_from: dateFrom, date_to: dateTo } }),
        api.get('/tarjetas/ventas/resumen/', { params: { date_from: dateFrom, date_to: dateTo } }),
      ]);
      setTipos(tiposRes.data);
      setLotes(lotesRes.data?.results ?? lotesRes.data ?? []);
      setVentas(ventasRes.data?.results ?? ventasRes.data ?? []);
      setResumen(resumenRes.data);
    } catch (e) {
      enqueueSnackbar('Error al cargar módulo de tarjetas', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  // Google Sheets sync completed → reload inventory.
  useEffect(() => {
    if (!lastSheetsSync) return;
    load();
  }, [lastSheetsSync, load]);

  const totalStock = tipos.reduce((s, t) => s + t.stock_actual, 0);
  const totalValor = tipos.reduce((s, t) => s + parseFloat(t.valor_inventario_bob || '0'), 0);

  return (
    <Box>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={800}>Tarjetas de Recarga</Typography>
          <Typography variant="body2" color="text.secondary">
            Gestión de inventario y ventas de tarjetas telefónicas
          </Typography>
        </Box>
        <Tooltip title="Actualizar">
          <IconButton onClick={load}><Refresh /></IconButton>
        </Tooltip>
      </Box>

      {/* KPI strip */}
      <Grid container spacing={2} mb={3}>
        {[
          { label: 'Stock Total', value: formatNumber(totalStock) + ' uds.', icon: <Inventory2 />, color: '#1976d2' },
          { label: 'Valor Inventario', value: formatCurrency(totalValor), icon: <AttachMoney />, color: '#2e7d32' },
          { label: 'Ventas del Mes', value: formatNumber(resumen?.totales?.total_ventas ?? 0), icon: <Sell />, color: '#e65100' },
          { label: 'Ganancia del Mes', value: formatCurrency(parseFloat(resumen?.totales?.total_ganancia || '0')), icon: <TrendingUp />, color: '#7b1fa2' },
        ].map(k => (
          <Grid item key={k.label} xs={6} md={3}>
            <Card sx={{ borderTop: `3px solid ${k.color}` }}>
              <CardContent sx={{ py: 1.5 }}>
                <Box display="flex" justifyContent="space-between" alignItems="center">
                  <Box>
                    <Typography variant="caption" color="text.secondary" textTransform="uppercase">{k.label}</Typography>
                    {loading ? <Skeleton width={80} /> : (
                      <Typography variant="h6" fontWeight={700} sx={{ color: k.color }}>{k.value}</Typography>
                    )}
                  </Box>
                  <Box sx={{ color: k.color, opacity: 0.7 }}>{k.icon}</Box>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3 }}>
        <Tab icon={<CreditCard />} iconPosition="start" label="Inventario" />
        <Tab icon={<ShoppingCart />} iconPosition="start" label="Lotes de Compra" />
        <Tab icon={<Sell />} iconPosition="start" label="Ventas" />
      </Tabs>

      {/* Tab 0: Inventario */}
      {tab === 0 && (
        <Grid container spacing={2}>
          {loading ? Array.from({ length: 4 }).map((_, i) => (
            <Grid item key={i} xs={12} sm={6} md={3}>
              <Skeleton variant="rectangular" height={200} sx={{ borderRadius: 2 }} />
            </Grid>
          )) : tipos.length === 0 ? (
            <Grid item xs={12}>
              <Alert severity="info">No hay tipos de tarjeta configurados.</Alert>
            </Grid>
          ) : tipos.map(tipo => (
            <Grid item key={tipo.id} xs={12} sm={6} md={3}>
              <InventarioCard
                tipo={tipo}
                canManage={canManage}
                onCompra={() => setLoteDialog(tipo)}
                onVenta={() => setVentaDialog(tipo)}
              />
            </Grid>
          ))}
        </Grid>
      )}

      {/* Tab 1: Lotes */}
      {tab === 1 && (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: 'grey.100' }}>
                <TableCell><strong>Tipo</strong></TableCell>
                <TableCell><strong>Proveedor</strong></TableCell>
                <TableCell align="center"><strong>Total</strong></TableCell>
                <TableCell align="center"><strong>Disponible</strong></TableCell>
                <TableCell align="right"><strong>Costo unit.</strong></TableCell>
                <TableCell><strong>Factura</strong></TableCell>
                <TableCell><strong>Fecha</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}><TableCell colSpan={7}><Skeleton /></TableCell></TableRow>
                ))
              ) : lotes.length === 0 ? (
                <TableRow><TableCell colSpan={7} align="center">
                  <Typography color="text.secondary" py={2}>Sin lotes activos</Typography>
                </TableCell></TableRow>
              ) : lotes.map(l => (
                <TableRow key={l.id} hover>
                  <TableCell>{l.tipo_tarjeta_nombre}</TableCell>
                  <TableCell>{l.proveedor}</TableCell>
                  <TableCell align="center">{l.cantidad_total}</TableCell>
                  <TableCell align="center">
                    <Chip label={l.cantidad_restante} size="small"
                      color={l.cantidad_restante < 10 ? 'warning' : 'default'} />
                  </TableCell>
                  <TableCell align="right">Bs. {parseFloat(l.precio_costo).toFixed(2)}</TableCell>
                  <TableCell>{l.numero_factura || '—'}</TableCell>
                  <TableCell>{l.fecha_compra}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Tab 2: Ventas */}
      {tab === 2 && (
        <>
          {resumen && (
            <Paper sx={{ p: 2, mb: 2 }}>
              <Typography fontWeight={700} mb={1}>Resumen del período ({dateFrom} → {dateTo})</Typography>
              <Grid container spacing={2}>
                {resumen.por_tipo.map(pt => (
                  <Grid item key={pt.tipo_tarjeta__nombre} xs={6} sm={3}>
                    <Box textAlign="center" p={1} border="1px solid" borderColor="divider" borderRadius={1}>
                      <Typography variant="caption" color="text.secondary">{pt.tipo_tarjeta__nombre}</Typography>
                      <Typography fontWeight={700}>{pt.unidades} uds.</Typography>
                      <Typography variant="caption" color="success.main">+{formatCurrency(parseFloat(pt.ganancia))}</Typography>
                    </Box>
                  </Grid>
                ))}
              </Grid>
            </Paper>
          )}
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow sx={{ bgcolor: 'grey.100' }}>
                  <TableCell><strong>N° Venta</strong></TableCell>
                  <TableCell><strong>Tipo</strong></TableCell>
                  <TableCell align="center"><strong>Cant.</strong></TableCell>
                  <TableCell align="right"><strong>Precio</strong></TableCell>
                  <TableCell align="right"><strong>Total</strong></TableCell>
                  <TableCell align="right"><strong>Ganancia</strong></TableCell>
                  <TableCell><strong>Pago</strong></TableCell>
                  <TableCell><strong>Cliente</strong></TableCell>
                  <TableCell><strong>Hora</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i}><TableCell colSpan={9}><Skeleton /></TableCell></TableRow>
                  ))
                ) : ventas.length === 0 ? (
                  <TableRow><TableCell colSpan={9} align="center">
                    <Typography color="text.secondary" py={2}>Sin ventas en el período</Typography>
                  </TableCell></TableRow>
                ) : ventas.map(v => (
                  <TableRow key={v.id} hover>
                    <TableCell><Typography variant="caption" fontFamily="monospace">{v.numero_venta}</Typography></TableCell>
                    <TableCell>
                      <Chip label={v.tipo_tarjeta_nombre} size="small"
                        sx={{ bgcolor: OPERADORA_COLOR[v.operadora] ?? '#607d8b', color: 'white' }} />
                    </TableCell>
                    <TableCell align="center">{v.cantidad}</TableCell>
                    <TableCell align="right">Bs. {parseFloat(v.precio_venta).toFixed(2)}</TableCell>
                    <TableCell align="right"><strong>{formatCurrency(parseFloat(v.total_bob))}</strong></TableCell>
                    <TableCell align="right">
                      <Typography color="success.main" fontWeight={700}>
                        {formatCurrency(parseFloat(v.ganancia_bob))}
                      </Typography>
                    </TableCell>
                    <TableCell><Chip label={v.medio_pago} size="small" variant="outlined" /></TableCell>
                    <TableCell>{v.cliente_nombre || '—'}</TableCell>
                    <TableCell>
                      <Typography variant="caption">
                        {new Date(v.created_at).toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' })}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}

      {/* Dialogs */}
      <LoteDialog open={!!loteDialog} tipo={loteDialog} onClose={() => setLoteDialog(null)} onSuccess={load} />
      <VentaDialog open={!!ventaDialog} tipo={ventaDialog} onClose={() => setVentaDialog(null)} onSuccess={load} />
    </Box>
  );
};

export default Tarjetas;
