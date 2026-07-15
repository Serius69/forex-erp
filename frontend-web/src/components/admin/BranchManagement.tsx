import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Chip, IconButton,
  Tooltip, Button, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, Grid, Switch, FormControlLabel,
  Alert, CircularProgress,
} from '@mui/material';
import { Add, Edit, Block, Store, Star } from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { useFormik }   from 'formik';
import * as yup        from 'yup';
import { api }         from '../../services/api';

interface Branch {
  id:           number;
  name:         string;
  code:         string;
  city:         string;
  address:      string;
  phone:        string;
  is_main:      boolean;
  is_active:    boolean;
  company_name: string | null;
  created_at:   string;
}

const validationSchema = yup.object({
  name:    yup.string().required('Requerido').max(100),
  code:    yup.string().required('Requerido').max(10),
  city:    yup.string().max(100),
  address: yup.string().required('Requerido'),
  phone:   yup.string().required('Requerido').max(20),
  is_main: yup.boolean(),
});

const BranchManagement: React.FC = () => {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [selected, setSelected] = useState<Branch | null>(null);
  const { enqueueSnackbar }     = useSnackbar();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get('/users/branches/');
      setBranches(res.data.results ?? res.data);
    } catch (e: any) {
      setError('No se pudieron cargar las sucursales.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const formik = useFormik({
    initialValues: {
      name: '', code: '', city: '', address: '', phone: '', is_main: false,
    },
    validationSchema,
    enableReinitialize: true,
    onSubmit: async (values, { setSubmitting }) => {
      try {
        if (selected) {
          await api.patch(`/users/branches/${selected.id}/`, values);
          enqueueSnackbar('Sucursal actualizada', { variant: 'success' });
        } else {
          await api.post('/users/branches/', values);
          enqueueSnackbar('Sucursal creada', { variant: 'success' });
        }
        setFormOpen(false);
        load();
      } catch (e: any) {
        const detail =
          e?.response?.data?.code?.[0] ??
          e?.response?.data?.detail ??
          'No se pudo guardar la sucursal';
        enqueueSnackbar(detail, { variant: 'error' });
      } finally {
        setSubmitting(false);
      }
    },
  });

  const openCreate = () => {
    setSelected(null);
    formik.resetForm({
      values: { name: '', code: '', city: '', address: '', phone: '', is_main: false },
    });
    setFormOpen(true);
  };

  const openEdit = (b: Branch) => {
    setSelected(b);
    formik.resetForm({
      values: {
        name: b.name, code: b.code, city: b.city ?? '',
        address: b.address ?? '', phone: b.phone ?? '', is_main: b.is_main,
      },
    });
    setFormOpen(true);
  };

  const deactivate = async (b: Branch) => {
    if (b.is_main) {
      enqueueSnackbar('No se puede desactivar la sucursal principal', { variant: 'warning' });
      return;
    }
    if (!window.confirm(`¿Desactivar la sucursal "${b.name}"? Dejará de estar disponible.`)) return;
    try {
      await api.patch(`/users/branches/${b.id}/`, { is_active: false });
      enqueueSnackbar('Sucursal desactivada', { variant: 'success' });
      load();
    } catch {
      enqueueSnackbar('No se pudo desactivar la sucursal', { variant: 'error' });
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2, flexWrap: 'wrap', gap: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Store color="primary" />
          <Typography variant="h5" fontWeight="bold">Sucursales</Typography>
        </Box>
        <Button variant="contained" startIcon={<Add />} onClick={openCreate}>
          Nueva sucursal
        </Button>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Paper>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Nombre</TableCell>
                <TableCell>Código</TableCell>
                <TableCell>Ciudad</TableCell>
                <TableCell>Teléfono</TableCell>
                <TableCell>Tipo</TableCell>
                <TableCell align="right">Acciones</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={6} align="center" sx={{ py: 4 }}><CircularProgress size={28} /></TableCell></TableRow>
              ) : branches.length === 0 ? (
                <TableRow><TableCell colSpan={6} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                  No hay sucursales registradas.
                </TableCell></TableRow>
              ) : branches.map(b => (
                <TableRow key={b.id} hover>
                  <TableCell sx={{ fontWeight: 600 }}>{b.name}</TableCell>
                  <TableCell><Chip label={b.code} size="small" variant="outlined" /></TableCell>
                  <TableCell>{b.city || '—'}</TableCell>
                  <TableCell>{b.phone || '—'}</TableCell>
                  <TableCell>
                    {b.is_main
                      ? <Chip icon={<Star sx={{ fontSize: 14 }} />} label="Principal" size="small" color="primary" />
                      : <Chip label="Sucursal" size="small" />}
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title="Editar">
                      <IconButton size="small" onClick={() => openEdit(b)}><Edit fontSize="small" /></IconButton>
                    </Tooltip>
                    <Tooltip title={b.is_main ? 'No se puede desactivar la principal' : 'Desactivar'}>
                      <span>
                        <IconButton size="small" color="error" disabled={b.is_main} onClick={() => deactivate(b)}>
                          <Block fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Dialog open={formOpen} onClose={() => setFormOpen(false)} maxWidth="sm" fullWidth>
        <form onSubmit={formik.handleSubmit}>
          <DialogTitle>{selected ? 'Editar sucursal' : 'Nueva sucursal'}</DialogTitle>
          <DialogContent dividers>
            <Grid container spacing={2}>
              <Grid item xs={12} sm={8}>
                <TextField fullWidth label="Nombre" name="name"
                  value={formik.values.name} onChange={formik.handleChange}
                  error={formik.touched.name && !!formik.errors.name}
                  helperText={formik.touched.name && formik.errors.name} />
              </Grid>
              <Grid item xs={12} sm={4}>
                <TextField fullWidth label="Código" name="code"
                  value={formik.values.code} onChange={formik.handleChange}
                  error={formik.touched.code && !!formik.errors.code}
                  helperText={formik.touched.code && formik.errors.code} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField fullWidth label="Ciudad" name="city"
                  value={formik.values.city} onChange={formik.handleChange}
                  error={formik.touched.city && !!formik.errors.city}
                  helperText={formik.touched.city && formik.errors.city} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField fullWidth label="Teléfono" name="phone"
                  value={formik.values.phone} onChange={formik.handleChange}
                  error={formik.touched.phone && !!formik.errors.phone}
                  helperText={formik.touched.phone && formik.errors.phone} />
              </Grid>
              <Grid item xs={12}>
                <TextField fullWidth label="Dirección" name="address" multiline minRows={2}
                  value={formik.values.address} onChange={formik.handleChange}
                  error={formik.touched.address && !!formik.errors.address}
                  helperText={formik.touched.address && formik.errors.address} />
              </Grid>
              <Grid item xs={12}>
                <FormControlLabel
                  control={<Switch name="is_main" checked={formik.values.is_main} onChange={formik.handleChange} />}
                  label="Sucursal principal (matriz)"
                />
              </Grid>
            </Grid>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setFormOpen(false)}>Cancelar</Button>
            <Button type="submit" variant="contained" disabled={formik.isSubmitting}>
              {selected ? 'Guardar' : 'Crear'}
            </Button>
          </DialogActions>
        </form>
      </Dialog>
    </Box>
  );
};

export default BranchManagement;
