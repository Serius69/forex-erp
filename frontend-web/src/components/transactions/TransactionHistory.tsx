// src/components/transactions/TransactionHistory.tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TablePagination, TextField, InputAdornment,
  Chip, Typography, Grid, FormControl, InputLabel, Select,
  MenuItem, Button, IconButton, Tooltip, Dialog, DialogTitle,
  DialogContent, DialogActions, Alert,
} from '@mui/material';
import {
  Search, Edit, Cancel, Receipt, FilterList,
} from '@mui/icons-material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { useFormik } from 'formik';
import * as yup from 'yup';
import { api, downloadFile } from '../../services/api';
import { formatCurrency, formatNumber } from '../../utils/formatters';
import { useAuth } from '../../contexts/AuthContext';

// ── Tipos alineados con el backend ───────────────────────────────────────────
interface Currency {
  id:     number;
  code:   string;
  name:   string;
  symbol: string;
}

interface Customer {
  id:              number;
  full_name:       string;
  document_number: string;
  document_type:   string;
}

interface Cashier {
  id:         number;
  username:   string;
  first_name: string;
  last_name:  string;
}

interface Transaction {
  id:                    number;
  transaction_number:    string;
  transaction_type:      'BUY' | 'SELL';
  status:                'COMPLETED' | 'PENDING' | 'CANCELLED' | 'REVERSED';
  is_reportable_to_asfi: boolean | null;
  customer:              Customer;
  currency_from:         Currency;
  currency_to:           Currency;
  amount_from:           number;
  amount_to:             number;
  exchange_rate:         number;
  payment_method:        string;
  payment_reference:     string | null;
  notes:                 string | null;
  bob_impact:            string | null;
  cashier:               Cashier | null;
  branch_name:           string | null;
  created_at:            string;
  completed_at:          string | null;
}

interface PaginatedResponse {
  count:    number;
  results:  Transaction[];
}

// ── Colores de estado ─────────────────────────────────────────────────────────
const STATUS_COLORS: Record<string, 'success' | 'warning' | 'error' | 'default'> = {
  COMPLETED: 'success',
  PENDING:   'warning',
  CANCELLED: 'error',
  REVERSED:  'default',
};

const STATUS_LABELS: Record<string, string> = {
  COMPLETED: 'Completada',
  PENDING:   'Pendiente',
  CANCELLED: 'Cancelada',
  REVERSED:  'Reversada',
};

// ── Validación de edición ─────────────────────────────────────────────────────
const editSchema = yup.object({
  exchange_rate:     yup.number().min(0.0001, 'Tasa inválida').required(),
  payment_method:    yup.string().required(),
  payment_reference: yup.string(),
  notes:             yup.string(),
});

// ── Componente principal ──────────────────────────────────────────────────────
const TransactionHistory: React.FC = () => {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [page,         setPage]         = useState(0);
  const [rowsPerPage,  setRowsPerPage]  = useState(25);
  const [total,        setTotal]        = useState(0);
  const [search,       setSearch]       = useState('');
  const [dateFrom,     setDateFrom]     = useState(
    new Date(new Date().getFullYear(), new Date().getMonth(), 1)
      .toISOString().split('T')[0]);
  const [dateTo,       setDateTo]       = useState(
    new Date().toISOString().split('T')[0]);
  const [txType,          setTxType]          = useState('');
  const [txStatus,        setTxStatus]        = useState('');
  const [reportableFilter, setReportableFilter] = useState('');
  const [editOpen,     setEditOpen]     = useState(false);
  const [cancelOpen,   setCancelOpen]   = useState(false);
  const [selected,     setSelected]     = useState<Transaction | null>(null);
  const [cancelReason, setCancelReason] = useState('');
  const [receiptBusy,  setReceiptBusy]  = useState<number | null>(null);
  const { user }                        = useAuth();
  const { enqueueSnackbar }             = useSnackbar();

  const handleReceipt = async (tx: Transaction) => {
    setReceiptBusy(tx.id);
    try {
      const res = await api.get(`/transactions/${tx.id}/receipt/`, { responseType: 'blob' });
      downloadFile(res.data, `${tx.transaction_number}.pdf`);
    } catch {
      enqueueSnackbar('No se pudo generar el comprobante', { variant: 'error' });
    } finally {
      setReceiptBusy(null);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<PaginatedResponse>('/transactions/', {
        params: {
          page:      page + 1,
          page_size: rowsPerPage,
          search:    search    || undefined,
          date_from: dateFrom  || undefined,
          date_to:   dateTo    || undefined,
          transaction_type:      txType            || undefined,
          status:                txStatus          || undefined,
          is_reportable_to_asfi: reportableFilter !== ''
            ? reportableFilter === 'true'
            : undefined,
        },
      });
      setTransactions(res.data.results ?? []);
      setTotal(res.data.count ?? 0);
    } catch {
      enqueueSnackbar('Error al cargar transacciones', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, search, dateFrom, dateTo, txType, txStatus, reportableFilter, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  // ── Edición ───────────────────────────────────────────────────────────────
  const formik = useFormik({
    initialValues: {
      exchange_rate:     '',
      payment_method:    'CASH',
      payment_reference: '',
      notes:             '',
    },
    validationSchema: editSchema,
    onSubmit: async (values) => {
      if (!selected) return;
      try {
        await api.patch(`/transactions/${selected.id}/`, {
          exchange_rate:     parseFloat(values.exchange_rate),
          payment_method:    values.payment_method,
          payment_reference: values.payment_reference || null,
          notes:             values.notes || null,
        });
        enqueueSnackbar('Transacción actualizada', { variant: 'success' });
        setEditOpen(false);
        load();
      } catch (e: any) {
        const msg = e.response?.data?.detail || 'Error al actualizar';
        enqueueSnackbar(msg, { variant: 'error' });
      }
    },
  });

  const handleEdit = (tx: Transaction) => {
    setSelected(tx);
    formik.setValues({
      exchange_rate:     String(tx.exchange_rate),
      payment_method:    tx.payment_method,
      payment_reference: tx.payment_reference ?? '',
      notes:             tx.notes ?? '',
    });
    setEditOpen(true);
  };

  // ── Anulación ─────────────────────────────────────────────────────────────
  const handleCancel = async () => {
    if (!selected || !cancelReason.trim()) return;
    try {
      await api.post(`/transactions/${selected.id}/reverse/`, {
        reason: cancelReason,
      });
      enqueueSnackbar('Transacción anulada', { variant: 'success' });
      setCancelOpen(false);
      setCancelReason('');
      load();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al anular', { variant: 'error' });
    }
  };

  const canEdit   = (tx: Transaction) =>
    tx.status === 'COMPLETED' &&
    (user?.role === 'ADMIN' || user?.role === 'SUPERVISOR');

  const canCancel = (tx: Transaction) =>
    tx.status === 'COMPLETED' &&
    user?.role === 'ADMIN';

  return (
    <Box>
      {/* ── Filtros ── */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} md={4}>
            <TextField fullWidth
              placeholder="Buscar por número, cliente, documento..."
              value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }}
              InputProps={{ startAdornment: <InputAdornment position="start"><Search /></InputAdornment> }} />
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField fullWidth label="Desde" type="date"
              value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(0); }}
              InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField fullWidth label="Hasta" type="date"
              value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(0); }}
              InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid item xs={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Tipo</InputLabel>
              <Select value={txType} onChange={(e) => { setTxType(e.target.value); setPage(0); }} label="Tipo">
                <MenuItem value="">Todos</MenuItem>
                <MenuItem value="BUY">Compra</MenuItem>
                <MenuItem value="SELL">Venta</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Estado</InputLabel>
              <Select value={txStatus} onChange={(e) => { setTxStatus(e.target.value); setPage(0); }} label="Estado">
                <MenuItem value="">Todos</MenuItem>
                <MenuItem value="COMPLETED">Completada</MenuItem>
                <MenuItem value="PENDING">Pendiente</MenuItem>
                <MenuItem value="CANCELLED">Cancelada</MenuItem>
                <MenuItem value="REVERSED">Reversada</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Reporte ASFI</InputLabel>
              <Select
                value={reportableFilter}
                onChange={(e) => { setReportableFilter(e.target.value); setPage(0); }}
                label="Reporte ASFI"
              >
                <MenuItem value="">Todas</MenuItem>
                <MenuItem value="true">🟢 Solo reportables</MenuItem>
                <MenuItem value="false">🔵 Solo internas</MenuItem>
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </Paper>

      {/* ── Resumen ── */}
      <Box display="flex" gap={2} mb={1}>
        <Typography variant="body2" color="text.secondary">
          Total: <strong>{total}</strong> transacciones
        </Typography>
      </Box>

      {/* ── Tabla ── */}
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>N° Transacción</TableCell>
              <TableCell>Cliente</TableCell>
              <TableCell>Tipo</TableCell>
              <TableCell>Divisa</TableCell>
              <TableCell align="right">Monto</TableCell>
              <TableCell align="right">Tasa</TableCell>
              <TableCell align="right">Total BOB</TableCell>
              <TableCell align="right">Impacto Caja</TableCell>
              <TableCell>Pago</TableCell>
              <TableCell>Tipo</TableCell>
              <TableCell>Estado</TableCell>
              <TableCell>Cajero</TableCell>
              <TableCell>Fecha</TableCell>
              <TableCell>Acciones</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {transactions.map((tx) => (
              <TableRow key={tx.id} hover
                sx={{ opacity: tx.status === 'CANCELLED' || tx.status === 'REVERSED' ? 0.6 : 1 }}>
                <TableCell>
                  <Typography variant="caption" fontFamily="monospace" fontWeight="bold">
                    {tx.transaction_number}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="body2">{tx.customer?.full_name}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {tx.customer?.document_number}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    label={tx.transaction_type === 'BUY' ? 'Compra' : 'Venta'}
                    color={tx.transaction_type === 'BUY' ? 'success' : 'warning'}
                    size="small" variant="outlined"
                  />
                </TableCell>
                <TableCell>
                  <Typography variant="body2" fontWeight="bold">
                    {tx.currency_from?.code}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  {formatNumber(tx.amount_from)}
                </TableCell>
                <TableCell align="right">
                  <Typography variant="caption">{formatNumber(tx.exchange_rate, 4)}</Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography fontWeight="bold" color="primary.main">
                    {formatCurrency(tx.amount_to)}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  {tx.bob_impact != null && (
                    <Typography
                      variant="body2"
                      fontWeight={700}
                      fontFamily="monospace"
                      color={
                        tx.status === 'REVERSED' || tx.status === 'CANCELLED'
                          ? 'text.disabled'
                          : tx.bob_impact.startsWith('+')
                            ? 'success.main'
                            : 'error.main'
                      }
                    >
                      {tx.bob_impact} Bs.
                    </Typography>
                  )}
                </TableCell>
                <TableCell>
                  <Typography variant="caption">{tx.payment_method}</Typography>
                </TableCell>
                <TableCell>
                  {tx.is_reportable_to_asfi === true && (
                    <Chip label="🟢 Reportable" size="small" color="success" variant="outlined"
                      sx={{ fontSize: '0.65rem', height: 20 }} />
                  )}
                  {tx.is_reportable_to_asfi === false && (
                    <Chip label="🔵 Interna" size="small" color="primary" variant="outlined"
                      sx={{ fontSize: '0.65rem', height: 20 }} />
                  )}
                  {tx.is_reportable_to_asfi === null && (
                    <Chip label="—" size="small" variant="outlined"
                      sx={{ fontSize: '0.65rem', height: 20 }} />
                  )}
                </TableCell>
                <TableCell>
                  <Chip
                    label={STATUS_LABELS[tx.status] ?? tx.status}
                    color={STATUS_COLORS[tx.status] ?? 'default'}
                    size="small"
                  />
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {tx.cashier?.first_name} {tx.cashier?.last_name}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {format(new Date(tx.created_at), 'dd/MM/yyyy HH:mm', { locale: es })}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Box display="flex" gap={0.5}>
                    {canEdit(tx) && (
                      <Tooltip title="Editar">
                        <IconButton size="small" onClick={() => handleEdit(tx)}>
                          <Edit fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                    {canCancel(tx) && (
                      <Tooltip title="Anular">
                        <IconButton size="small" color="error"
                          onClick={() => { setSelected(tx); setCancelOpen(true); }}>
                          <Cancel fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                    <Tooltip title="Comprobante PDF">
                      <span>
                        <IconButton size="small" color="primary"
                          disabled={receiptBusy === tx.id}
                          onClick={() => handleReceipt(tx)}>
                          <Receipt fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                  </Box>
                </TableCell>
              </TableRow>
            ))}
            {!loading && transactions.length === 0 && (
              <TableRow>
                <TableCell colSpan={14} align="center">
                  <Box py={4} display="flex" flexDirection="column" alignItems="center" gap={1}>
                    <Receipt color="disabled" sx={{ fontSize: 48 }} />
                    <Typography color="text.secondary">
                      Sin transacciones en el período seleccionado
                    </Typography>
                  </Box>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50, 100]}
          component="div" count={total}
          rowsPerPage={rowsPerPage} page={page}
          onPageChange={(_, p) => setPage(p)}
          onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value)); setPage(0); }}
          labelRowsPerPage="Filas por página"
        />
      </TableContainer>

      {/* ── Dialog edición ── */}
      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          Editar Transacción — {selected?.transaction_number}
        </DialogTitle>
        <DialogContent>
          {selected?.status !== 'COMPLETED' && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Solo se pueden editar transacciones completadas.
            </Alert>
          )}
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={6}>
              <TextField fullWidth label="Tipo de Cambio" name="exchange_rate"
                type="number" value={formik.values.exchange_rate}
                onChange={formik.handleChange}
                error={formik.touched.exchange_rate && Boolean(formik.errors.exchange_rate)}
                helperText={formik.touched.exchange_rate && formik.errors.exchange_rate} />
            </Grid>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>Método de Pago</InputLabel>
                <Select name="payment_method" value={formik.values.payment_method}
                  onChange={formik.handleChange} label="Método de Pago">
                  <MenuItem value="CASH">Efectivo</MenuItem>
                  <MenuItem value="TRANSFER">Transferencia</MenuItem>
                  <MenuItem value="QR">QR</MenuItem>
                  <MenuItem value="CHECK">Cheque</MenuItem>
                  <MenuItem value="CARD">Tarjeta</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12}>
              <TextField fullWidth label="Referencia de Pago" name="payment_reference"
                value={formik.values.payment_reference} onChange={formik.handleChange} />
            </Grid>
            <Grid item xs={12}>
              <TextField fullWidth label="Notas" name="notes" multiline rows={2}
                value={formik.values.notes} onChange={formik.handleChange} />
            </Grid>
          </Grid>
          {selected && (
            <Box mt={2} p={1.5} bgcolor="grey.100" borderRadius={1}>
              <Typography variant="caption" color="text.secondary">
                Cliente: <strong>{selected.customer?.full_name}</strong> |
                Monto: <strong>{selected.currency_from?.code} {formatNumber(selected.amount_from)}</strong> |
                Total: <strong>{formatCurrency(selected.amount_to)}</strong>
              </Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancelar</Button>
          <Button variant="contained" onClick={() => formik.submitForm()}>
            Guardar Cambios
          </Button>
        </DialogActions>
      </Dialog>

      {/* ── Dialog anulación ── */}
      <Dialog open={cancelOpen} onClose={() => setCancelOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Anular Transacción</DialogTitle>
        <DialogContent>
          <Alert severity="error" sx={{ mb: 2 }}>
            Esta acción no se puede deshacer. La transacción quedará marcada como REVERSADA.
          </Alert>
          <Typography variant="body2" color="text.secondary" mb={1}>
            Transacción: <strong>{selected?.transaction_number}</strong>
          </Typography>
          <Typography variant="body2" color="text.secondary" mb={2}>
            Total: <strong>{formatCurrency(selected?.amount_to ?? 0)}</strong>
          </Typography>
          <TextField fullWidth multiline rows={2}
            label="Razón de anulación (requerido)"
            value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setCancelOpen(false); setCancelReason(''); }}>
            Cancelar
          </Button>
          <Button variant="contained" color="error"
            onClick={handleCancel} disabled={!cancelReason.trim()}>
            Confirmar Anulación
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default TransactionHistory;