import React from 'react';
import {
  Card, CardContent, Typography, Table, TableBody,
  TableCell, TableHead, TableRow, Chip, Box,
} from '@mui/material';
import { formatCurrency } from '../../utils/formatters';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';

interface Props {
  transactions: any[];
}

const RecentTransactions: React.FC<Props> = ({ transactions }) => (
  <Card>
    <CardContent>
      <Typography variant="h6" mb={2}>Transacciones Recientes</Typography>
      {transactions.length === 0 ? (
        <Typography color="text.secondary">Sin transacciones hoy</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>N°</TableCell>
              <TableCell>Cliente</TableCell>
              <TableCell>Tipo</TableCell>
              <TableCell>Divisa</TableCell>
              <TableCell align="right">Monto</TableCell>
              <TableCell align="right">Total BOB</TableCell>
              <TableCell>Hora</TableCell>
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
                <TableCell>{tx.customer}</TableCell>
                <TableCell>
                  <Chip
                    label={tx.type === 'BUY' ? 'Compra' : 'Venta'}
                    color={tx.type === 'BUY' ? 'success' : 'warning'}
                    size="small"
                  />
                </TableCell>
                <TableCell>{tx.currency}</TableCell>
                <TableCell align="right">{formatCurrency(tx.amount, tx.currency)}</TableCell>
                <TableCell align="right" sx={{ fontWeight: 'bold' }}>
                  {formatCurrency(tx.total_bob)}
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {format(new Date(tx.created_at), 'HH:mm', { locale: es })}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </CardContent>
  </Card>
);

export default RecentTransactions;