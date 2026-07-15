// src/components/reports/ROUEReports.tsx
// ROUE — Reporte de Operaciones Inusuales o Sospechosas (ASFI / SAR)
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Button, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Chip, IconButton, Tooltip,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField,
  Grid, FormControl, InputLabel, Select, MenuItem, Alert,
  CircularProgress, Autocomplete,
} from '@mui/material';
import { Add, PictureAsPdf, ReportProblem } from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { useFormik } from 'formik';
import * as yup from 'yup';
import { api, downloadFile } from '../../services/api';

interface Customer { id: number; full_name?: string; first_name?: string; last_name?: string; document_number?: string; }
interface ROUE {
  id: number; report_number: string; report_type: string; risk_level: string;
  status: string; amount_involved: string; currency_involved: string;
  description: string; detected_at: string;
  customer: { id: number; full_name?: string; first_name?: string; last_name?: string } | null;
}

const RISK_COLOR: Record<string, any> = { LOW: 'success', MEDIUM: 'info', HIGH: 'warning', CRITICAL: 'error' };
const RISK_LABEL: Record<string, string> = { LOW: 'Bajo', MEDIUM: 'Medio', HIGH: 'Alto', CRITICAL: 'Crítico' };
const STATUS_LABEL: Record<string, string> = { DRAFT: 'Borrador', REVIEW: 'En Revisión', SUBMITTED: 'Enviado', CLOSED: 'Cerrado' };
const TYPE_LABEL: Record<string, string> = { UNUSUAL: 'Inusual', SUSPICIOUS: 'Sospechosa' };

const custLabel = (c: Customer) =>
  `${c.full_name ?? [c.first_name, c.last_name].filter(Boolean).join(' ') ?? 'Cliente'}${c.document_number ? ` · ${c.document_number}` : ''}`;

const validationSchema = yup.object({
  customer_id:       yup.number().required('Seleccione un cliente'),
  report_type:       yup.string().required('Requerido'),
  risk_level:        yup.string().required('Requerido'),
  description:       yup.string().required('Describa la operación').min(10, 'Mínimo 10 caracteres'),
  amount_involved:   yup.number().min(0).required('Requerido'),
  currency_involved: yup.string().required('Requerido'),
});

const ROUEReports: React.FC = () => {
  const [rows, setRows]         = useState<ROUE[]>([]);
  const [loading, setLoading]   = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [pdfBusy, setPdfBusy]   = useState<number | null>(null);
  const { enqueueSnackbar }     = useSnackbar();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/reports/asfi/roue/');
      setRows(res.data.results ?? res.data);
    } catch {
      enqueueSnackbar('No se pudieron cargar los reportes ROUE', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const loadCustomers = useCallback(async () => {
    try {
      const res = await api.get('/customers/', { params: { page_size: 200 } });
      setCustomers(res.data.results ?? res.data);
    } catch { /* silent — form still usable if empty */ }
  }, []);

  const formik = useFormik({
    initialValues: {
      customer_id: null as number | null,
      report_type: 'UNUSUAL',
      risk_level:  'MEDIUM',
      description: '',
      indicators:  '',
      amount_involved:   '',
      currency_involved: 'USD',
    },
    validationSchema,
    onSubmit: async (values, { setSubmitting }) => {
      try {
        await api.post('/reports/asfi/roue/', {
          customer_id:       values.customer_id,
          report_type:       values.report_type,
          risk_level:        values.risk_level,
          description:       values.description,
          amount_involved:   values.amount_involved,
          currency_involved: values.currency_involved,
          indicators: values.indicators
            ? values.indicators.split(',').map(s => s.trim()).filter(Boolean)
            : [],
        });
        enqueueSnackbar('Reporte ROUE creado', { variant: 'success' });
        setFormOpen(false);
        load();
      } catch (e: any) {
        enqueueSnackbar(e?.response?.data?.detail ?? 'No se pudo crear el reporte', { variant: 'error' });
      } finally {
        setSubmitting(false);
      }
    },
  });

  const openForm = () => {
    formik.resetForm();
    loadCustomers();
    setFormOpen(true);
  };

  const downloadPdf = async (r: ROUE) => {
    setPdfBusy(r.id);
    try {
      const res = await api.get(`/reports/asfi/roue/${r.id}/download-pdf/`, { responseType: 'blob' });
      downloadFile(res.data, `ROUE_${r.report_number}.pdf`);
      enqueueSnackbar('PDF descargado', { variant: 'success' });
    } catch {
      enqueueSnackbar('Error al generar el PDF', { variant: 'error' });
    } finally {
      setPdfBusy(null);
    }
  };

  const custName = (c: ROUE['customer']) =>
    c ? (c.full_name ?? [c.first_name, c.last_name].filter(Boolean).join(' ') ?? `#${c.id}`) : '—';

  return (
    <Paper sx={{ p: 2, mt: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5, flexWrap: 'wrap', gap: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <ReportProblem color="error" />
          <Typography variant="subtitle1" fontWeight="bold">
            ROUE — Operaciones Inusuales / Sospechosas
          </Typography>
        </Box>
        <Button variant="contained" size="small" startIcon={<Add />} onClick={openForm}>
          Nuevo reporte
        </Button>
      </Box>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Reportes de operaciones inusuales o sospechosas (ROS/SAR) para la Unidad de Investigaciones Financieras — ASFI.
      </Typography>

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>N.º</TableCell>
              <TableCell>Cliente</TableCell>
              <TableCell>Tipo</TableCell>
              <TableCell>Riesgo</TableCell>
              <TableCell>Estado</TableCell>
              <TableCell align="right">Monto</TableCell>
              <TableCell align="right">PDF</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={7} align="center" sx={{ py: 3 }}><CircularProgress size={24} /></TableCell></TableRow>
            ) : rows.length === 0 ? (
              <TableRow><TableCell colSpan={7} align="center" sx={{ py: 3, color: 'text.secondary' }}>
                No hay reportes ROUE registrados.
              </TableCell></TableRow>
            ) : rows.map(r => (
              <TableRow key={r.id} hover>
                <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{r.report_number}</TableCell>
                <TableCell>{custName(r.customer)}</TableCell>
                <TableCell>{TYPE_LABEL[r.report_type] ?? r.report_type}</TableCell>
                <TableCell><Chip size="small" color={RISK_COLOR[r.risk_level] ?? 'default'} label={RISK_LABEL[r.risk_level] ?? r.risk_level} /></TableCell>
                <TableCell><Chip size="small" variant="outlined" label={STATUS_LABEL[r.status] ?? r.status} /></TableCell>
                <TableCell align="right">{r.currency_involved} {Number(r.amount_involved).toLocaleString()}</TableCell>
                <TableCell align="right">
                  <Tooltip title="Descargar PDF">
                    <IconButton size="small" color="error" disabled={pdfBusy === r.id} onClick={() => downloadPdf(r)}>
                      {pdfBusy === r.id ? <CircularProgress size={16} /> : <PictureAsPdf fontSize="small" />}
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Create dialog */}
      <Dialog open={formOpen} onClose={() => setFormOpen(false)} maxWidth="sm" fullWidth>
        <form onSubmit={formik.handleSubmit}>
          <DialogTitle>Nuevo reporte ROUE</DialogTitle>
          <DialogContent dividers>
            {customers.length === 0 && (
              <Alert severity="info" sx={{ mb: 2 }}>
                No hay clientes registrados. Registre primero un cliente para asociar el reporte.
              </Alert>
            )}
            <Grid container spacing={2}>
              <Grid item xs={12}>
                <Autocomplete
                  options={customers}
                  getOptionLabel={custLabel}
                  onChange={(_, v) => formik.setFieldValue('customer_id', v?.id ?? null)}
                  renderInput={(params) => (
                    <TextField {...params} label="Cliente"
                      error={formik.touched.customer_id && !!formik.errors.customer_id}
                      helperText={formik.touched.customer_id && formik.errors.customer_id} />
                  )}
                />
              </Grid>
              <Grid item xs={12} sm={6}>
                <FormControl fullWidth>
                  <InputLabel>Tipo</InputLabel>
                  <Select name="report_type" label="Tipo" value={formik.values.report_type} onChange={formik.handleChange}>
                    <MenuItem value="UNUSUAL">Operación Inusual</MenuItem>
                    <MenuItem value="SUSPICIOUS">Operación Sospechosa</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6}>
                <FormControl fullWidth>
                  <InputLabel>Nivel de riesgo</InputLabel>
                  <Select name="risk_level" label="Nivel de riesgo" value={formik.values.risk_level} onChange={formik.handleChange}>
                    <MenuItem value="LOW">Bajo</MenuItem>
                    <MenuItem value="MEDIUM">Medio</MenuItem>
                    <MenuItem value="HIGH">Alto</MenuItem>
                    <MenuItem value="CRITICAL">Crítico</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={8}>
                <TextField fullWidth label="Monto involucrado" type="number" name="amount_involved"
                  value={formik.values.amount_involved} onChange={formik.handleChange}
                  error={formik.touched.amount_involved && !!formik.errors.amount_involved}
                  helperText={formik.touched.amount_involved && formik.errors.amount_involved} />
              </Grid>
              <Grid item xs={4}>
                <FormControl fullWidth>
                  <InputLabel>Moneda</InputLabel>
                  <Select name="currency_involved" label="Moneda" value={formik.values.currency_involved} onChange={formik.handleChange}>
                    {['USD', 'BOB', 'EUR', 'BRL', 'ARS', 'PEN', 'CLP'].map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12}>
                <TextField fullWidth label="Descripción de la operación" name="description" multiline minRows={3}
                  value={formik.values.description} onChange={formik.handleChange}
                  error={formik.touched.description && !!formik.errors.description}
                  helperText={formik.touched.description && formik.errors.description} />
              </Grid>
              <Grid item xs={12}>
                <TextField fullWidth label="Indicadores (separados por coma)" name="indicators"
                  placeholder="fraccionamiento, PEP, efectivo alto"
                  value={formik.values.indicators} onChange={formik.handleChange} />
              </Grid>
            </Grid>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setFormOpen(false)}>Cancelar</Button>
            <Button type="submit" variant="contained" disabled={formik.isSubmitting}>Crear reporte</Button>
          </DialogActions>
        </form>
      </Dialog>
    </Paper>
  );
};

export default ROUEReports;
