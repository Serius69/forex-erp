/**
 * CapitalDashboard — Pantalla principal de composición de capital.
 *
 * FÓRMULA:
 *   CAPITAL NETO = TOTAL ACTIVOS - TOTAL PASIVOS
 *
 *   ACTIVOS:
 *     A) Divisas en efectivo  = Σ (stock × tasa_venta)
 *     B) Efectivo BOB físico  = fuertes + caja_chica + monedas + rotos + sueltos
 *     C) Digital              = qr_transferencias + tarjetas_telefonicas
 *     D) Tarjetas módulo      = Σ (stock_tipo × precio_venta_prom)
 *
 * Actualización en tiempo real via WebSocket cuando cambian las tasas.
 * Data fetching delegated to useCapital() — single request per data source.
 */
import React, { useState, useMemo, useEffect } from 'react';
import {
  Box, Grid, Paper, Typography, Button, IconButton,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Chip, Skeleton, Alert, Divider, Tooltip,
  CircularProgress, LinearProgress,
} from '@mui/material';
import {
  Refresh, Edit, Save, Cancel,
  AccountBalance, CurrencyExchange, PhoneAndroid, Payments,
  Circle, WifiOff,
} from '@mui/icons-material';
import { NumericFormat } from 'react-number-format';
import { useSnackbar } from 'notistack';
import { alpha } from '@mui/material/styles';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { useCapital } from '../../hooks/useCapital';
import type { ComposicionHoy } from '../../hooks/useCapital';

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (val: string | number | undefined, decimals = 2): string => {
  const n = parseFloat(String(val || 0));
  return isNaN(n) ? '0.00'
    : new Intl.NumberFormat('es-BO', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }).format(n);
};

const fmtBOB = (val: string | number | undefined) => `Bs. ${fmt(val)}`;

const COLORS = {
  green: '#2e7d32', blue: '#1565c0', amber: '#e65100',
  purple: '#6a1b9a', red: '#b71c1c', teal: '#00695c',
};

// ── KPI Card ──────────────────────────────────────────────────────────────────

const KpiCard = ({
  label, value, sub, color, icon, loading, pct,
}: {
  label: string; value: string; sub?: string;
  color: string; icon: React.ReactNode; loading: boolean; pct?: string;
}) => (
  <Paper
    variant="outlined"
    sx={{ p: 2.5, borderTop: `3px solid ${color}`, height: '100%' }}
  >
    <Box display="flex" justifyContent="space-between" alignItems="flex-start">
      <Box flex={1}>
        <Typography variant="caption" color="text.secondary"
          textTransform="uppercase" fontWeight={700} letterSpacing={0.5}>
          {label}
        </Typography>
        {loading ? (
          <Skeleton width={140} height={44} />
        ) : (
          <Typography variant="h5" fontWeight={800}
            sx={{ color, fontVariantNumeric: 'tabular-nums', lineHeight: 1.3, mt: 0.5 }}>
            {value}
          </Typography>
        )}
        {sub && !loading && (
          <Typography variant="caption" color="text.secondary">{sub}</Typography>
        )}
      </Box>
      <Box sx={{ color, opacity: 0.7, mt: 0.5 }}>{icon}</Box>
    </Box>
    {pct && !loading && (
      <Box mt={1.5}>
        <Box display="flex" justifyContent="space-between" mb={0.5}>
          <Typography variant="caption" color="text.secondary">del total activos</Typography>
          <Typography variant="caption" fontWeight={700} sx={{ color }}>
            {parseFloat(pct).toFixed(1)}%
          </Typography>
        </Box>
        <LinearProgress
          variant="determinate"
          value={Math.min(parseFloat(pct), 100)}
          sx={{ height: 4, borderRadius: 2,
            bgcolor: alpha(color, 0.1),
            '& .MuiLinearProgress-bar': { bgcolor: color } }}
        />
      </Box>
    )}
  </Paper>
);

// ── Efectivo Edit Dialog ───────────────────────────────────────────────────────

const EFECTIVO_FIELDS: { key: keyof ComposicionHoy; label: string; help?: string }[] = [
  { key: 'fuertes',    label: 'Billetes grandes (200/100/50)',  help: 'Denominación alta' },
  { key: 'caja_chica', label: 'Caja chica (20/10)',             help: 'Billetes medianos' },
  { key: 'monedas',    label: 'Monedas',                        help: '5, 2, 1, 0.50 Bs.' },
  { key: 'rotos',      label: 'Billetes dañados',               help: 'Se aceptan al 100%' },
  { key: 'sueltos',    label: 'Sueltos sin clasificar',         help: '' },
  { key: 'qr_transferencias',    label: 'QR / Transferencias',  help: 'Saldo digital' },
  { key: 'tarjetas_telefonicas', label: 'Tarjetas Tel. en caja', help: 'Stock valorado en BOB' },
  { key: 'pasivos',    label: 'Pasivos (deudas)',               help: 'Acreedores / obligaciones' },
];

interface EfectivoDialogProps {
  open: boolean;
  composicion: ComposicionHoy;
  onClose: () => void;
  onSaved: () => void;
}

const EfectivoDialog: React.FC<EfectivoDialogProps> = ({
  open, composicion, onClose, onSaved,
}) => {
  const [form, setForm]     = useState<Record<string, string>>({});
  const [motivo, setMotivo] = useState('');
  const [saving, setSaving] = useState(false);
  const { enqueueSnackbar } = useSnackbar();

  useEffect(() => {
    if (!open) return;
    const init: Record<string, string> = {};
    EFECTIVO_FIELDS.forEach(({ key }) => {
      init[key] = String(composicion[key] ?? '0.00');
    });
    setForm(init);
    setMotivo('');
  }, [open, composicion]);

  const total = useMemo(() => {
    const efe = ['fuertes', 'caja_chica', 'monedas', 'rotos', 'sueltos']
      .reduce((s, k) => s + parseFloat(form[k] || '0'), 0);
    return efe;
  }, [form]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Record<string, string | number> = {};
      EFECTIVO_FIELDS.forEach(({ key }) => {
        payload[key as string] = parseFloat(form[key as string] || '0');
      });
      if (motivo) payload.motivo = motivo;

      await api.post('/capital/composicion/', payload);
      enqueueSnackbar('Composición de capital guardada', { variant: 'success' });
      onSaved();
      onClose();
    } catch (e: any) {
      const msg = e.response?.data?.detail || JSON.stringify(e.response?.data) || 'Error al guardar';
      enqueueSnackbar(msg, { variant: 'error' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth
      PaperProps={{ sx: { borderRadius: 3 } }}>
      <DialogTitle sx={{ fontWeight: 700, borderBottom: '1px solid', borderColor: 'divider', pb: 2 }}>
        <Box display="flex" alignItems="center" gap={1}>
          <Edit sx={{ color: COLORS.blue }} />
          Editar Composición de Capital — Hoy
        </Box>
      </DialogTitle>

      <DialogContent sx={{ pt: 3 }}>
        <Grid container spacing={2}>
          {EFECTIVO_FIELDS.map(({ key, label, help }) => (
            <Grid item xs={12} sm={6} key={key as string}>
              <NumericFormat
                customInput={TextField}
                label={label}
                value={form[key as string] ?? '0'}
                onValueChange={v => setForm(p => ({ ...p, [key as string]: v.value || '0' }))}
                thousandSeparator=","
                decimalSeparator="."
                decimalScale={2}
                fixedDecimalScale
                allowNegative={false}
                fullWidth
                size="small"
                helperText={help}
                InputProps={{ startAdornment: <Typography variant="caption" sx={{ mr: 0.5, color: 'text.secondary' }}>Bs.</Typography> }}
                sx={{ '& input': { fontVariantNumeric: 'tabular-nums', fontWeight: 600 } }}
              />
            </Grid>
          ))}

          <Grid item xs={12}>
            <Paper sx={{ p: 2, bgcolor: alpha(COLORS.green, 0.05), border: `1px solid ${alpha(COLORS.green, 0.2)}` }}>
              <Box display="flex" justifyContent="space-between" alignItems="center">
                <Typography variant="body2" fontWeight={600} color="text.secondary">
                  Total efectivo físico
                </Typography>
                <Typography variant="h6" fontWeight={800} sx={{ color: COLORS.green, fontVariantNumeric: 'tabular-nums' }}>
                  {fmtBOB(total)}
                </Typography>
              </Box>
            </Paper>
          </Grid>

          <Grid item xs={12}>
            <TextField
              label="Motivo del cambio (opcional)"
              value={motivo}
              onChange={e => setMotivo(e.target.value)}
              fullWidth size="small"
              placeholder="Ej: Conteo de cierre, corrección…"
            />
          </Grid>
        </Grid>
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2.5, gap: 1 }}>
        <Button onClick={onClose} startIcon={<Cancel />} color="inherit">Cancelar</Button>
        <Button
          variant="contained" onClick={handleSave}
          disabled={saving}
          startIcon={saving ? <CircularProgress size={16} color="inherit" /> : <Save />}
          sx={{ fontWeight: 700, minWidth: 140 }}
        >
          {saving ? 'Guardando…' : 'Guardar'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

const CapitalDashboard: React.FC = () => {
  const [editOpen, setEditOpen] = useState(false);
  const { capital, composicion, loading, error, connected, refresh } = useCapital();
  const { user } = useAuth();

  const canEdit = user?.role === 'ADMIN' || user?.role === 'SUPERVISOR' || user?.role === 'CASHIER';

  const divisasArr = useMemo(
    () => Object.values(capital?.divisas ?? {}).sort((a, b) =>
      parseFloat(b.valor_bob) - parseFloat(a.valor_bob)
    ),
    [capital]
  );

  const tarjetasArr = useMemo(
    () => Object.entries(capital?.tarjetas_modulo ?? {}),
    [capital]
  );

  if (loading && !capital) {
    return (
      <Box>
        <Grid container spacing={2} mb={3}>
          {[0,1,2,3].map(i => (
            <Grid item xs={12} sm={6} md={3} key={i}>
              <Skeleton variant="rectangular" height={130} sx={{ borderRadius: 2 }} />
            </Grid>
          ))}
        </Grid>
        <Skeleton variant="rectangular" height={300} sx={{ borderRadius: 2 }} />
      </Box>
    );
  }

  // Error de carga sin datos previos → Alert persistente + Reintentar
  // (distingue "error" de "sin datos" y evita el crash de capital! === null)
  if (!capital) {
    return (
      <Alert
        severity={error ? 'error' : 'info'}
        action={<Button color="inherit" size="small" onClick={refresh}>Reintentar</Button>}
      >
        {error ?? 'No hay datos de capital disponibles.'}
      </Alert>
    );
  }

  const cap = capital;

  return (
    <Box>
      {/* ── Header ── */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2.5}>
        <Box display="flex" alignItems="center" gap={1.5}>
          <Typography variant="h5" fontWeight={800}>Capital en Tiempo Real</Typography>
          <Chip
            icon={<Circle sx={{ fontSize: '10px !important' }} />}
            label={connected ? 'Live' : 'Sin señal'}
            size="small"
            color={connected ? 'success' : 'default'}
            variant="outlined"
            sx={{ fontWeight: 700, fontSize: '0.7rem' }}
          />
        </Box>
        <Box display="flex" gap={1} alignItems="center">
          {!connected && (
            <Tooltip title="Sin conexión WebSocket — datos pueden no estar actualizados">
              <WifiOff color="warning" fontSize="small" />
            </Tooltip>
          )}
          {canEdit && (
            <Button variant="outlined" startIcon={<Edit />}
              onClick={() => setEditOpen(true)} size="small">
              Editar efectivo
            </Button>
          )}
          <IconButton onClick={refresh} size="small" disabled={loading}>
            {loading ? <CircularProgress size={18} /> : <Refresh fontSize="small" />}
          </IconButton>
        </Box>
      </Box>

      {cap.advertencias?.length > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {cap.advertencias.join(' · ')}
        </Alert>
      )}

      {/* ── KPI Cards ── */}
      <Grid container spacing={2} mb={3}>
        <Grid item xs={12} sm={6} md={3}>
          <KpiCard
            label="Capital Neto"
            value={fmtBOB(cap.capital_neto)}
            sub={`Activos ${fmtBOB(cap.total_activos)} − Pasivos ${fmtBOB(cap.total_pasivos)}`}
            color={parseFloat(cap.capital_neto) >= 0 ? COLORS.green : COLORS.red}
            icon={<AccountBalance sx={{ fontSize: 32 }} />}
            loading={loading}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <KpiCard
            label="Divisas (valoradas)"
            value={fmtBOB(cap.totales.divisas_bob)}
            color={COLORS.blue}
            icon={<CurrencyExchange sx={{ fontSize: 32 }} />}
            loading={loading}
            pct={cap.desglose.pct_divisas}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <KpiCard
            label="Efectivo BOB"
            value={fmtBOB(cap.totales.efectivo_bob)}
            sub={`Digital: Bs. ${fmt(cap.totales.digital_bob)}`}
            color={COLORS.amber}
            icon={<Payments sx={{ fontSize: 32 }} />}
            loading={loading}
            pct={cap.desglose.pct_efectivo}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <KpiCard
            label="Tarjetas Telefónicas"
            value={fmtBOB(cap.totales.tarjetas_bob)}
            color={COLORS.purple}
            icon={<PhoneAndroid sx={{ fontSize: 32 }} />}
            loading={loading}
            pct={cap.desglose.pct_tarjetas}
          />
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        {/* ── A) DIVISAS ── */}
        <Grid item xs={12} lg={7}>
          <Paper variant="outlined" sx={{ p: 0, overflow: 'hidden' }}>
            <Box px={2.5} py={1.5} display="flex" justifyContent="space-between" alignItems="center"
              sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
              <Typography variant="subtitle1" fontWeight={700}>
                Divisas en efectivo
              </Typography>
              <Chip label={`${divisasArr.length} divisas`} size="small" variant="outlined" />
            </Box>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ bgcolor: 'background.default' }}>
                    {['Divisa', 'Stock', 'TC Venta/u.', 'Valor BOB', 'Mercado'].map(h => (
                      <TableCell key={h} sx={{ fontWeight: 700, fontSize: '0.72rem',
                        textTransform: 'uppercase', letterSpacing: 0.5 }}>
                        {h}
                      </TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {divisasArr.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                        Sin inventario de divisas registrado
                      </TableCell>
                    </TableRow>
                  ) : divisasArr.map(d => (
                    <TableRow key={d.code} hover>
                      <TableCell>
                        <Box display="flex" alignItems="center" gap={1}>
                          <Typography variant="body2" fontWeight={700}>{d.code}</Typography>
                          {d.scale_factor > 1 && (
                            <Chip label={`×${d.scale_factor.toLocaleString()}`}
                              size="small" variant="outlined"
                              sx={{ height: 16, fontSize: '0.6rem',
                                color: COLORS.amber, borderColor: COLORS.amber }} />
                          )}
                        </Box>
                        <Typography variant="caption" color="text.secondary">{d.name}</Typography>
                      </TableCell>
                      <TableCell sx={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
                        {d.scale_factor > 1
                          ? `${fmt(parseFloat(d.stock) / d.scale_factor, 0)} lotes`
                          : fmt(d.stock)
                        }
                      </TableCell>
                      <TableCell sx={{ fontVariantNumeric: 'tabular-nums', color: COLORS.blue }}>
                        Bs. {fmt(d.tc_venta_unit, 4)}
                        {d.scale_factor > 1 && (
                          <Typography variant="caption" color="text.secondary" display="block">
                            (por lote: {fmt(d.tc_venta_lote, 4)})
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell sx={{ fontVariantNumeric: 'tabular-nums', fontWeight: 700, color: COLORS.green }}>
                        {fmtBOB(d.valor_bob)}
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={d.market_type === 'paralelo_fisico_empresa' ? 'Empresa'
                                : d.market_type === 'paralelo_digital' ? 'Digital'
                                : d.market_type === 'official' ? 'BCB'
                                : 'Paralelo'}
                          size="small"
                          sx={{ height: 18, fontSize: '0.6rem',
                            bgcolor: alpha(COLORS.blue, 0.08), color: COLORS.blue }}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
            {divisasArr.length > 0 && (
              <Box px={2.5} py={1.5} sx={{ borderTop: '1px solid', borderColor: 'divider',
                bgcolor: alpha(COLORS.green, 0.04) }} display="flex" justifyContent="flex-end">
                <Typography variant="subtitle2" fontWeight={800} sx={{ color: COLORS.green }}>
                  Total divisas: {fmtBOB(cap.totales.divisas_bob)}
                </Typography>
              </Box>
            )}
          </Paper>
        </Grid>

        {/* ── B+C) EFECTIVO + DIGITAL ── */}
        <Grid item xs={12} lg={5}>
          <Paper variant="outlined" sx={{ p: 0, overflow: 'hidden', mb: 2 }}>
            <Box px={2.5} py={1.5} display="flex" justifyContent="space-between" alignItems="center"
              sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
              <Typography variant="subtitle1" fontWeight={700}>Efectivo BOB</Typography>
              {canEdit && (
                <IconButton size="small" onClick={() => setEditOpen(true)}>
                  <Edit fontSize="small" />
                </IconButton>
              )}
            </Box>
            <Box p={2}>
              {composicion ? (
                <Box display="flex" flexDirection="column" gap={0.75}>
                  {[
                    { label: 'Billetes grandes (50–200)', value: composicion.fuertes },
                    { label: 'Caja chica (10–20)',        value: composicion.caja_chica },
                    { label: 'Monedas',                   value: composicion.monedas },
                    { label: 'Billetes dañados',          value: composicion.rotos },
                    { label: 'Sueltos sin clasificar',    value: composicion.sueltos },
                  ].map(({ label, value }) => (
                    <Box key={label} display="flex" justifyContent="space-between" alignItems="center">
                      <Typography variant="body2" color="text.secondary">{label}</Typography>
                      <Typography variant="body2" fontWeight={600}
                        sx={{ fontVariantNumeric: 'tabular-nums' }}>
                        {fmtBOB(value)}
                      </Typography>
                    </Box>
                  ))}
                  <Divider sx={{ my: 0.5 }} />
                  <Box display="flex" justifyContent="space-between" alignItems="center">
                    <Typography variant="body2" fontWeight={700}>Total efectivo físico</Typography>
                    <Typography variant="body2" fontWeight={800}
                      sx={{ color: COLORS.amber, fontVariantNumeric: 'tabular-nums' }}>
                      {fmtBOB(composicion.total_efectivo)}
                    </Typography>
                  </Box>
                  <Divider sx={{ my: 0.5 }} />
                  {[
                    { label: 'QR / Transferencias',     value: composicion.qr_transferencias },
                    { label: 'Tarjetas tel. en caja',   value: composicion.tarjetas_telefonicas },
                  ].map(({ label, value }) => (
                    <Box key={label} display="flex" justifyContent="space-between" alignItems="center">
                      <Typography variant="body2" color="text.secondary">{label}</Typography>
                      <Typography variant="body2" fontWeight={600}
                        sx={{ fontVariantNumeric: 'tabular-nums' }}>
                        {fmtBOB(value)}
                      </Typography>
                    </Box>
                  ))}
                  <Divider sx={{ my: 0.5 }} />
                  <Box display="flex" justifyContent="space-between" alignItems="center"
                    sx={{ bgcolor: alpha(COLORS.red, 0.04), p: 1, borderRadius: 1 }}>
                    <Typography variant="body2" color="error.main" fontWeight={700}>
                      Pasivos (deudas)
                    </Typography>
                    <Typography variant="body2" fontWeight={800}
                      sx={{ color: COLORS.red, fontVariantNumeric: 'tabular-nums' }}>
                      − {fmtBOB(composicion.pasivos)}
                    </Typography>
                  </Box>
                </Box>
              ) : (
                <Alert severity="info" action={
                  canEdit ? (
                    <Button size="small" onClick={() => setEditOpen(true)}>
                      Registrar
                    </Button>
                  ) : undefined
                }>
                  Sin datos de efectivo para hoy.
                </Alert>
              )}
            </Box>
          </Paper>

          {/* ── D) TARJETAS MÓDULO ── */}
          {tarjetasArr.length > 0 && (
            <Paper variant="outlined" sx={{ p: 0, overflow: 'hidden' }}>
              <Box px={2.5} py={1.5}
                sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
                <Typography variant="subtitle1" fontWeight={700}>
                  Tarjetas Telefónicas (módulo)
                </Typography>
              </Box>
              <Box p={2} display="flex" flexDirection="column" gap={0.75}>
                {tarjetasArr.map(([nombre, t]) => (
                  <Box key={nombre} display="flex" justifyContent="space-between" alignItems="center">
                    <Box>
                      <Typography variant="body2" fontWeight={600}>{nombre}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {t.stock} und. × Bs. {fmt(t.precio_prom)}
                      </Typography>
                    </Box>
                    <Typography variant="body2" fontWeight={700}
                      sx={{ color: COLORS.purple, fontVariantNumeric: 'tabular-nums' }}>
                      {fmtBOB(t.valor_bob)}
                    </Typography>
                  </Box>
                ))}
                <Divider />
                <Box display="flex" justifyContent="flex-end">
                  <Typography variant="body2" fontWeight={800}
                    sx={{ color: COLORS.purple, fontVariantNumeric: 'tabular-nums' }}>
                    Total: {fmtBOB(cap.totales.tarjetas_bob)}
                  </Typography>
                </Box>
              </Box>
            </Paper>
          )}
        </Grid>
      </Grid>

      {/* ── Resumen final ── */}
      <Paper variant="outlined"
        sx={{ mt: 2, p: 2, bgcolor: alpha(COLORS.green, 0.04),
          border: `2px solid ${alpha(COLORS.green, 0.3)}` }}>
        <Grid container spacing={2} alignItems="center">
          {[
            { label: 'Total divisas',       value: cap.totales.divisas_bob,  color: COLORS.blue   },
            { label: 'Total efectivo',       value: cap.totales.efectivo_bob, color: COLORS.amber  },
            { label: 'Total digital',        value: cap.totales.digital_bob,  color: COLORS.teal   },
            { label: 'Total tarjetas',       value: cap.totales.tarjetas_bob, color: COLORS.purple },
            { label: '— Pasivos',            value: cap.total_pasivos,        color: COLORS.red    },
          ].map(({ label, value, color }) => (
            <Grid item xs={6} sm={4} md="auto" key={label} sx={{ flex: 1 }}>
              <Typography variant="caption" color="text.secondary" display="block">{label}</Typography>
              <Typography variant="body1" fontWeight={700}
                sx={{ color, fontVariantNumeric: 'tabular-nums' }}>
                {label.startsWith('—') ? `− ${fmtBOB(value)}` : fmtBOB(value)}
              </Typography>
            </Grid>
          ))}
          <Grid item xs={12} sm={4} md="auto" sx={{ flex: 1.5 }}>
            <Box sx={{ bgcolor: COLORS.green, borderRadius: 2, p: 2, textAlign: 'center' }}>
              <Typography variant="caption" sx={{ color: 'white', opacity: 0.85 }}>
                CAPITAL NETO
              </Typography>
              <Typography variant="h5" fontWeight={900}
                sx={{ color: 'white', fontVariantNumeric: 'tabular-nums' }}>
                {fmtBOB(cap.capital_neto)}
              </Typography>
            </Box>
          </Grid>
        </Grid>
      </Paper>

      <Typography variant="caption" color="text.secondary" display="block" mt={1} textAlign="right">
        Calculado: {cap.calculado_en ? new Date(cap.calculado_en).toLocaleTimeString('es-BO') : '—'}
        {connected && ' · Actualización automática activa'}
      </Typography>

      {/* ── Edit Dialog ── */}
      {composicion && (
        <EfectivoDialog
          open={editOpen}
          composicion={composicion}
          onClose={() => setEditOpen(false)}
          onSaved={refresh}
        />
      )}
    </Box>
  );
};

export default CapitalDashboard;
