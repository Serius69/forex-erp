import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TablePagination, Chip, Typography,
  FormControl, InputLabel, Select, MenuItem, Grid, CircularProgress,
} from '@mui/material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatNumber } from '../../utils/formatters';

const MOV_COLORS: Record<string, any> = {
  IN:           'success',
  OUT:          'error',
  ADJUSTMENT:   'warning',
  TRANSFER_IN:  'info',
  TRANSFER_OUT: 'secondary',
};

const InventoryMovements: React.FC = () => {
  const [movements,    setMovements]    = useState<any[]>([]);
  const [inventory,    setInventory]    = useState<any[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [page,         setPage]         = useState(0);
  const [rowsPerPage,  setRowsPerPage]  = useState(25);
  const [total,        setTotal]        = useState(0);
  const [selectedInv,  setSelectedInv]  = useState('');
  const [movType,      setMovType]      = useState('');
  const { enqueueSnackbar }            = useSnackbar();

  useEffect(() => {
    api.get('/inventory/stock/').then(res => {
      const list = res.data?.results ?? res.data ?? [];
      setInventory(Array.isArray(list) ? list : []);
    }).catch(() => {
      // Sin aviso, el filtro aparecía vacío como si no hubiera inventario.
      setInventory([]);
      enqueueSnackbar('Error al cargar el inventario para el filtro', { variant: 'error' });
    });
  }, [enqueueSnackbar]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, any> = {
        page:      page + 1,
        page_size: rowsPerPage,
      };
      if (movType)      params.type         = movType;
      if (selectedInv)  params.inventory_id = selectedInv;

      const res = await api.get('/inventory/movements/', { params });
      const results = res.data?.results ?? res.data ?? [];
      setMovements(Array.isArray(results) ? results : []);
      setTotal(res.data?.count ?? results.length);
    } catch {
      enqueueSnackbar('Error al cargar movimientos', { variant: 'error' });
      setMovements([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [selectedInv, page, rowsPerPage, movType, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  return (
    <Box>
      {/* Filtros */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} md={5}>
            <FormControl fullWidth>
              <InputLabel>Divisa / Sucursal</InputLabel>
              <Select value={selectedInv}
                onChange={(e) => { setSelectedInv(e.target.value as string); setPage(0); }}
                label="Divisa / Sucursal">
                <MenuItem value="">Todas</MenuItem>
                {inventory.map((inv) => (
                  <MenuItem key={inv.id} value={String(inv.id)}>
                    {inv.currency?.code} — {inv.branch?.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={3}>
            <FormControl fullWidth>
              <InputLabel>Tipo de Movimiento</InputLabel>
              <Select value={movType}
                onChange={(e) => { setMovType(e.target.value as string); setPage(0); }}
                label="Tipo de Movimiento">
                <MenuItem value="">Todos</MenuItem>
                <MenuItem value="IN">Entrada</MenuItem>
                <MenuItem value="OUT">Salida</MenuItem>
                <MenuItem value="ADJUSTMENT">Ajuste</MenuItem>
                <MenuItem value="TRANSFER_IN">Transferencia Entrada</MenuItem>
                <MenuItem value="TRANSFER_OUT">Transferencia Salida</MenuItem>
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </Paper>

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Tipo</TableCell>
              <TableCell>Divisa</TableCell>
              <TableCell>Sucursal</TableCell>
              <TableCell align="right">Monto</TableCell>
              <TableCell align="right">Tasa</TableCell>
              <TableCell align="right">Bal. Antes</TableCell>
              <TableCell align="right">Bal. Después</TableCell>
              <TableCell>Referencia</TableCell>
              <TableCell>Usuario</TableCell>
              <TableCell>Fecha</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={10} align="center" sx={{ py: 4 }}>
                  <CircularProgress size={32} />
                </TableCell>
              </TableRow>
            ) : movements.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} align="center">
                  <Typography color="text.secondary" py={3}>
                    No hay movimientos disponibles
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              movements.map((m) => (
                <TableRow key={m.id} hover>
                  <TableCell>
                    <Chip label={m.movement_type}
                      color={MOV_COLORS[m.movement_type] ?? 'default'}
                      size="small" />
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" fontWeight="bold">
                      {m.currency_code}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">{m.branch_name}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography fontWeight="bold"
                      color={m.movement_type === 'OUT' || m.movement_type === 'TRANSFER_OUT'
                        ? 'error.main' : 'success.main'}>
                      {m.movement_type === 'OUT' || m.movement_type === 'TRANSFER_OUT'
                        ? '-' : '+'}{formatNumber(m.amount)}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">{formatNumber(m.rate, 4)}</TableCell>
                  <TableCell align="right">{formatNumber(m.balance_before)}</TableCell>
                  <TableCell align="right">{formatNumber(m.balance_after)}</TableCell>
                  <TableCell>
                    <Typography variant="caption">{m.reference || m.notes || '—'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">{m.user || '—'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">
                      {format(new Date(m.created_at), 'dd/MM/yyyy HH:mm', { locale: es })}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50]}
          component="div"
          count={total}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={(_, p) => setPage(p)}
          onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value)); setPage(0); }}
          labelRowsPerPage="Filas por página"
        />
      </TableContainer>
    </Box>
  );
};

export default InventoryMovements;
