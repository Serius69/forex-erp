import React from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, Typography, Grid, Chip, Divider, Box,
} from '@mui/material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { formatCurrency } from '../../utils/formatters';

interface TransactionDetailsProps {
  open: boolean;
  onClose: () => void;
  transaction: any;
}

const statusColors: Record<string, any> = {
  COMPLETED: 'success',
  PENDING:   'warning',
  CANCELLED: 'error',
  REVERSED:  'default',
};

const TransactionDetails: React.FC<TransactionDetailsProps> = ({
  open, onClose, transaction,
}) => {
  if (!transaction) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography variant="h6">
            Transacción {transaction.transaction_number}
          </Typography>
          <Chip
            label={transaction.status}
            color={statusColors[transaction.status] || 'default'}
            size="small"
          />
        </Box>
      </DialogTitle>
      <DialogContent>
        <Grid container spacing={2}>
          <Grid item xs={6}>
            <Typography variant="caption" color="text.secondary">Tipo</Typography>
            <Typography variant="body1" fontWeight="bold">
              {transaction.transaction_type === 'BUY' ? 'Compra' : 'Venta'}
            </Typography>
          </Grid>
          <Grid item xs={6}>
            <Typography variant="caption" color="text.secondary">Fecha</Typography>
            <Typography variant="body1">
              {format(new Date(transaction.created_at), 'dd/MM/yyyy HH:mm', { locale: es })}
            </Typography>
          </Grid>

          <Grid item xs={12}><Divider /></Grid>

          <Grid item xs={6}>
            <Typography variant="caption" color="text.secondary">Cliente</Typography>
            <Typography variant="body1">{transaction.customer?.full_name}</Typography>
            <Typography variant="caption" color="text.secondary">
              {transaction.customer?.document_type}: {transaction.customer?.document_number}
            </Typography>
          </Grid>
          <Grid item xs={6}>
            <Typography variant="caption" color="text.secondary">Cajero</Typography>
            <Typography variant="body1">
              {transaction.cashier?.first_name} {transaction.cashier?.last_name}
            </Typography>
          </Grid>

          <Grid item xs={12}><Divider /></Grid>

          <Grid item xs={4}>
            <Typography variant="caption" color="text.secondary">Divisa</Typography>
            <Typography variant="h6">{transaction.currency_from?.code}</Typography>
          </Grid>
          <Grid item xs={4}>
            <Typography variant="caption" color="text.secondary">Monto</Typography>
            <Typography variant="h6">
              {formatCurrency(transaction.amount_from)}
            </Typography>
          </Grid>
          <Grid item xs={4}>
            <Typography variant="caption" color="text.secondary">Tipo de cambio</Typography>
            <Typography variant="h6">{transaction.exchange_rate}</Typography>
          </Grid>

          <Grid item xs={12}>
            <Box sx={{ p: 2, bgcolor: 'success.light', borderRadius: 1, textAlign: 'center' }}>
              <Typography variant="caption" color="success.contrastText">
                Total en Bolivianos
              </Typography>
              <Typography variant="h5" color="success.contrastText" fontWeight="bold">
                {formatCurrency(transaction.amount_to)}
              </Typography>
            </Box>
          </Grid>

          <Grid item xs={6}>
            <Typography variant="caption" color="text.secondary">Método de pago</Typography>
            <Typography variant="body1">{transaction.payment_method}</Typography>
          </Grid>
          {transaction.payment_reference && (
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">Referencia</Typography>
              <Typography variant="body1">{transaction.payment_reference}</Typography>
            </Grid>
          )}
          {transaction.notes && (
            <Grid item xs={12}>
              <Typography variant="caption" color="text.secondary">Notas</Typography>
              <Typography variant="body2">{transaction.notes}</Typography>
            </Grid>
          )}
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cerrar</Button>
      </DialogActions>
    </Dialog>
  );
};

export default TransactionDetails;