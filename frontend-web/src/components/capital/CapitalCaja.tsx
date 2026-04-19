/**
 * Entrada manual de capital — efectivo, QR y pasivos.
 * Funciona como una celda de Excel editable con historial de cambios.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, TextField, Button, Grid, Alert,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Chip, Divider, CircularProgress, Collapse, IconButton,
} from '@mui/material';
import { Save, History, ExpandMore, ExpandLess, Edit } from '@mui/icons-material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatBOB } from '../../utils/finance';

interface HistoryEntry {
  id: number;
  efectivo_bob_prev: string;
  qr_bob_prev: string;
  pasivos_bob_prev: string;
  efectivo_bob_new: string;
  qr_bob_new: string;
  pasivos_bob_new: string;
  motivo: string;
  modificado_por_nombre: string;
  created_at: string;
}

interface CajaEntry {
  id: number | null;
  fecha: string;
  efectivo_bob: string;
  qr_bob: string;
  pasivos_bob: string;
  notas: string;
  history: HistoryEntry[];
}

const CapitalCaja: React.FC = () => {
  const [entry,   setEntry]   = useState<CajaEntry | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving,  setSaving]  = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [form,    setForm]    = useState({
    efectivo_bob: '', qr_bob: '', pasivos_bob: '', notas: '', motivo: '',
  });
  const { enqueueSnackbar } = useSnackbar();

  const load = useCallback(async () => {
    try {
      const res = await api.get('/capital/caja/hoy/');
      setEntry(res.data);
      setForm({
        efectivo_bob: res.data.efectivo_bob ?? '0',
        qr_bob:       res.data.qr_bob       ?? '0',
        pasivos_bob:  res.data.pasivos_bob  ?? '0',
        notas:        res.data.notas        ?? '',
        motivo:       '',
      });
    } catch {
      enqueueSnackbar('Error al cargar caja', { variant: 'error' });
    }
  }, [enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        efectivo_bob: parseFloat(form.efectivo_bob) || 0,
        qr_bob:       parseFloat(form.qr_bob) || 0,
        pasivos_bob:  parseFloat(form.pasivos_bob) || 0,
        notas:        form.notas,
        motivo:       form.motivo,
      };

      if (!entry?.id) {
        await api.post('/capital/caja/', payload);
      } else {
        await api.patch(`/capital/caja/${entry.id}/`, payload);
      }

      enqueueSnackbar('Caja actualizada', { variant: 'success' });
      setEditing(false);
      load();
    } catch (err: any) {
      enqueueSnackbar(err?.response?.data?.error || 'Error al guardar', { variant: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const total = entry
    ? (parseFloat(entry.efectivo_bob) + parseFloat(entry.qr_bob) - parseFloat(entry.pasivos_bob))
    : 0;

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Box>
          <Typography variant="h6" fontWeight="bold">Caja del Día</Typography>
          <Typography variant="caption" color="text.secondary">
            {entry?.fecha
              ? format(new Date(entry.fecha + 'T12:00:00'), 'EEEE d MMMM yyyy', { locale: es })
              : '—'
            }
          </Typography>
        </Box>
        {!editing && (
          <Button startIcon={<Edit />} variant="outlined" size="small"
            onClick={() => setEditing(true)}>
            Editar
          </Button>
        )}
      </Box>

      {/* Vista de solo lectura */}
      {!editing && entry && (
        <Grid container spacing={2} mb={2}>
          {[
            { label: 'Efectivo físico', value: entry.efectivo_bob, color: 'success.main' },
            { label: 'QR / Digital',    value: entry.qr_bob,       color: 'info.main' },
            { label: 'Pasivos (−)',     value: entry.pasivos_bob,  color: 'error.main' },
          ].map(({ label, value, color }) => (
            <Grid item xs={12} sm={4} key={label}>
              <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                <Typography variant="caption" color="text.secondary" display="block">{label}</Typography>
                <Typography variant="h5" fontWeight="bold" color={color}>
                  {formatBOB(value)}
                </Typography>
              </Paper>
            </Grid>
          ))}
          <Grid item xs={12}>
            <Alert severity="info" sx={{ py: 0.5 }}>
              <strong>Total caja (sin divisas/tarjetas):</strong>{' '}
              <Typography component="span" fontWeight="bold">{formatBOB(total)}</Typography>
            </Alert>
          </Grid>
          {entry.notas && (
            <Grid item xs={12}>
              <Typography variant="body2" color="text.secondary">{entry.notas}</Typography>
            </Grid>
          )}
        </Grid>
      )}

      {/* Formulario de edición */}
      {editing && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}>
              <TextField
                fullWidth label="Efectivo físico BOB" type="number"
                value={form.efectivo_bob}
                onChange={e => setForm(f => ({ ...f, efectivo_bob: e.target.value }))}
                inputProps={{ step: '0.01', min: '0' }}
              />
            </Grid>
            <Grid item xs={12} sm={4}>
              <TextField
                fullWidth label="QR / Digital BOB" type="number"
                value={form.qr_bob}
                onChange={e => setForm(f => ({ ...f, qr_bob: e.target.value }))}
                inputProps={{ step: '0.01', min: '0' }}
              />
            </Grid>
            <Grid item xs={12} sm={4}>
              <TextField
                fullWidth label="Pasivos (deudas) BOB" type="number"
                value={form.pasivos_bob}
                onChange={e => setForm(f => ({ ...f, pasivos_bob: e.target.value }))}
                inputProps={{ step: '0.01', min: '0' }}
              />
            </Grid>
            <Grid item xs={12} sm={8}>
              <TextField
                fullWidth label="Notas" multiline rows={1}
                value={form.notas}
                onChange={e => setForm(f => ({ ...f, notas: e.target.value }))}
              />
            </Grid>
            <Grid item xs={12} sm={4}>
              <TextField
                fullWidth label="Motivo del cambio" required={!!entry?.id}
                value={form.motivo}
                onChange={e => setForm(f => ({ ...f, motivo: e.target.value }))}
                placeholder="Ej: Arqueo de caja"
              />
            </Grid>
            <Grid item xs={12}>
              <Box display="flex" gap={1} justifyContent="flex-end">
                <Button onClick={() => setEditing(false)} disabled={saving}>Cancelar</Button>
                <Button
                  variant="contained" startIcon={saving ? <CircularProgress size={16} /> : <Save />}
                  onClick={handleSave} disabled={saving}>
                  Guardar
                </Button>
              </Box>
            </Grid>
          </Grid>
        </Paper>
      )}

      {/* Historial */}
      {entry?.history && entry.history.length > 0 && (
        <Box>
          <Divider sx={{ my: 1.5 }} />
          <Box
            display="flex" alignItems="center" justifyContent="space-between"
            onClick={() => setShowHistory(h => !h)}
            sx={{ cursor: 'pointer' }}>
            <Box display="flex" alignItems="center" gap={0.5}>
              <History fontSize="small" color="action" />
              <Typography variant="subtitle2">
                Historial de cambios ({entry.history.length})
              </Typography>
            </Box>
            <IconButton size="small">
              {showHistory ? <ExpandLess /> : <ExpandMore />}
            </IconButton>
          </Box>

          <Collapse in={showHistory}>
            <TableContainer sx={{ mt: 1 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Fecha</TableCell>
                    <TableCell>Usuario</TableCell>
                    <TableCell align="right">Efectivo</TableCell>
                    <TableCell align="right">QR</TableCell>
                    <TableCell align="right">Pasivos</TableCell>
                    <TableCell>Motivo</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {entry.history.map(h => (
                    <TableRow key={h.id} hover>
                      <TableCell>
                        <Typography variant="caption">
                          {format(new Date(h.created_at), 'dd/MM HH:mm', { locale: es })}
                        </Typography>
                      </TableCell>
                      <TableCell>{h.modificado_por_nombre}</TableCell>
                      <TableCell align="right">
                        <Box>
                          <Typography variant="caption" color="text.disabled">
                            {formatBOB(h.efectivo_bob_prev)}
                          </Typography>
                          {' → '}
                          <Typography variant="caption" fontWeight="bold">
                            {formatBOB(h.efectivo_bob_new)}
                          </Typography>
                        </Box>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="caption" fontWeight="bold">
                          {formatBOB(h.qr_bob_new)}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="caption" fontWeight="bold">
                          {formatBOB(h.pasivos_bob_new)}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption" color="text.secondary">
                          {h.motivo || '—'}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Collapse>
        </Box>
      )}
    </Box>
  );
};

export default CapitalCaja;
