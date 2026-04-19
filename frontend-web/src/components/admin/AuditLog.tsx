/**
 * Log de auditoría del sistema — todas las acciones críticas de usuarios.
 * Solo visible para ADMIN / SUPERVISOR.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Chip, TextField, Grid, Button, Tooltip,
  Dialog, DialogTitle, DialogContent, DialogActions, LinearProgress,
} from '@mui/material';
import { Refresh, Search, Visibility } from '@mui/icons-material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

interface AuditEntry {
  id: number;
  user: string;
  action: string;
  details: Record<string, any>;
  ip_address: string;
  user_agent: string;
  created_at: string;
}

const ACTION_COLORS: Record<string, 'error' | 'warning' | 'success' | 'info' | 'default'> = {
  TRANSACTION_CREATED:   'success',
  TRANSACTION_EDITED:    'warning',
  TRANSACTION_REVERSED:  'warning',
  TRANSACTION_CANCELLED: 'error',
  LOGIN:                 'info',
  LOGOUT:                'default',
  CAPITAL_ENTRY_UPDATED: 'info',
};

const ACTION_LABELS: Record<string, string> = {
  TRANSACTION_CREATED:   'Transacción creada',
  TRANSACTION_EDITED:    'Transacción editada',
  TRANSACTION_REVERSED:  'Transacción revertida',
  TRANSACTION_CANCELLED: 'Transacción cancelada',
  LOGIN:                 'Inicio de sesión',
  LOGOUT:                'Cierre de sesión',
  CAPITAL_ENTRY_UPDATED: 'Capital actualizado',
};

const AuditLog: React.FC = () => {
  const [entries,     setEntries]     = useState<AuditEntry[]>([]);
  const [total,       setTotal]       = useState(0);
  const [loading,     setLoading]     = useState(true);
  const [page,        setPage]        = useState(1);
  const [selected,    setSelected]    = useState<AuditEntry | null>(null);
  const [filters,     setFilters]     = useState({
    search: '', action: '', date_from: '', date_to: '',
  });
  const { enqueueSnackbar } = useSnackbar();
  const PAGE_SIZE = 50;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, any> = {
        page, page_size: PAGE_SIZE,
      };
      if (filters.search)    params.search    = filters.search;
      if (filters.action)    params.action    = filters.action;
      if (filters.date_from) params.date_from = filters.date_from;
      if (filters.date_to)   params.date_to   = filters.date_to;

      const res = await api.get('/users/activities/', { params });
      const data = res.data;
      setEntries(data.results ?? data);
      setTotal(data.count ?? (data.results ?? data).length);
    } catch {
      enqueueSnackbar('Error al cargar log de auditoría', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar, page, filters]);

  useEffect(() => { load(); }, [load]);

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Box>
          <Typography variant="h5" fontWeight="bold">Log de Auditoría</Typography>
          <Typography variant="caption" color="text.secondary">
            {total} registros · Solo lectura · Inmutable
          </Typography>
        </Box>
        <Button startIcon={<Refresh />} variant="outlined" onClick={load} disabled={loading}>
          Actualizar
        </Button>
      </Box>

      {/* Filtros */}
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={4}>
            <TextField
              fullWidth size="small" label="Buscar usuario o acción"
              value={filters.search}
              onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
              InputProps={{ endAdornment: <Search fontSize="small" /> }}
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              fullWidth size="small" label="Desde" type="date"
              value={filters.date_from}
              onChange={e => setFilters(f => ({ ...f, date_from: e.target.value }))}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              fullWidth size="small" label="Hasta" type="date"
              value={filters.date_to}
              onChange={e => setFilters(f => ({ ...f, date_to: e.target.value }))}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={12} sm={2}>
            <Button fullWidth variant="contained" onClick={() => { setPage(1); load(); }}>
              Filtrar
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {loading && <LinearProgress sx={{ mb: 1, borderRadius: 1 }} />}

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Fecha/Hora</TableCell>
              <TableCell>Usuario</TableCell>
              <TableCell>Acción</TableCell>
              <TableCell>IP</TableCell>
              <TableCell>Detalle</TableCell>
              <TableCell>Ver</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {entries.map(entry => (
              <TableRow key={entry.id} hover>
                <TableCell>
                  <Typography variant="caption" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    {format(new Date(entry.created_at), 'dd/MM/yy HH:mm:ss', { locale: es })}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="body2" fontWeight="medium">
                    {entry.user}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    label={ACTION_LABELS[entry.action] ?? entry.action}
                    color={ACTION_COLORS[entry.action] ?? 'default'}
                    size="small"
                    sx={{ fontSize: '0.65rem' }}
                  />
                </TableCell>
                <TableCell>
                  <Typography variant="caption" color="text.secondary">
                    {entry.ip_address || '—'}
                  </Typography>
                </TableCell>
                <TableCell sx={{ maxWidth: 200 }}>
                  <Typography variant="caption" noWrap color="text.secondary">
                    {entry.details?.tx_number ?? entry.details?.reason ??
                     Object.values(entry.details ?? {})[0] ?? '—'}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Tooltip title="Ver detalles">
                    <Button size="small" onClick={() => setSelected(entry)}>
                      <Visibility fontSize="small" />
                    </Button>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}

            {!loading && entries.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} align="center">
                  <Typography color="text.secondary" py={3}>Sin registros</Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Paginación simple */}
      {total > PAGE_SIZE && (
        <Box display="flex" justifyContent="center" gap={1} mt={2}>
          <Button disabled={page === 1} onClick={() => setPage(p => p - 1)}>Anterior</Button>
          <Typography alignSelf="center">
            Página {page} de {Math.ceil(total / PAGE_SIZE)}
          </Typography>
          <Button disabled={page >= Math.ceil(total / PAGE_SIZE)} onClick={() => setPage(p => p + 1)}>
            Siguiente
          </Button>
        </Box>
      )}

      {/* Dialog de detalles */}
      <Dialog open={!!selected} onClose={() => setSelected(null)} maxWidth="sm" fullWidth>
        <DialogTitle>
          Detalle — {ACTION_LABELS[selected?.action ?? ''] ?? selected?.action}
        </DialogTitle>
        <DialogContent>
          {selected && (
            <Box>
              <Typography variant="body2" color="text.secondary" mb={2}>
                {format(new Date(selected.created_at), 'dd/MM/yyyy HH:mm:ss', { locale: es })}
                {' · '}{selected.user}
                {selected.ip_address ? ` · ${selected.ip_address}` : ''}
              </Typography>
              <Paper variant="outlined" sx={{ p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
                <pre style={{ margin: 0, fontSize: '0.75rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                  {JSON.stringify(selected.details, null, 2)}
                </pre>
              </Paper>
              {selected.user_agent && (
                <Typography variant="caption" color="text.disabled" display="block" mt={1}>
                  UA: {selected.user_agent}
                </Typography>
              )}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSelected(null)}>Cerrar</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default AuditLog;
