import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Button, Paper,
  Table, TableHead, TableBody, TableRow, TableCell, TableContainer,
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, MenuItem, IconButton, Chip, CircularProgress, Tooltip,
} from '@mui/material';
import {
  Add, Edit, Delete, Refresh,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import api from '../../services/api';

// ─── Types ────────────────────────────────────────────────────────────────────

type CardStatus = 'ACTIVE' | 'INACTIVE' | 'BLOCKED';

interface InventoryCard {
  id: number;
  currency: string;
  amount: string;
  status: CardStatus;
  created_at: string;
  updated_at: string;
}

interface CardForm {
  currency: string;
  amount: string;
  status: CardStatus;
}

const EMPTY_FORM: CardForm = { currency: '', amount: '', status: 'ACTIVE' };

const STATUS_LABELS: Record<CardStatus, string> = {
  ACTIVE:   'Activa',
  INACTIVE: 'Inactiva',
  BLOCKED:  'Bloqueada',
};

const STATUS_COLORS: Record<CardStatus, 'success' | 'default' | 'error'> = {
  ACTIVE:   'success',
  INACTIVE: 'default',
  BLOCKED:  'error',
};

// ─── Component ────────────────────────────────────────────────────────────────

const InventoryCards: React.FC = () => {
  const { enqueueSnackbar } = useSnackbar();

  const [cards, setCards]         = useState<InventoryCard[]>([]);
  const [loading, setLoading]     = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedCard, setSelectedCard] = useState<InventoryCard | null>(null);
  const [form, setForm]           = useState<CardForm>(EMPTY_FORM);
  const [saving, setSaving]       = useState(false);

  // ── Data load ───────────────────────────────────────────────────────────────

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/inventory/cards/');
      const data = res.data;
      setCards(Array.isArray(data) ? data : (data.results ?? []));
    } catch {
      enqueueSnackbar('Error al cargar las tarjetas', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  // ── Dialog helpers ──────────────────────────────────────────────────────────

  const openCreate = () => {
    setSelectedCard(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  };

  const openEdit = (card: InventoryCard) => {
    setSelectedCard(card);
    setForm({ currency: card.currency, amount: card.amount, status: card.status });
    setDialogOpen(true);
  };

  const openDelete = (card: InventoryCard) => {
    setSelectedCard(card);
    setDeleteDialogOpen(true);
  };

  const closeDialog = () => {
    setDialogOpen(false);
    setSelectedCard(null);
  };

  // ── CRUD handlers ───────────────────────────────────────────────────────────

  const handleSave = async () => {
    if (!form.currency.trim() || !form.amount) {
      enqueueSnackbar('Divisa y monto son obligatorios', { variant: 'warning' });
      return;
    }
    setSaving(true);
    try {
      if (selectedCard) {
        await api.put(`/inventory/cards/${selectedCard.id}/`, form);
        enqueueSnackbar('Tarjeta actualizada', { variant: 'success' });
      } else {
        await api.post('/inventory/cards/', form);
        enqueueSnackbar('Tarjeta creada', { variant: 'success' });
      }
      closeDialog();
      load();
    } catch (err: any) {
      const msg = err?.response?.data
        ? JSON.stringify(err.response.data)
        : 'Error al guardar';
      enqueueSnackbar(msg, { variant: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedCard) return;
    setSaving(true);
    try {
      await api.delete(`/inventory/cards/${selectedCard.id}/`);
      enqueueSnackbar('Tarjeta eliminada', { variant: 'success' });
      setDeleteDialogOpen(false);
      setSelectedCard(null);
      load();
    } catch {
      enqueueSnackbar('Error al eliminar la tarjeta', { variant: 'error' });
    } finally {
      setSaving(false);
    }
  };

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <Box>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6" fontWeight="bold">Tarjetas de Inventario</Typography>
        <Box display="flex" gap={1}>
          <Tooltip title="Actualizar">
            <IconButton onClick={load} disabled={loading}>
              <Refresh />
            </IconButton>
          </Tooltip>
          <Button variant="contained" startIcon={<Add />} onClick={openCreate}>
            Nueva Tarjeta
          </Button>
        </Box>
      </Box>

      {/* Table */}
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell><b>ID</b></TableCell>
              <TableCell><b>Divisa</b></TableCell>
              <TableCell align="right"><b>Monto</b></TableCell>
              <TableCell><b>Estado</b></TableCell>
              <TableCell><b>Creada</b></TableCell>
              <TableCell><b>Actualizada</b></TableCell>
              <TableCell align="center"><b>Acciones</b></TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                  <CircularProgress size={32} />
                </TableCell>
              </TableRow>
            ) : cards.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">No hay tarjetas registradas</Typography>
                </TableCell>
              </TableRow>
            ) : cards.map(card => (
              <TableRow key={card.id} hover>
                <TableCell>{card.id}</TableCell>
                <TableCell><b>{card.currency.toUpperCase()}</b></TableCell>
                <TableCell align="right">
                  {Number(card.amount).toLocaleString('es-BO', { minimumFractionDigits: 2 })}
                </TableCell>
                <TableCell>
                  <Chip
                    label={STATUS_LABELS[card.status]}
                    color={STATUS_COLORS[card.status]}
                    size="small"
                  />
                </TableCell>
                <TableCell>{new Date(card.created_at).toLocaleString('es-BO')}</TableCell>
                <TableCell>{new Date(card.updated_at).toLocaleString('es-BO')}</TableCell>
                <TableCell align="center">
                  <Tooltip title="Editar">
                    <IconButton size="small" onClick={() => openEdit(card)}>
                      <Edit fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Eliminar">
                    <IconButton size="small" color="error" onClick={() => openDelete(card)}>
                      <Delete fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onClose={closeDialog} maxWidth="xs" fullWidth>
        <DialogTitle>{selectedCard ? 'Editar Tarjeta' : 'Nueva Tarjeta'}</DialogTitle>
        <DialogContent>
          <Box display="flex" flexDirection="column" gap={2} mt={1}>
            <TextField
              label="Divisa"
              value={form.currency}
              onChange={e => setForm(f => ({ ...f, currency: e.target.value.toUpperCase() }))}
              inputProps={{ maxLength: 10 }}
              placeholder="USD, EUR, BOB…"
              fullWidth
              required
            />
            <TextField
              label="Monto"
              type="number"
              value={form.amount}
              onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
              inputProps={{ min: 0, step: '0.01' }}
              fullWidth
              required
            />
            <TextField
              select
              label="Estado"
              value={form.status}
              onChange={e => setForm(f => ({ ...f, status: e.target.value as CardStatus }))}
              fullWidth
            >
              {(Object.keys(STATUS_LABELS) as CardStatus[]).map(s => (
                <MenuItem key={s} value={s}>{STATUS_LABELS[s]}</MenuItem>
              ))}
            </TextField>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDialog} disabled={saving}>Cancelar</Button>
          <Button variant="contained" onClick={handleSave} disabled={saving}>
            {saving ? <CircularProgress size={20} /> : 'Guardar'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Confirmar Eliminación</DialogTitle>
        <DialogContent>
          <Typography>
            ¿Eliminar la tarjeta <b>{selectedCard?.currency}</b> por monto{' '}
            <b>{selectedCard ? Number(selectedCard.amount).toLocaleString('es-BO', { minimumFractionDigits: 2 }) : ''}</b>?
            Esta acción no se puede deshacer.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)} disabled={saving}>Cancelar</Button>
          <Button variant="contained" color="error" onClick={handleDelete} disabled={saving}>
            {saving ? <CircularProgress size={20} /> : 'Eliminar'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default InventoryCards;
