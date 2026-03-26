import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  IconButton,
  Chip,
  TextField,
  InputAdornment,
  Menu,
  MenuItem,
  Typography,
  Tooltip,
  Button,
  Collapse,
  Grid,
  Card,
  CardContent,
} from '@mui/material';
import {
  Search,
  FilterList,
  MoreVert,
  Receipt,
  SwapHoriz,
  TrendingUp,
  TrendingDown,
  Print,
  Cancel,
  KeyboardArrowDown,
  KeyboardArrowUp,
} from '@mui/icons-material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';

import { api } from '../../services/api';
import { formatCurrency, formatNumber } from '../../utils/formatters';
import TransactionDetails from './TransactionDetails';
import { useAuth } from '../../contexts/AuthContext';

interface Transaction {
  id: number;
  transaction_number: string;
  transaction_type: 'BUY' | 'SELL';
  customer: {
    full_name: string;
    document_number: string;
  };
  currency_from: {
    code: string;
  };
  amount_from: number;
  exchange_rate: number;
  amount_to: number;
  payment_method: string;
  status: string;
  created_at: string;
  cashier: {
    username: string;
    first_name: string;
    last_name: string;
  };
}
interface TransactionListProps {
  onRefreshRef?: React.MutableRefObject<(() => void) | null>;
}


const TransactionList: React.FC<TransactionListProps> = ({ onRefreshRef }) => {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [totalCount, setTotalCount] = useState(0);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { user } = useAuth();
  const { enqueueSnackbar } = useSnackbar();



  const loadTransactions = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get('/transactions/', {
        params: {
          page:      page + 1,
          page_size: rowsPerPage,
          search:    searchTerm || undefined,
        },
      });
      setTransactions(response.data.results ?? response.data);
      setTotalCount(response.data.count ?? response.data.length);
    } catch (error) {
      enqueueSnackbar('Error al cargar transacciones', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, searchTerm, enqueueSnackbar]);

  useEffect(() => {
    if (onRefreshRef) {
      onRefreshRef.current = loadTransactions;
    }
  }, [loadTransactions, onRefreshRef]);

  const handlePrintReceipt = async (transactionId: number) => {
    try {
      const response = await api.get(`/transactions/${transactionId}/receipt/`, {
        responseType: 'blob',
      });
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `receipt_${transactionId}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      enqueueSnackbar('Error al descargar comprobante', { variant: 'error' });
    }
  };

  const handleReverse = async (transactionId: number) => {
    if (!window.confirm('¿Está seguro de reversar esta transacción?')) {
      return;
    }

    try {
      await api.post(`/transactions/${transactionId}/reverse/`, {
        reason: 'Reversión solicitada por usuario',
      });
      enqueueSnackbar('Transacción reversada exitosamente', { variant: 'success' });
      loadTransactions();
    } catch (error) {
      enqueueSnackbar('Error al reversar transacción', { variant: 'error' });
    }
  };

  const getStatusChip = (status: string) => {
    const statusConfig = {
      COMPLETED: { label: 'Completada', color: 'success' as const },
      PENDING: { label: 'Pendiente', color: 'warning' as const },
      CANCELLED: { label: 'Cancelada', color: 'error' as const },
      REVERSED: { label: 'Reversada', color: 'default' as const },
    };

    const config = statusConfig[status as keyof typeof statusConfig] || {
      label: status,
      color: 'default' as const,
    };

    return <Chip label={config.label} color={config.color} size="small" />;
  };

  const getTransactionIcon = (type: string) => {
    return type === 'BUY' ? (
      <TrendingDown color="error" />
    ) : (
      <TrendingUp color="success" />
    );
  };

  const Row = ({ transaction }: { transaction: Transaction }) => {
    const [open, setOpen] = useState(false);

    return (
      <>
        <TableRow
          hover
          sx={{ '& > *': { borderBottom: 'unset' } }}
        >
          <TableCell>
            <IconButton
              size="small"
              onClick={() => setOpen(!open)}
            >
              {open ? <KeyboardArrowUp /> : <KeyboardArrowDown />}
            </IconButton>
          </TableCell>
          <TableCell>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {getTransactionIcon(transaction.transaction_type)}
              <Typography variant="body2" fontWeight="medium">
                {transaction.transaction_number}
              </Typography>
            </Box>
          </TableCell>
          <TableCell>
            <Typography variant="body2" fontWeight="medium">
              {transaction.customer.full_name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {transaction.customer.document_number}
            </Typography>
          </TableCell>
          <TableCell>
            <Chip
              label={transaction.transaction_type === 'BUY' ? 'Compra' : 'Venta'}
              size="small"
              color={transaction.transaction_type === 'BUY' ? 'error' : 'success'}
              variant="outlined"
            />
          </TableCell>
          <TableCell>
            <Typography variant="body2">
              {transaction.currency_from.code} {formatNumber(transaction.amount_from)}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              TC: {formatNumber(transaction.exchange_rate, 4)}
            </Typography>
          </TableCell>
          <TableCell>
            <Typography variant="body2" fontWeight="medium">
              {formatCurrency(transaction.amount_to)}
            </Typography>
          </TableCell>
          <TableCell>{getStatusChip(transaction.status)}</TableCell>
          <TableCell>
            <Typography variant="caption">
              {format(new Date(transaction.created_at), 'dd/MM/yyyy HH:mm', { locale: es })}
            </Typography>
          </TableCell>
          <TableCell>
            <IconButton
              size="small"
              onClick={(e) => {
                setAnchorEl(e.currentTarget);
                setSelectedId(transaction.id);
              }}
            >
              <MoreVert />
            </IconButton>
          </TableCell>
        </TableRow>
        <TableRow>
          <TableCell style={{ paddingBottom: 0, paddingTop: 0 }} colSpan={9}>
            <Collapse in={open} timeout="auto" unmountOnExit>
              <Box sx={{ margin: 2 }}>
                <Grid container spacing={2}>
                  <Grid xs={12} md={4}>
                    <Card variant="outlined">
                      <CardContent>
                        <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                          Información del Cliente
                        </Typography>
                        <Typography variant="body2">
                          {transaction.customer.full_name}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {transaction.customer.document_number}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                  <Grid xs={12} md={4}>
                    <Card variant="outlined">
                      <CardContent>
                        <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                          Detalles de Pago
                        </Typography>
                        <Typography variant="body2">
                          Método: {transaction.payment_method}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          Cajero: {transaction.cashier.first_name} {transaction.cashier.last_name}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                  <Grid xs={12} md={4}>
                    <Card variant="outlined">
                      <CardContent>
                        <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                          Acciones
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 1 }}>
                          <Button
                            size="small"
                            startIcon={<Print />}
                            onClick={() => handlePrintReceipt(transaction.id)}
                          >
                            Imprimir
                          </Button>
                          {user?.role === 'ADMIN' && transaction.status === 'COMPLETED' && (
                            <Button
                              size="small"
                              color="error"
                              startIcon={<Cancel />}
                              onClick={() => handleReverse(transaction.id)}
                            >
                              Reversar
                            </Button>
                          )}
                        </Box>
                      </CardContent>
                    </Card>
                  </Grid>
                </Grid>
              </Box>
            </Collapse>
          </TableCell>
        </TableRow>
      </>
    );
  };

  return (
    <Box>
      <Paper sx={{ mb: 2, p: 2 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid xs={12} md={6}>
            <TextField
              fullWidth
              variant="outlined"
              placeholder="Buscar por número, cliente o documento..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Search />
                  </InputAdornment>
                ),
              }}
            />
          </Grid>
          <Grid xs={12} md={6}>
            <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
              <Button
                variant="outlined"
                startIcon={<FilterList />}
              >
                Filtros
              </Button>
            </Box>
          </Grid>
        </Grid>
      </Paper>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell />
              <TableCell>Número</TableCell>
              <TableCell>Cliente</TableCell>
              <TableCell>Tipo</TableCell>
              <TableCell>Monto</TableCell>
              <TableCell>Total BOB</TableCell>
              <TableCell>Estado</TableCell>
              <TableCell>Fecha</TableCell>
              <TableCell>Acciones</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {transactions.map((transaction) => (
              <Row key={transaction.id} transaction={transaction} />
            ))}
          </TableBody>
        </Table>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50]}
          component="div"
          count={totalCount}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={(_, newPage) => setPage(newPage)}
          onRowsPerPageChange={(e) => {
            setRowsPerPage(parseInt(e.target.value, 10));
            setPage(0);
          }}
          labelRowsPerPage="Filas por página"
        />
      </TableContainer>

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={() => {
          setAnchorEl(null);
          setSelectedId(null);
        }}
      >
        <MenuItem
          onClick={() => {
            if (selectedId) {
              const transaction = transactions.find((t) => t.id === selectedId);
              if (transaction) {
                setSelectedTransaction(transaction);
                setDetailsOpen(true);
              }
            }
            setAnchorEl(null);
          }}
        >
          <Receipt sx={{ mr: 1 }} fontSize="small" />
          Ver Detalles
        </MenuItem>
        <MenuItem
          onClick={() => {
            if (selectedId) handlePrintReceipt(selectedId);
            setAnchorEl(null);
          }}
        >
          <Print sx={{ mr: 1 }} fontSize="small" />
          Imprimir Comprobante
        </MenuItem>
      </Menu>

      {selectedTransaction && (
        <TransactionDetails
          open={detailsOpen}
          onClose={() => {
            setDetailsOpen(false);
            setSelectedTransaction(null);
          }}
          transaction={selectedTransaction}
        />
      )}
    </Box>
  );
};

export default TransactionList;