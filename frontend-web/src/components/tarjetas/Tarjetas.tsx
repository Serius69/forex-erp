// src/components/tarjetas/Tarjetas.tsx
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, Chip,
  Table, TableHead, TableBody, TableRow, TableCell, TableContainer,
  Paper, Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, FormControl, InputLabel, Select, MenuItem,
  Tabs, Tab, Skeleton, Alert, IconButton, Tooltip,
  Divider, Badge, LinearProgress, Drawer, CircularProgress,
} from '@mui/material';
import {
  Add, Refresh, CreditCard, ShoppingCart, Sell,
  Inventory2, TrendingUp, AttachMoney, Warning, Cancel,
  WifiOff, Wifi,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatCurrency, formatNumber } from '../../utils/formatters';
import { useAuth } from '../../contexts/AuthContext';

// ── Types ─────────────────────────────────────────────────────────────────────

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
  estado: string;
  created_at: string;
}

interface PosicionItem {
  id: number;
  nombre: string;
  operadora: string;
  denominacion: string;
  stock: number;
  lotes_activos: number;
  costo_promedio: string;
  valor_costo_bob: string;
  valor_venta_bob: string;
  margen_potencial: string;
  estado_stock: 'ok' | 'bajo' | 'critico';
  stock_minimo: number | null;
  stock_critico: number | null;
}

interface KPIs {
  inventario: {
    total_tipos: number;
    total_unidades: number;
    valor_costo_bob: string;
    valor_venta_bob: string;
    margen_potencial: string;
  };
  mes: {
    desde: string;
    hasta: string;
    total_ventas: number;
    total_unidades: number;
    ingresos_bob: string;
    ganancia_bob: string;
  };
  alertas_activas: number;
}

// ── Operadora colors ───────────────────────────────────────────────────────────

const OPERADORA_COLOR: Record<string, string> = {
  TIGO: '#00A8E0', VIVA: '#E50914', CLARO: '#DA291C', ENTEL: '#FFB300',
};

// ── Custom WS hook para inventario de tarjetas ────────────────────────────────

function useTarjetasWS(onUpdate: (data: { items: PosicionItem[] }) => void) {
  const [connected, setConnected] = useState(false);
  const wsRef   = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attempts = useRef(0);
  const { user } = useAuth();

  const connect = useCallback(() => {
    if (!user) return;
    const token = localStorage.getItem('access_token') || sessionStorage.getItem('access_token') || '';
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const base  = import.meta.env.VITE_WS_BASE_URL || `${proto}://${window.location.host}`;
    const url   = `${base}/ws/tarjetas/inventario/?token=${token}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      attempts.current = 0;
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'inventario_snapshot' || msg.type === 'inventario_update') {
          onUpdate(msg.data);
        }
      } catch { /* ignore malformed */ }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Reconexión exponencial con cap de 30 s
      const delay = Math.min(1000 * 2 ** attempts.current, 30_000);
      attempts.current += 1;
      retryRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => ws.close();
  }, [user, onUpdate]);

  useEffect(() => {
    connect();
    return () => {
      if (retryRef.current) clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return connected;
}

// ── InventarioRow — con flash animation al cambiar stock ──────────────────────

const InventarioRow = React.memo(({ item, prevStock, onCompra, onVenta, canManage }: {
  item: PosicionItem;
  prevStock: number | undefined;
  onCompra: () => void;
  onVenta: () => void;
  canManage: boolean;
}) => {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const color = OPERADORA_COLOR[item.operadora] ?? '#607d8b';

  useEffect(() => {
    if (prevStock === undefined || prevStock === item.stock) return;
    const dir = item.stock > prevStock ? 'up' : 'down';
    setFlash(dir);
    const t = setTimeout(() => setFlash(null), 1200);
    return () => clearTimeout(t);
  }, [item.stock, prevStock]);

  const stockPct   = Math.min((item.stock / Math.max(item.stock_minimo ?? 100, 1)) * 100, 100);
  const estadoColor = item.estado_stock === 'critico' ? 'error'
    : item.estado_stock === 'bajo' ? 'warning' : 'success';

  const flashBg = flash === 'up'   ? 'rgba(46,125,50,0.12)'
    : flash === 'down' ? 'rgba(211,47,47,0.12)' : 'transparent';

  return (
    <TableRow hover sx={{ transition: 'background 0.4s', bgcolor: flashBg }}>
      <TableCell>
        <Chip label={item.operadora} size="small"
          sx={{ bgcolor: color, color: 'white', fontWeight: 700 }} />
      </TableCell>
      <TableCell><Typography fontWeight={600}>{item.nombre}</Typography></TableCell>
      <TableCell align="right">Bs. {parseFloat(item.denominacion).toFixed(2)}</TableCell>
      <TableCell align="center">
        <Box>
          <Typography fontWeight={700}
            color={item.estado_stock === 'critico' ? 'error.main'
              : item.estado_stock === 'bajo' ? 'warning.main' : 'text.primary'}>
            {item.stock}
          </Typography>
          <LinearProgress variant="determinate" value={stockPct}
            color={estadoColor} sx={{ height: 4, borderRadius: 2, mt: 0.5 }} />
        </Box>
      </TableCell>
      <TableCell align="right">Bs. {parseFloat(item.costo_promedio).toFixed(2)}</TableCell>
      <TableCell align="right">{formatCurrency(parseFloat(item.valor_costo_bob))}</TableCell>
      <TableCell align="right">{formatCurrency(parseFloat(item.valor_venta_bob))}</TableCell>
      <TableCell align="right">
        <Typography color="success.main" fontWeight={600}>
          {formatCurrency(parseFloat(item.margen_potencial))}
        </Typography>
      </TableCell>
      <TableCell>
        <Chip size="small"
          label={item.estado_stock === 'critico' ? 'Crítico'
            : item.estado_stock === 'bajo' ? 'Bajo' : 'OK'}
          color={estadoColor} />
      </TableCell>
      <TableCell>
        <Box display="flex" gap={0.5}>
          {canManage && (
            <Button size="small" variant="outlined" onClick={onCompra}
              startIcon={<ShoppingCart fontSize="small" />}>Comprar</Button>
          )}
          <Button size="small" variant="contained" onClick={onVenta}
            disabled={item.stock === 0} color={item.estado_stock !== 'ok' ? 'warning' : 'primary'}
            startIcon={<Sell fontSize="small" />}>Vender</Button>
        </Box>
      </TableCell>
    </TableRow>
  );
}, (prev, next) =>
  prev.item.stock === next.item.stock &&
  prev.item.estado_stock === next.item.estado_stock &&
  prev.canManage === next.canManage
);

// ── Dialog: Registrar Lote de Compra ──────────────────────────────────────────

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

  const cant   = parseInt(form.cantidad || '0');
  const costo  = parseFloat(form.precio_costo || '0');
  const total  = cant * costo;
  const margen = tipo ? (tipo.denominacion - costo) / tipo.denominacion * 100 : 0;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <ShoppingCart color="primary" />
          Registrar Lote — {tipo?.nombre}
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
                <Box display="flex" justifyContent="space-between">
                  <Typography fontWeight={700}>Total inversión</Typography>
                  <Typography fontWeight={700}>{formatCurrency(total)}</Typography>
                </Box>
                {tipo && costo > 0 && (
                  <Box display="flex" justifyContent="space-between" mt={0.5}>
                    <Typography variant="caption" color="text.secondary">Margen estimado</Typography>
                    <Typography variant="caption" color={margen > 0 ? 'success.main' : 'error.main'}>
                      {margen.toFixed(1)}%
                    </Typography>
                  </Box>
                )}
              </Paper>
            </Grid>
          )}
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" onClick={submit} disabled={loading || !form.cantidad || !form.precio_costo}>
          {loading ? <CircularProgress size={20} /> : 'Registrar Lote'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// ── Dialog: Vender Tarjetas ───────────────────────────────────────────────────

const VentaDialog = ({ open, tipo, onClose, onSuccess }: {
  open: boolean; tipo: TipoTarjeta | null;
  onClose: () => void; onSuccess: () => void;
}) => {
  const [form, setForm] = useState({ cantidad: 1, precio_venta: '', medio_pago: 'CASH', cliente_nombre: '', cliente_tel: '' });
  const [ventaResult, setVentaResult] = useState<{ numero_venta: string; ganancia_bob: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const { enqueueSnackbar } = useSnackbar();

  useEffect(() => {
    if (open && tipo) {
      setForm({ cantidad: 1, precio_venta: tipo.denominacion.toString(), medio_pago: 'CASH', cliente_nombre: '', cliente_tel: '' });
      setVentaResult(null);
    }
  }, [open, tipo]);

  const submit = async () => {
    if (!tipo) return;
    setLoading(true);
    try {
      const res = await api.post(`/tarjetas/tipos/${tipo.id}/vender/`, {
        cantidad: form.cantidad,
        precio_venta: parseFloat(form.precio_venta),
        medio_pago: form.medio_pago,
        cliente_nombre: form.cliente_nombre,
        cliente_tel: form.cliente_tel,
      });
      setVentaResult({ numero_venta: res.data.numero_venta, ganancia_bob: res.data.ganancia_bob });
      enqueueSnackbar(`Venta ${res.data.numero_venta} registrada`, { variant: 'success' });
      onSuccess();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al registrar venta', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const total   = form.cantidad * parseFloat(form.precio_venta || '0');
  const costo   = form.cantidad * parseFloat(tipo?.costo_promedio || '0');
  const ganancia = total - costo;

  if (ventaResult) {
    return (
      <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
        <DialogTitle>Venta Registrada</DialogTitle>
        <DialogContent>
          <Box textAlign="center" py={2}>
            <Typography variant="h6" fontFamily="monospace">{ventaResult.numero_venta}</Typography>
            <Typography color="text.secondary" mt={1}>Ganancia</Typography>
            <Typography variant="h4" fontWeight={800} color="success.main">
              {formatCurrency(parseFloat(ventaResult.ganancia_bob))}
            </Typography>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button variant="contained" onClick={onClose}>Cerrar</Button>
        </DialogActions>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <Sell color="success" />
          Vender — {tipo?.nombre}
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
                  <Typography variant="body2" color="text.secondary">Costo FIFO (estimado)</Typography>
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
          {loading ? <CircularProgress size={20} /> : 'Confirmar Venta'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// ── Dialog: Anular Venta ──────────────────────────────────────────────────────

const AnularDialog = ({ open, venta, onClose, onSuccess }: {
  open: boolean; venta: VentaTarjeta | null;
  onClose: () => void; onSuccess: () => void;
}) => {
  const [motivo, setMotivo] = useState('');
  const [loading, setLoading] = useState(false);
  const { enqueueSnackbar } = useSnackbar();

  useEffect(() => { if (open) setMotivo(''); }, [open]);

  const submit = async () => {
    if (!venta || !motivo.trim()) return;
    setLoading(true);
    try {
      await api.post(`/tarjetas/ventas/${venta.id}/anular/`, { motivo });
      enqueueSnackbar('Venta anulada correctamente', { variant: 'success' });
      onSuccess();
      onClose();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al anular venta', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <Cancel color="error" /> Anular Venta
        </Box>
      </DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" mb={2}>
          Venta: <strong>{venta?.numero_venta}</strong> — {venta?.tipo_tarjeta_nombre} × {venta?.cantidad}
        </Typography>
        <TextField fullWidth multiline rows={3} label="Motivo de anulación" required
          value={motivo} onChange={e => setMotivo(e.target.value)} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" color="error" onClick={submit}
          disabled={loading || !motivo.trim()}>
          {loading ? <CircularProgress size={20} /> : 'Anular Venta'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// ── Main Component ─────────────────────────────────────────────────────────────

const Tarjetas: React.FC = () => {
  const [tab, setTab] = useState(0);

  // REST data
  const [tipos, setTipos]   = useState<TipoTarjeta[]>([]);
  const [lotes, setLotes]   = useState<LoteCompra[]>([]);
  const [ventas, setVentas] = useState<VentaTarjeta[]>([]);
  const [kpis, setKpis]     = useState<KPIs | null>(null);
  const [loading, setLoading] = useState(true);

  // WS-driven posición de inventario (tabla en tiempo real)
  const [posicion, setPosicion]     = useState<PosicionItem[]>([]);
  const [prevStocks, setPrevStocks] = useState<Record<number, number>>({});

  // Dialogs
  const [loteDialog,   setLoteDialog]   = useState<TipoTarjeta | null>(null);
  const [ventaDialog,  setVentaDialog]  = useState<TipoTarjeta | null>(null);
  const [anularDialog, setAnularDialog] = useState<VentaTarjeta | null>(null);

  const [dateFrom] = useState(new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0]);
  const [dateTo]   = useState(new Date().toISOString().split('T')[0]);

  const { user } = useAuth();
  const { enqueueSnackbar } = useSnackbar();
  const canManage = user?.role === 'ADMIN' || user?.role === 'SUPERVISOR';

  // WS callback — actualiza posición y anima fila cambiada
  const handleWsUpdate = useCallback((data: { items: PosicionItem[] }) => {
    if (!data?.items) return;
    setPosicion(prev => {
      const stocks: Record<number, number> = {};
      prev.forEach(it => { stocks[it.id] = it.stock; });
      setPrevStocks(stocks);
      return data.items;
    });
  }, []);

  const wsConnected = useTarjetasWS(handleWsUpdate);

  // REST data load
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tiposRes, lotesRes, ventasRes, kpisRes] = await Promise.all([
        api.get('/tarjetas/tipos/inventario/'),
        api.get('/tarjetas/lotes/', { params: { activos: 'true' } }),
        api.get('/tarjetas/ventas/', { params: { date_from: dateFrom, date_to: dateTo } }),
        api.get('/tarjetas/inventario/kpis/'),
      ]);
      setTipos(tiposRes.data);
      setLotes(lotesRes.data?.results ?? lotesRes.data ?? []);
      setVentas(ventasRes.data?.results ?? ventasRes.data ?? []);
      setKpis(kpisRes.data);
      // Inicializar posición desde REST si el WS aún no conectó
      if (posicion.length === 0) {
        const posRes = await api.get('/tarjetas/inventario/posicion/');
        setPosicion(posRes.data?.items ?? []);
      }
    } catch {
      enqueueSnackbar('Error al cargar módulo de tarjetas', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, enqueueSnackbar, posicion.length]);

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Usar posición WS para KPIs de inventario cuando esté disponible
  const totalStock = posicion.length
    ? posicion.reduce((s, it) => s + it.stock, 0)
    : tipos.reduce((s, t) => s + t.stock_actual, 0);

  const totalValorCosto = posicion.length
    ? posicion.reduce((s, it) => s + parseFloat(it.valor_costo_bob), 0)
    : tipos.reduce((s, t) => s + parseFloat(t.valor_inventario_bob || '0'), 0);

  const alertasCount = kpis?.alertas_activas
    ?? posicion.filter(it => it.estado_stock !== 'ok').length;

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
        <Box display="flex" alignItems="center" gap={1}>
          <Tooltip title={wsConnected ? 'Tiempo real activo' : 'Reconectando...'}>
            <Box display="flex" alignItems="center" gap={0.5}>
              {wsConnected
                ? <Wifi fontSize="small" color="success" />
                : <WifiOff fontSize="small" color="disabled" />}
              <Typography variant="caption" color={wsConnected ? 'success.main' : 'text.disabled'}>
                {wsConnected ? 'En vivo' : 'Offline'}
              </Typography>
            </Box>
          </Tooltip>
          <Tooltip title="Actualizar">
            <IconButton onClick={load}><Refresh /></IconButton>
          </Tooltip>
        </Box>
      </Box>

      {/* KPI strip */}
      <Grid container spacing={2} mb={3}>
        {[
          {
            label: 'Stock Total', icon: <Inventory2 />, color: '#1976d2',
            value: loading ? null : `${formatNumber(totalStock)} uds.`,
          },
          {
            label: 'Valor Inventario', icon: <AttachMoney />, color: '#2e7d32',
            value: loading ? null : formatCurrency(totalValorCosto),
          },
          {
            label: 'Ventas del Mes', icon: <Sell />, color: '#e65100',
            value: loading ? null : formatNumber(kpis?.mes?.total_ventas ?? 0),
          },
          {
            label: 'Ganancia del Mes', icon: <TrendingUp />, color: '#7b1fa2',
            value: loading ? null : formatCurrency(parseFloat(kpis?.mes?.ganancia_bob || '0')),
          },
          {
            label: 'Alertas Activas', icon: <Warning />, color: alertasCount > 0 ? '#d32f2f' : '#757575',
            value: loading ? null : String(alertasCount),
          },
        ].map(k => (
          <Grid item key={k.label} xs={6} md={12 / 5}>
            <Card sx={{ borderTop: `3px solid ${k.color}` }}>
              <CardContent sx={{ py: 1.5 }}>
                <Box display="flex" justifyContent="space-between" alignItems="center">
                  <Box>
                    <Typography variant="caption" color="text.secondary" textTransform="uppercase">{k.label}</Typography>
                    {k.value === null
                      ? <Skeleton width={80} />
                      : <Typography variant="h6" fontWeight={700} sx={{ color: k.color }}>{k.value}</Typography>}
                  </Box>
                  <Box sx={{ color: k.color, opacity: 0.7 }}>{k.icon}</Box>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3 }}>
        <Tab icon={<CreditCard />} iconPosition="start" label="Inventario en Vivo" />
        <Tab icon={<ShoppingCart />} iconPosition="start" label="Lotes de Compra" />
        <Tab icon={<Sell />} iconPosition="start"
          label={<Badge badgeContent={alertasCount > 0 ? alertasCount : 0} color="error">Ventas</Badge>} />
      </Tabs>

      {/* Tab 0: Inventario en tiempo real (tabla con flash) */}
      {tab === 0 && (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: 'grey.100' }}>
                <TableCell><strong>Operadora</strong></TableCell>
                <TableCell><strong>Tipo</strong></TableCell>
                <TableCell align="right"><strong>Denominación</strong></TableCell>
                <TableCell align="center"><strong>Stock</strong></TableCell>
                <TableCell align="right"><strong>Costo prom.</strong></TableCell>
                <TableCell align="right"><strong>Valor costo</strong></TableCell>
                <TableCell align="right"><strong>Valor venta</strong></TableCell>
                <TableCell align="right"><strong>Margen</strong></TableCell>
                <TableCell><strong>Estado</strong></TableCell>
                <TableCell><strong>Acciones</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading && posicion.length === 0
                ? Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i}><TableCell colSpan={10}><Skeleton /></TableCell></TableRow>
                  ))
                : posicion.length === 0
                  ? (
                    <TableRow>
                      <TableCell colSpan={10} align="center">
                        <Typography color="text.secondary" py={2}>Sin datos de inventario</Typography>
                      </TableCell>
                    </TableRow>
                  )
                  : posicion.map(item => (
                    <InventarioRow
                      key={item.id}
                      item={item}
                      prevStock={prevStocks[item.id]}
                      canManage={canManage}
                      onCompra={() => {
                        const tipo = tipos.find(t => t.id === item.id);
                        if (tipo) setLoteDialog(tipo);
                      }}
                      onVenta={() => {
                        const tipo = tipos.find(t => t.id === item.id);
                        if (tipo) setVentaDialog(tipo);
                        else setVentaDialog({ id: item.id, operadora: item.operadora, nombre: item.nombre,
                          denominacion: parseFloat(item.denominacion), stock_actual: item.stock,
                          costo_promedio: item.costo_promedio, valor_inventario_bob: item.valor_costo_bob,
                          is_active: true });
                      }}
                    />
                  ))
              }
            </TableBody>
          </Table>
        </TableContainer>
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
              {loading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i}><TableCell colSpan={7}><Skeleton /></TableCell></TableRow>
                  ))
                : lotes.length === 0
                  ? <TableRow><TableCell colSpan={7} align="center"><Typography color="text.secondary" py={2}>Sin lotes activos</Typography></TableCell></TableRow>
                  : lotes.map(l => (
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
          {kpis?.mes && (
            <Paper sx={{ p: 2, mb: 2 }}>
              <Typography fontWeight={700} mb={1}>
                Mes actual ({kpis.mes.desde} → {kpis.mes.hasta})
              </Typography>
              <Grid container spacing={2}>
                {[
                  { label: 'Ventas', value: formatNumber(kpis.mes.total_ventas) },
                  { label: 'Unidades', value: formatNumber(kpis.mes.total_unidades) },
                  { label: 'Ingresos', value: formatCurrency(parseFloat(kpis.mes.ingresos_bob)) },
                  { label: 'Ganancia', value: formatCurrency(parseFloat(kpis.mes.ganancia_bob)), color: 'success.main' },
                ].map(s => (
                  <Grid item key={s.label} xs={6} sm={3}>
                    <Box textAlign="center" p={1} border="1px solid" borderColor="divider" borderRadius={1}>
                      <Typography variant="caption" color="text.secondary">{s.label}</Typography>
                      <Typography fontWeight={700} color={s.color}>{s.value}</Typography>
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
                  <TableCell><strong>Estado</strong></TableCell>
                  <TableCell><strong>Hora</strong></TableCell>
                  {canManage && <TableCell />}
                </TableRow>
              </TableHead>
              <TableBody>
                {loading
                  ? Array.from({ length: 5 }).map((_, i) => (
                      <TableRow key={i}><TableCell colSpan={10}><Skeleton /></TableCell></TableRow>
                    ))
                  : ventas.length === 0
                    ? <TableRow><TableCell colSpan={10} align="center"><Typography color="text.secondary" py={2}>Sin ventas en el período</Typography></TableCell></TableRow>
                    : ventas.map(v => (
                      <TableRow key={v.id} hover
                        sx={{ opacity: v.estado === 'ANULADA' ? 0.5 : 1 }}>
                        <TableCell>
                          <Typography variant="caption" fontFamily="monospace">{v.numero_venta}</Typography>
                        </TableCell>
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
                        <TableCell>
                          <Chip label={v.estado} size="small"
                            color={v.estado === 'ANULADA' ? 'error' : 'success'} />
                        </TableCell>
                        <TableCell>
                          <Typography variant="caption">
                            {new Date(v.created_at).toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' })}
                          </Typography>
                        </TableCell>
                        {canManage && (
                          <TableCell>
                            {v.estado === 'COMPLETADA' && (
                              <Tooltip title="Anular venta">
                                <IconButton size="small" color="error"
                                  onClick={() => setAnularDialog(v)}>
                                  <Cancel fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}
                          </TableCell>
                        )}
                      </TableRow>
                    ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}

      {/* Dialogs */}
      <LoteDialog open={!!loteDialog} tipo={loteDialog}
        onClose={() => setLoteDialog(null)} onSuccess={load} />
      <VentaDialog open={!!ventaDialog} tipo={ventaDialog}
        onClose={() => setVentaDialog(null)} onSuccess={load} />
      <AnularDialog open={!!anularDialog} venta={anularDialog}
        onClose={() => setAnularDialog(null)} onSuccess={load} />
    </Box>
  );
};

export default Tarjetas;
