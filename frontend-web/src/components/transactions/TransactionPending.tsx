import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Typography, Button, Chip, Alert,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField,
} from '@mui/material';
import { CheckCircle, Cancel } from '@mui/icons-material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatCurrency } from '../../utils/formatters';
import { useAuth } from '../../contexts/AuthContext';

const TransactionPending: React.FC = () => {
  const [pending,      setPending]      = useState<any[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [reverseOpen,  setReverseOpen]  = useState(false);
  const [selected,     setSelected]     = useState<any>(null);
  const [reason,       setReason]       = useState('');
  const { user }                        = useAuth();
  const { enqueueSnackbar }             = useSnackbar();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/transactions/pending-approvals/');
      setPending(res.data.results ?? res.data);
    } catch {
      enqueueSnackbar('Error al cargar pendientes', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const handleApprove = async (txId: number) => {
    try {
      await api.post(`/transactions/${txId}/approve/`);
      enqueueSnackbar('Transacción aprobada', { variant: 'success' });
      load();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al aprobar', { variant: 'error' });
    }
  };

  const handleReverse = async () => {
    if (!selected || !reason) return;
    try {
      await api.post(`/transactions/${selected.id}/reverse/`, { reason });
      enqueueSnackbar('Transacción reversada', { variant: 'success' });
      setReverseOpen(false);
      setReason('');
      load();
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al reversar', { variant: 'error' });
    }
  };

  if (user?.role === 'CASHIER') {
    return (
      <Alert severity="info">
        Solo supervisores y administradores pueden ver transacciones pendientes de aprobación.
      </Alert>
    );
  }

  return (
    <Box>
      <Alert severity="warning" sx={{ mb: 3 }}>
        Estas transacciones superan los límites establecidos y requieren aprobación de supervisor.
      </Alert>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>N° Transacción</TableCell>
              <TableCell>Cliente</TableCell>
              <TableCell>Tipo</TableCell>
              <TableCell>Divisa</TableCell>
              <TableCell align="right">Monto</TableCell>
              <TableCell align="right">Total BOB</TableCell>
              <TableCell>Cajero</TableCell>
              <TableCell>Fecha</TableCell>
              <TableCell>Acciones</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {pending.map((tx) => (
              <TableRow key={tx.id} hover
                sx={{ bgcolor: 'warning.50' }}>
                <TableCell>
                  <Typography variant="caption" fontFamily="monospace">
                    {tx.transaction_number}
                  </Typography>
                </TableCell>
                <TableCell>{tx.customer?.full_name}</TableCell>
                <TableCell>
                  <Chip
                    label={tx.transaction_type === 'BUY' ? 'Compra' : 'Venta'}
                    color={tx.transaction_type === 'BUY' ? 'success' : 'warning'}
                    size="small"
                  />
                </TableCell>
                <TableCell>{tx.currency_from?.code}</TableCell>
                <TableCell align="right">{formatCurrency(tx.amount_from, tx.currency_from?.code)}</TableCell>
                <TableCell align="right">
                  <Typography fontWeight="bold" color="warning.main">
                    {formatCurrency(tx.amount_to)}
                  </Typography>
                </TableCell>
                <TableCell>
                  {tx.cashier?.first_name} {tx.cashier?.last_name}
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {format(new Date(tx.created_at), 'dd/MM/yyyy HH:mm', { locale: es })}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Box display="flex" gap={1}>
                    <Button size="small" variant="contained" color="success"
                      startIcon={<CheckCircle />}
                      onClick={() => handleApprove(tx.id)}>
                      Aprobar
                    </Button>
                    <Button size="small" variant="outlined" color="error"
                      startIcon={<Cancel />}
                      onClick={() => { setSelected(tx); setReverseOpen(true); }}>
                      Reversar
                    </Button>
                  </Box>
                </TableCell>
              </TableRow>
            ))}
            {!loading && pending.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} align="center">
                  <Box py={4} display="flex" flexDirection="column" alignItems="center" gap={1}>
                    <CheckCircle color="success" sx={{ fontSize: 48 }} />
                    <Typography color="text.secondary">
                      Sin transacciones pendientes de aprobación
                    </Typography>
                  </Box>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <Dialog open={reverseOpen} onClose={() => setReverseOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Reversar Transacción</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" mb={2}>
            Transacción: <strong>{selected?.transaction_number}</strong>
          </Typography>
          <TextField fullWidth multiline rows={3}
            label="Razón de la reversión (requerido)"
            value={reason} onChange={(e) => setReason(e.target.value)} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setReverseOpen(false)}>Cancelar</Button>
          <Button variant="contained" color="error"
            onClick={handleReverse} disabled={!reason}>
            Confirmar Reversión
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default TransactionPending;