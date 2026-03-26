import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TablePagination, Chip, Typography,
  TextField, Grid, FormControl, InputLabel, Select, MenuItem,
  InputAdornment,
} from '@mui/material';
import { Search } from '@mui/icons-material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatNumber } from '../../utils/formatters';

const InventoryMovements: React.FC = () => {
  const [movements,   setMovements]   = useState<any[]>([]);
  const [inventory,   setInventory]   = useState<any[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [page,        setPage]        = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [total,       setTotal]       = useState(0);
  const [selectedInv, setSelectedInv] = useState('');
  const [movType,     setMovType]     = useState('');
  const { enqueueSnackbar }           = useSnackbar();

  useEffect(() => {
    api.get('/inventory/stock/').then(res => {
      setInventory(res.data.results ?? res.data);
    });
  }, []);

  const load = useCallback(async () => {
    if (!selectedInv) {
      setMovements([]); setTotal(0); setLoading(false); return;
    }
    setLoading(true);
    try {
      const res = await api.get(`/inventory/stock/${selectedInv}/movements/`, {
        params: {
          page:      page + 1,
          page_size: rowsPerPage,
          type:      movType || undefined,
        },
      });
      setMovements(res.data.results ?? res.data);
      setTotal(res.data.count ?? res.data.length);
    } catch {
      enqueueSnackbar('Error al cargar movimientos', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [selectedInv, page, rowsPerPage, movType, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const movColors: Record<string, any> = {
    IN:           'success',
    OUT:          'error',
    ADJUSTMENT:   'warning',
    TRANSFER_IN:  'info',
    TRANSFER_OUT: 'secondary',
  };

  return (
    <Box>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid xs={12} md={5}>
            <FormControl fullWidth>
              <InputLabel>Divisa / Sucursal</InputLabel>
              <Select value={selectedInv}
                onChange={(e) => setSelectedInv(e.target.value)} label="Divisa / Sucursal">
                <MenuItem value="">Seleccionar...</MenuItem>
                {inventory.map((inv) => (
                  <MenuItem key={inv.id} value={inv.id}>
                    {inv.currency?.code} — {inv.branch?.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid xs={12} md={3}>
            <FormControl fullWidth>
              <InputLabel>Tipo de Movimiento</InputLabel>
              <Select value={movType}
                onChange={(e) => setMovType(e.target.value)} label="Tipo de Movimiento">
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

      {!selectedInv ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            Selecciona una divisa/sucursal para ver sus movimientos
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Tipo</TableCell>
                <TableCell align="right">Monto</TableCell>
                <TableCell align="right">Tasa</TableCell>
                <TableCell align="right">Balance Antes</TableCell>
                <TableCell align="right">Balance Después</TableCell>
                <TableCell>Referencia</TableCell>
                <TableCell>Usuario</TableCell>
                <TableCell>Fecha</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {movements.map((m) => (
                <TableRow key={m.id} hover>
                  <TableCell>
                    <Chip label={m.movement_type}
                      color={movColors[m.movement_type] ?? 'default'}
                      size="small" />
                  </TableCell>
                  <TableCell align="right">
                    <Typography fontWeight="bold"
                      color={m.movement_type === 'OUT' ? 'error.main' : 'success.main'}>
                      {m.movement_type === 'OUT' ? '-' : '+'}{formatNumber(m.amount)}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">{formatNumber(m.rate, 4)}</TableCell>
                  <TableCell align="right">{formatNumber(m.balance_before)}</TableCell>
                  <TableCell align="right">{formatNumber(m.balance_after)}</TableCell>
                  <TableCell>
                    <Typography variant="caption">{m.reference || m.notes || '—'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">{m.user}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">
                      {format(new Date(m.created_at), 'dd/MM/yyyy HH:mm', { locale: es })}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
              {!loading && movements.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} align="center">
                    <Typography color="text.secondary" py={3}>Sin movimientos</Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          <TablePagination
            rowsPerPageOptions={[10, 25, 50]}
            component="div" count={total}
            rowsPerPage={rowsPerPage} page={page}
            onPageChange={(_, p) => setPage(p)}
            onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value)); setPage(0); }}
            labelRowsPerPage="Filas por página"
          />
        </TableContainer>
      )}
    </Box>
  );
};

export default InventoryMovements;