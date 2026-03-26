import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TablePagination, TextField, InputAdornment,
  Chip, Typography, Grid, FormControl, InputLabel, Select, MenuItem,
  Button,
} from '@mui/material';
import { Search, FileDownload } from '@mui/icons-material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api, downloadFile } from '../../services/api';
import { formatCurrency, formatNumber } from '../../utils/formatters';

const TransactionHistory: React.FC = () => {
  const [transactions, setTransactions] = useState<any[]>([]);
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
  const [txType,       setTxType]       = useState('');
  const [txStatus,     setTxStatus]     = useState('');
  const { enqueueSnackbar }             = useSnackbar();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/transactions/', {
        params: {
          page:      page + 1,
          page_size: rowsPerPage,
          search:    search    || undefined,
          date_from: dateFrom  || undefined,
          date_to:   dateTo    || undefined,
          type:      txType    || undefined,
          status:    txStatus  || undefined,
        },
      });
      setTransactions(res.data.results ?? res.data);
      setTotal(res.data.count ?? res.data.length);
    } catch {
      enqueueSnackbar('Error al cargar historial', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, search, dateFrom, dateTo, txType, txStatus, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const statusColors: Record<string, any> = {
    COMPLETED: 'success', PENDING: 'warning',
    CANCELLED: 'error',   REVERSED: 'default',
  };

  return (
    <Box>
      {/* ── Filtros ── */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid xs={12} md={4}>
            <TextField fullWidth placeholder="Buscar por número, cliente..."
              value={search} onChange={(e) => setSearch(e.target.value)}
              InputProps={{ startAdornment: <InputAdornment position="start"><Search /></InputAdornment> }} />
          </Grid>
          <Grid xs={6} md={2}>
            <TextField fullWidth label="Desde" type="date"
              value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
              InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid xs={6} md={2}>
            <TextField fullWidth label="Hasta" type="date"
              value={dateTo} onChange={(e) => setDateTo(e.target.value)}
              InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid xs={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Tipo</InputLabel>
              <Select value={txType} onChange={(e) => setTxType(e.target.value)} label="Tipo">
                <MenuItem value="">Todos</MenuItem>
                <MenuItem value="BUY">Compra</MenuItem>
                <MenuItem value="SELL">Venta</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid xs={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Estado</InputLabel>
              <Select value={txStatus} onChange={(e) => setTxStatus(e.target.value)} label="Estado">
                <MenuItem value="">Todos</MenuItem>
                <MenuItem value="COMPLETED">Completada</MenuItem>
                <MenuItem value="PENDING">Pendiente</MenuItem>
                <MenuItem value="CANCELLED">Cancelada</MenuItem>
                <MenuItem value="REVERSED">Reversada</MenuItem>
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </Paper>

      {/* ── Resumen ── */}
      <Box display="flex" gap={2} mb={2}>
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
              <TableCell>Pago</TableCell>
              <TableCell>Estado</TableCell>
              <TableCell>Cajero</TableCell>
              <TableCell>Fecha</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {transactions.map((tx) => (
              <TableRow key={tx.id} hover>
                <TableCell>
                  <Typography variant="caption" fontFamily="monospace">
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
                <TableCell>{tx.currency_from?.code}</TableCell>
                <TableCell align="right">{formatNumber(tx.amount_from)}</TableCell>
                <TableCell align="right">
                  <Typography variant="caption">{formatNumber(tx.exchange_rate, 4)}</Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography fontWeight="bold">{formatCurrency(tx.amount_to)}</Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption">{tx.payment_method}</Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    label={tx.status}
                    color={statusColors[tx.status] ?? 'default'}
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
              </TableRow>
            ))}
            {!loading && transactions.length === 0 && (
              <TableRow>
                <TableCell colSpan={11} align="center">
                  <Typography color="text.secondary" py={3}>
                    Sin transacciones en el período seleccionado
                  </Typography>
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
    </Box>
  );
};

export default TransactionHistory;