/**
 * Panel de mantenimiento del sistema Kapitalya.
 * Solo visible para ADMIN.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, Button, TextField, Alert, Chip,
  Card, CardContent, CardActions, Divider, Grid, CircularProgress,
  Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material';
import {
  Build, ClearAll, Refresh, Warning, CheckCircle, Block,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

interface MaintenanceInfo {
  maintenance_active: boolean;
  info: {
    activated_by: string;
    reason: string;
    activated_at: string;
  } | null;
  server_time: string;
}

const MaintenancePanel: React.FC = () => {
  const [data,      setData]      = useState<MaintenanceInfo | null>(null);
  const [loading,   setLoading]   = useState(false);
  const [reason,    setReason]    = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<'activate' | 'deactivate' | null>(null);
  const { enqueueSnackbar } = useSnackbar();

  const load = useCallback(async () => {
    try {
      const res = await api.get('/maintenance/');
      setData(res.data);
    } catch {
      enqueueSnackbar('Error al obtener estado del sistema', { variant: 'error' });
    }
  }, [enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const handleToggle = async () => {
    if (!pendingAction) return;
    if (pendingAction === 'activate' && !reason.trim()) {
      enqueueSnackbar('Debe indicar el motivo del mantenimiento', { variant: 'warning' });
      return;
    }
    setLoading(true);
    try {
      await api.post('/maintenance/toggle/', {
        action: pendingAction,
        reason: reason.trim(),
      });
      enqueueSnackbar(
        pendingAction === 'activate'
          ? 'Modo mantenimiento ACTIVADO'
          : 'Modo mantenimiento DESACTIVADO',
        { variant: pendingAction === 'activate' ? 'warning' : 'success' }
      );
      setConfirmOpen(false);
      setReason('');
      load();
    } catch (err: any) {
      enqueueSnackbar(err?.response?.data?.error || 'Error al cambiar estado', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleClearCache = async () => {
    setLoading(true);
    try {
      await api.post('/maintenance/clear-cache/');
      enqueueSnackbar('Cache limpiado exitosamente', { variant: 'success' });
    } catch {
      enqueueSnackbar('Error al limpiar cache', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleRecalculate = async () => {
    setLoading(true);
    try {
      const res = await api.post('/maintenance/recalculate/');
      const { steps, errors } = res.data;
      if (errors?.length) {
        enqueueSnackbar(`Recálculo con ${errors.length} error(es)`, { variant: 'warning' });
      } else {
        enqueueSnackbar(`Recálculo completado: ${steps?.length} pasos`, { variant: 'success' });
      }
    } catch {
      enqueueSnackbar('Error al recalcular', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const active = data?.maintenance_active;

  return (
    <Box>
      <Typography variant="h5" fontWeight="bold" mb={2}>Panel de Mantenimiento</Typography>

      {/* Estado actual */}
      <Card variant="outlined" sx={{ mb: 3, borderColor: active ? 'error.main' : 'success.main' }}>
        <CardContent>
          <Box display="flex" alignItems="center" gap={1.5} mb={1}>
            {active
              ? <Warning color="error" />
              : <CheckCircle color="success" />
            }
            <Typography variant="h6" fontWeight="bold">
              Estado del Sistema: {' '}
              <Chip
                label={active ? 'MANTENIMIENTO ACTIVO' : 'OPERATIVO'}
                color={active ? 'error' : 'success'}
                size="small"
              />
            </Typography>
          </Box>

          {active && data?.info && (
            <Box mt={1}>
              <Alert severity="error" icon={<Block />}>
                <strong>Motivo:</strong> {data.info.reason}<br/>
                <strong>Activado por:</strong> {data.info.activated_by}<br/>
                <strong>Desde:</strong> {new Date(data.info.activated_at).toLocaleString('es-BO')}
              </Alert>
            </Box>
          )}

          {data?.server_time && (
            <Typography variant="caption" color="text.secondary" display="block" mt={1}>
              Hora del servidor: {new Date(data.server_time).toLocaleString('es-BO')}
            </Typography>
          )}
        </CardContent>

        <CardActions sx={{ px: 2, pb: 2 }}>
          {!active ? (
            <Button
              variant="contained" color="error" startIcon={<Build />}
              onClick={() => { setPendingAction('activate'); setConfirmOpen(true); }}
              disabled={loading}>
              Activar Mantenimiento
            </Button>
          ) : (
            <Button
              variant="contained" color="success" startIcon={<CheckCircle />}
              onClick={() => { setPendingAction('deactivate'); setConfirmOpen(true); }}
              disabled={loading}>
              Desactivar Mantenimiento
            </Button>
          )}
          <Button variant="outlined" startIcon={<Refresh />} onClick={load} disabled={loading}>
            Actualizar estado
          </Button>
        </CardActions>
      </Card>

      {/* Operaciones */}
      <Typography variant="subtitle1" fontWeight="bold" mb={1.5}>Operaciones del Sistema</Typography>
      <Grid container spacing={2}>
        <Grid item xs={12} sm={6}>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Box display="flex" alignItems="center" gap={1} mb={1}>
              <ClearAll color="warning" />
              <Typography fontWeight="medium">Limpiar Cache</Typography>
            </Box>
            <Typography variant="body2" color="text.secondary" mb={2}>
              Vacía la cache de tasas de cambio, arbitraje y datos calculados.
              Fuerza recarga de datos frescos en la próxima consulta.
            </Typography>
            <Button
              variant="outlined" color="warning" startIcon={<ClearAll />}
              onClick={handleClearCache} disabled={loading}>
              Limpiar Cache
            </Button>
          </Paper>
        </Grid>

        <Grid item xs={12} sm={6}>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Box display="flex" alignItems="center" gap={1} mb={1}>
              <Refresh color="info" />
              <Typography fontWeight="medium">Recalcular Sistema</Typography>
            </Box>
            <Typography variant="body2" color="text.secondary" mb={2}>
              Recalcula el WAC (costo promedio ponderado) del inventario y
              verifica la consistencia entre transacciones e inventario.
            </Typography>
            <Button
              variant="outlined" color="info" startIcon={<Refresh />}
              onClick={handleRecalculate} disabled={loading}>
              {loading ? <CircularProgress size={18} sx={{ mr: 1 }} /> : null}
              Recalcular
            </Button>
          </Paper>
        </Grid>
      </Grid>

      {/* Dialog de confirmación */}
      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {pendingAction === 'activate'
            ? 'Activar Modo Mantenimiento'
            : 'Desactivar Modo Mantenimiento'
          }
        </DialogTitle>
        <DialogContent>
          {pendingAction === 'activate' ? (
            <>
              <Alert severity="warning" sx={{ mb: 2 }}>
                Al activar el modo mantenimiento, los cajeros NO podrán registrar
                transacciones hasta que lo desactives.
              </Alert>
              <TextField
                fullWidth
                multiline
                rows={2}
                label="Motivo del mantenimiento *"
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder="Ej: Actualización del sistema, corrección de datos..."
              />
            </>
          ) : (
            <Alert severity="info">
              El sistema volverá a estar operativo para todos los usuarios.
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>Cancelar</Button>
          <Button
            variant="contained"
            color={pendingAction === 'activate' ? 'error' : 'success'}
            onClick={handleToggle}
            disabled={loading || (pendingAction === 'activate' && !reason.trim())}>
            {pendingAction === 'activate' ? 'Activar' : 'Desactivar'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default MaintenancePanel;
