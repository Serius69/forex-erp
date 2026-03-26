import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TablePagination, Chip, Typography,
  Button, FormControl, InputLabel, Select, MenuItem, Grid,
} from '@mui/material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatNumber } from '../../utils/formatters';
import { useAuth } from '../../contexts/AuthContext';

const InventoryTransfers: React.FC = () => {
  const [transfers,   setTransfers]   = useState<any[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [page,        setPage]        = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [total,       setTotal]       = useState(0);
  const [statusFilter,setStatusFilter]= useState('');
  const { user }                      = useAuth();
  const { enqueueSnackbar }           = useSnackbar();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/inventory/transfers/', {
        params: {
          page:      page + 1,
          page_size: rowsPerPage,
          status:    statusFilter || undefined,
        },
      });
      setTransfers(res.data.results ?? res.data);
      setTotal(res.data.count ?? res.data.length);
    } catch {
      enqueueSnackbar('Error al cargar transferencias', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, statusFilter, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const handleAuthorize = async (transferId: number) => {
    try {
      await api.post(`/inventory/transfers/${transferId}/authorize/`);
      enqueueSnackbar('Transferencia autorizada', { variant: 'success' });
      load();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error', { variant: 'error' });
    }
  };

  const handleReceive = async (transferId: number) => {
    try {
      await api.post(`/inventory/transfers/${transferId}/receive/`);
      enqueueSnackbar('Transferencia recibida', { variant: 'success' });
      load();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error', { variant: 'error' });
    }
  };

  const statusColors: Record<string, any> = {
    PENDING:    'warning',
    IN_TRANSIT: 'info',
    COMPLETED:  'success',
    CANCELLED:  'error',
  };

  return (
    <Box>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2}>
          <Grid xs={12} md={3}>
            <FormControl fullWidth>
              <InputLabel>Estado</InputLabel>
              <Select value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)} label="Estado">
                <MenuItem value="">Todos</MenuItem>
                <MenuItem value="PENDING">Pendiente</MenuItem>
                <MenuItem value="IN_TRANSIT">En Tránsito</MenuItem>
                <MenuItem value="COMPLETED">Completada</MenuItem>
                <MenuItem value="CANCELLED">Cancelada</MenuItem>
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </Paper>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>N° Transferencia</TableCell>
              <TableCell>Divisa</TableCell>
              <TableCell>Origen</TableCell>
              <TableCell>Destino</TableCell>
              <TableCell align="right">Monto</TableCell>
              <TableCell>Estado</TableCell>
              <TableCell>Solicitado por</TableCell>
              <TableCell>Fecha</TableCell>
              {user?.role !== 'CASHIER' && <TableCell>Acciones</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {transfers.map((t) => (
              <TableRow key={t.id} hover>
                <TableCell>
                  <Typography variant="caption" fontFamily="monospace">
                    {t.transfer_number}
                  </Typography>
                </TableCell>
                <TableCell>{t.currency?.code}</TableCell>
                <TableCell>{t.source_branch?.name}</TableCell>
                <TableCell>{t.target_branch?.name}</TableCell>
                <TableCell align="right">
                  <Typography fontWeight="bold">{formatNumber(t.amount)}</Typography>
                </TableCell>
                <TableCell>
                  <Chip label={t.status}
                    color={statusColors[t.status] ?? 'default'}
                    size="small" />
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {t.requested_by?.first_name} {t.requested_by?.last_name}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {format(new Date(t.created_at), 'dd/MM/yyyy', { locale: es })}
                  </Typography>
                </TableCell>
                {user?.role !== 'CASHIER' && (
                  <TableCell>
                    {t.status === 'PENDING' && (
                      <Button size="small" variant="outlined" color="success"
                        onClick={() => handleAuthorize(t.id)}>
                        Autorizar
                      </Button>
                    )}
                    {t.status === 'IN_TRANSIT' && (
                      <Button size="small" variant="outlined" color="primary"
                        onClick={() => handleReceive(t.id)}>
                        Recibir
                      </Button>
                    )}
                  </TableCell>
                )}
              </TableRow>
            ))}
            {!loading && transfers.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} align="center">
                  <Typography color="text.secondary" py={3}>
                    Sin transferencias
                  </Typography>
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
    </Box>
  );
};

export default InventoryTransfers;