import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Chip, Button,
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Grid, IconButton, Tooltip, Card, CardContent,
} from '@mui/material';
import { Refresh, Edit, TrendingUp, TrendingDown } from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { useFormik } from 'formik';
import * as yup from 'yup';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';

const Rates: React.FC = () => {
  const [rates,      setRates]      = useState<any[]>([]);
  const [currencies, setCurrencies] = useState<any[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [editOpen,   setEditOpen]   = useState(false);
  const [selected,   setSelected]   = useState<any>(null);
  const { user }                    = useAuth();
  const { enqueueSnackbar }         = useSnackbar();

  const loadRates = useCallback(async () => {
    setLoading(true);
    try {
      const [ratesRes, currRes] = await Promise.all([
        api.get('/rates/exchange-rates/'),
        api.get('/rates/currencies/'),
      ]);
      setRates(ratesRes.data.results ?? ratesRes.data);
      setCurrencies(currRes.data.results ?? currRes.data);
    } catch {
      enqueueSnackbar('Error al cargar tasas', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => { loadRates(); }, [loadRates]);

  const handleUpdateFromBCB = async () => {
    try {
      await api.post('/rates/exchange-rates/update_rates/', { source: 'BCB' });
      enqueueSnackbar('Tasas actualizadas desde BCB', { variant: 'success' });
      loadRates();
    } catch {
      enqueueSnackbar('Error al actualizar tasas', { variant: 'error' });
    }
  };

  const formik = useFormik({
    initialValues: { buy_rate: '', sell_rate: '', official_rate: '' },
    validationSchema: yup.object({
      buy_rate:      yup.number().min(0.0001).required('Requerido'),
      sell_rate:     yup.number().min(0.0001).required('Requerido'),
      official_rate: yup.number().min(0.0001).required('Requerido'),
    }),
    onSubmit: async (values) => {
      try {
        await api.patch(`/rates/exchange-rates/${selected.id}/`, {
          ...values,
          valid_from: new Date().toISOString(),
        });
        enqueueSnackbar('Tasa actualizada', { variant: 'success' });
        setEditOpen(false);
        loadRates();
      } catch {
        enqueueSnackbar('Error al actualizar', { variant: 'error' });
      }
    },
  });

  const handleEdit = (rate: any) => {
    setSelected(rate);
    formik.setValues({
      buy_rate:      rate.buy_rate,
      sell_rate:     rate.sell_rate,
      official_rate: rate.official_rate,
    });
    setEditOpen(true);
  };

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight="bold">Tasas de Cambio</Typography>
        <Box display="flex" gap={1}>
          {user?.role === 'ADMIN' && (
            <Button variant="outlined" startIcon={<Refresh />} onClick={handleUpdateFromBCB}>
              Actualizar desde BCB
            </Button>
          )}
          <Button variant="outlined" startIcon={<Refresh />} onClick={loadRates}>
            Recargar
          </Button>
        </Box>
      </Box>

      {/* ── KPI Cards ── */}
      <Grid container spacing={2} mb={3}>
        {rates.slice(0, 4).map((rate) => (
          <Grid xs={12} sm={6} md={3} key={rate.id}>
            <Card>
              <CardContent>
                <Typography variant="h6" color="primary">
                  {rate.currency_from?.code} / {rate.currency_to?.code}
                </Typography>
                <Box display="flex" justifyContent="space-between" mt={1}>
                  <Box>
                    <Typography variant="caption" color="text.secondary">Compra</Typography>
                    <Typography variant="h6" color="success.main">{rate.buy_rate}</Typography>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary">Venta</Typography>
                    <Typography variant="h6" color="error.main">{rate.sell_rate}</Typography>
                  </Box>
                </Box>
                <Typography variant="caption" color="text.secondary">
                  Spread: {rate.spread_percentage}%
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* ── Tabla completa ── */}
      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Par</TableCell>
              <TableCell align="right">Oficial</TableCell>
              <TableCell align="right">Compra</TableCell>
              <TableCell align="right">Venta</TableCell>
              <TableCell align="right">Spread</TableCell>
              <TableCell>Fuente</TableCell>
              <TableCell>Válido desde</TableCell>
              <TableCell>Estado</TableCell>
              {user?.role === 'ADMIN' && <TableCell>Acciones</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {rates.map((rate) => (
              <TableRow key={rate.id} hover>
                <TableCell>
                  <Typography fontWeight="bold">
                    {rate.currency_from?.code} / {rate.currency_to?.code}
                  </Typography>
                </TableCell>
                <TableCell align="right">{parseFloat(rate.official_rate).toFixed(4)}</TableCell>
                <TableCell align="right">
                  <Typography color="success.main" fontWeight="medium">
                    {parseFloat(rate.buy_rate).toFixed(4)}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography color="error.main" fontWeight="medium">
                    {parseFloat(rate.sell_rate).toFixed(4)}
                  </Typography>
                </TableCell>
                <TableCell align="right">{rate.spread_percentage}%</TableCell>
                <TableCell><Chip label={rate.source} size="small" /></TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {format(new Date(rate.valid_from), 'dd/MM/yyyy HH:mm', { locale: es })}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    label={rate.valid_until ? 'Vencida' : 'Vigente'}
                    color={rate.valid_until ? 'default' : 'success'}
                    size="small"
                  />
                </TableCell>
                {user?.role === 'ADMIN' && (
                  <TableCell>
                    <Tooltip title="Editar tasa">
                      <IconButton size="small" onClick={() => handleEdit(rate)}>
                        <Edit />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* ── Dialog editar ── */}
      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>
          Editar Tasa — {selected?.currency_from?.code}/{selected?.currency_to?.code}
        </DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid xs={12}>
              <TextField fullWidth label="Tasa Oficial" name="official_rate" type="number"
                value={formik.values.official_rate} onChange={formik.handleChange}
                error={formik.touched.official_rate && Boolean(formik.errors.official_rate)} />
            </Grid>
            <Grid xs={6}>
              <TextField fullWidth label="Tasa Compra" name="buy_rate" type="number"
                value={formik.values.buy_rate} onChange={formik.handleChange}
                error={formik.touched.buy_rate && Boolean(formik.errors.buy_rate)} />
            </Grid>
            <Grid xs={6}>
              <TextField fullWidth label="Tasa Venta" name="sell_rate" type="number"
                value={formik.values.sell_rate} onChange={formik.handleChange}
                error={formik.touched.sell_rate && Boolean(formik.errors.sell_rate)} />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancelar</Button>
          <Button variant="contained" onClick={() => formik.submitForm()}>Guardar</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Rates;