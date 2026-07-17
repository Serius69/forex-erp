// frontend-web/src/components/customers/Customers.tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Button, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TablePagination, TextField,
  InputAdornment, Chip, IconButton, Dialog, DialogTitle,
  DialogContent, DialogActions, Grid, FormControl, InputLabel,
  Select, MenuItem, Tooltip, Card, CardContent, Divider,
} from '@mui/material';
import {
  Add, Search, Edit, History, Person,
  Phone, Email, Badge,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { useFormik } from 'formik';
import * as yup from 'yup';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { api } from '../../services/api';
import { formatCurrency } from '../../utils/formatters';
import { useDebounce } from '../../hooks/useDebounce';

interface Customer {
  id:              number;
  document_type:   string;
  document_number: string;
  full_name:       string;
  phone:           string;
  email:           string;
  nationality:     string;
  is_pep:          boolean;
  is_frequent:     boolean;
  transaction_count: number;
  total_volume:    number;
  created_at:      string;
}

const validationSchema = yup.object({
  document_type:   yup.string().required('Requerido'),
  document_number: yup.string().required('Número de documento requerido'),
  full_name:       yup.string().required('Nombre requerido'),
  phone:           yup.string(),
  email:           yup.string().email('Email inválido'),
  nationality:     yup.string().required('Requerido'),
});

const Customers: React.FC = () => {
  const [customers,    setCustomers]    = useState<Customer[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [page,         setPage]         = useState(0);
  const [rowsPerPage,  setRowsPerPage]  = useState(10);
  const [total,        setTotal]        = useState(0);
  const [search,       setSearch]       = useState('');
  const debouncedSearch                 = useDebounce(search, 350);
  const [formOpen,     setFormOpen]     = useState(false);
  const [historyOpen,  setHistoryOpen]  = useState(false);
  const [selected,     setSelected]     = useState<Customer | null>(null);
  const [history,      setHistory]      = useState<any[]>([]);
  const { enqueueSnackbar } = useSnackbar();

  const loadCustomers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/customers/', {
        params: { page: page + 1, page_size: rowsPerPage, search: debouncedSearch || undefined },
      });
      setCustomers(res.data.results ?? res.data);
      setTotal(res.data.count ?? res.data.length);
    } catch {
      enqueueSnackbar('Error al cargar clientes', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, debouncedSearch, enqueueSnackbar]);

  useEffect(() => { loadCustomers(); }, [loadCustomers]);

  const loadHistory = async (customerId: number) => {
    try {
      const res = await api.get(`/customers/${customerId}/transactions/`);
      setHistory(res.data);
    } catch {
      enqueueSnackbar('Error al cargar historial', { variant: 'error' });
    }
  };

  const formik = useFormik({
    initialValues: {
      document_type: 'CI', document_number: '', full_name: '',
      phone: '', email: '', nationality: 'Boliviana', is_pep: false,
    },
    validationSchema,
    onSubmit: async (values) => {
      try {
        if (selected) {
          await api.patch(`/customers/${selected.id}/`, values);
          enqueueSnackbar('Cliente actualizado', { variant: 'success' });
        } else {
          await api.post('/customers/', values);
          enqueueSnackbar('Cliente registrado', { variant: 'success' });
        }
        setFormOpen(false);
        formik.resetForm();
        setSelected(null);
        loadCustomers();
      } catch (e: any) {
        enqueueSnackbar(e.response?.data?.document_number?.[0] || 'Error al guardar', { variant: 'error' });
      }
    },
  });

  const handleEdit = (customer: Customer) => {
    setSelected(customer);
    formik.setValues({
      document_type:   customer.document_type,
      document_number: customer.document_number,
      full_name:       customer.full_name,
      phone:           customer.phone   || '',
      email:           customer.email   || '',
      nationality:     customer.nationality,
      is_pep:          customer.is_pep,
    });
    setFormOpen(true);
  };

  const handleHistory = async (customer: Customer) => {
    setSelected(customer);
    await loadHistory(customer.id);
    setHistoryOpen(true);
  };

  const handleMarkFrequent = async (customer: Customer) => {
    try {
      await api.post(`/customers/${customer.id}/mark-frequent/`);
      enqueueSnackbar('Cliente marcado como frecuente', { variant: 'success' });
      loadCustomers();
    } catch {
      enqueueSnackbar('Error', { variant: 'error' });
    }
  };

  return (
    <Box>
      {/* ── Header ── */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight="bold">Clientes</Typography>
        <Button variant="contained" startIcon={<Add />}
          onClick={() => { setSelected(null); formik.resetForm(); setFormOpen(true); }}>
          Nuevo Cliente
        </Button>
      </Box>

      {/* ── Buscador ── */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <TextField
          fullWidth placeholder="Buscar por nombre, documento o teléfono..."
          value={search} onChange={(e) => setSearch(e.target.value)}
          InputProps={{ startAdornment: <InputAdornment position="start"><Search /></InputAdornment> }}
        />
      </Paper>

      {/* ── Tabla ── */}
      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Cliente</TableCell>
              <TableCell>Documento</TableCell>
              <TableCell>Contacto</TableCell>
              <TableCell>Transacciones</TableCell>
              <TableCell>Volumen Total</TableCell>
              <TableCell>Estado</TableCell>
              <TableCell>Acciones</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {customers.map((c) => (
              <TableRow key={c.id} hover>
                <TableCell>
                  <Box display="flex" alignItems="center" gap={1}>
                    <Person color="action" />
                    <Box>
                      <Typography variant="body2" fontWeight="medium">{c.full_name}</Typography>
                      <Typography variant="caption" color="text.secondary">{c.nationality}</Typography>
                    </Box>
                  </Box>
                </TableCell>
                <TableCell>
                  <Chip label={c.document_type} size="small" variant="outlined" sx={{ mr: 0.5 }} />
                  {c.document_number}
                </TableCell>
                <TableCell>
                  {c.phone && <Box display="flex" alignItems="center" gap={0.5}><Phone fontSize="small" /><Typography variant="caption">{c.phone}</Typography></Box>}
                  {c.email && <Box display="flex" alignItems="center" gap={0.5}><Email fontSize="small" /><Typography variant="caption">{c.email}</Typography></Box>}
                </TableCell>
                <TableCell>{c.transaction_count ?? 0}</TableCell>
                <TableCell>{formatCurrency(c.total_volume ?? 0)}</TableCell>
                <TableCell>
                  <Box display="flex" gap={0.5} flexWrap="wrap">
                    {c.is_pep      && <Chip label="PEP"       color="error"   size="small" />}
                    {c.is_frequent && <Chip label="Frecuente" color="success" size="small" />}
                    {!c.is_pep && !c.is_frequent && <Chip label="Regular" size="small" />}
                  </Box>
                </TableCell>
                <TableCell>
                  <Tooltip title="Editar"><IconButton size="small" onClick={() => handleEdit(c)}><Edit /></IconButton></Tooltip>
                  <Tooltip title="Historial"><IconButton size="small" onClick={() => handleHistory(c)}><History /></IconButton></Tooltip>
                  {!c.is_frequent && (
                    <Tooltip title="Marcar frecuente">
                      <IconButton size="small" onClick={() => handleMarkFrequent(c)}><Badge /></IconButton>
                    </Tooltip>
                  )}
                </TableCell>
              </TableRow>
            ))}
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

      {/* ── Formulario crear/editar ── */}
      <Dialog open={formOpen} onClose={() => setFormOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{selected ? 'Editar Cliente' : 'Nuevo Cliente'}</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={4}>
              <FormControl fullWidth>
                <InputLabel>Tipo Doc.</InputLabel>
                <Select name="document_type" value={formik.values.document_type} onChange={formik.handleChange} label="Tipo Doc.">
                  <MenuItem value="CI">CI</MenuItem>
                  <MenuItem value="NIT">NIT</MenuItem>
                  <MenuItem value="PASSPORT">Pasaporte</MenuItem>
                  <MenuItem value="RUC">RUC</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={8}>
              <TextField fullWidth label="Número de Documento" name="document_number"
                value={formik.values.document_number} onChange={formik.handleChange}
                error={formik.touched.document_number && Boolean(formik.errors.document_number)}
                helperText={formik.touched.document_number && formik.errors.document_number} />
            </Grid>
            <Grid item xs={12}>
              <TextField fullWidth label="Nombre Completo" name="full_name"
                value={formik.values.full_name} onChange={formik.handleChange}
                error={formik.touched.full_name && Boolean(formik.errors.full_name)}
                helperText={formik.touched.full_name && formik.errors.full_name} />
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Teléfono" name="phone"
                value={formik.values.phone} onChange={formik.handleChange} />
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Email" name="email" type="email"
                value={formik.values.email} onChange={formik.handleChange}
                error={formik.touched.email && Boolean(formik.errors.email)}
                helperText={formik.touched.email && formik.errors.email} />
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Nacionalidad" name="nationality"
                value={formik.values.nationality} onChange={formik.handleChange} />
            </Grid>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>PEP</InputLabel>
                <Select name="is_pep" value={formik.values.is_pep as any} onChange={formik.handleChange} label="PEP">
                  <MenuItem value={false as any}>No</MenuItem>
                  <MenuItem value={true as any}>Sí — Persona Expuesta Políticamente</MenuItem>
                </Select>
              </FormControl>
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFormOpen(false)}>Cancelar</Button>
          <Button variant="contained" onClick={() => formik.submitForm()}>
            {selected ? 'Actualizar' : 'Registrar'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* ── Historial de transacciones ── */}
      <Dialog open={historyOpen} onClose={() => setHistoryOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          Historial — {selected?.full_name}
        </DialogTitle>
        <DialogContent>
          {history.length === 0 ? (
            <Typography color="text.secondary" textAlign="center" py={4}>
              Sin transacciones registradas
            </Typography>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>N°</TableCell>
                  <TableCell>Tipo</TableCell>
                  <TableCell>Divisa</TableCell>
                  <TableCell>Monto</TableCell>
                  <TableCell>Total BOB</TableCell>
                  <TableCell>Fecha</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {history.map((tx: any) => (
                  <TableRow key={tx.id} hover>
                    <TableCell><Typography variant="caption" fontFamily="monospace">{tx.transaction_number}</Typography></TableCell>
                    <TableCell>
                      <Chip label={tx.transaction_type === 'BUY' ? 'Compra' : 'Venta'}
                        color={tx.transaction_type === 'BUY' ? 'success' : 'warning'} size="small" />
                    </TableCell>
                    <TableCell>{tx.currency_from?.code}</TableCell>
                    <TableCell>{formatCurrency(tx.amount_from, tx.currency_from?.code)}</TableCell>
                    <TableCell><Typography fontWeight="bold">{formatCurrency(tx.amount_to)}</Typography></TableCell>
                    <TableCell>
                      <Typography variant="caption">
                        {format(new Date(tx.created_at), 'dd/MM/yyyy HH:mm', { locale: es })}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setHistoryOpen(false)}>Cerrar</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Customers;