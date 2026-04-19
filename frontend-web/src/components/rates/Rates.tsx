import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Chip, Button, Tab, Tabs,
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Grid, IconButton, Tooltip, Card, CardContent,
  Alert, AlertTitle, Link,
} from '@mui/material';
import {
  Refresh, Edit, TrendingUp, Analytics,
  CheckCircle, Warning, Error as ErrorIcon, HelpOutline,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { useFormik } from 'formik';
import * as yup from 'yup';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { isScaled, formatScale, formatRate } from '../../utils/finance';
import ArbitrageAlerts from './ArbitrageAlerts';
import RateHistoryChart from './RateHistoryChart';

// ── Source method colour coding (Phase 7) ────────────────────────────────────
const SOURCE_CONFIG: Record<string, {
  color: 'success' | 'warning' | 'error' | 'default';
  bgcolor: string;
  icon: React.ReactNode;
  label: string;
  description: string;
}> = {
  API: {
    color: 'success',
    bgcolor: '#e8f5e9',
    icon: <CheckCircle sx={{ fontSize: 14 }} />,
    label: 'API',
    description: 'Dato en tiempo real desde API externa verificada',
  },
  SCRAP: {
    color: 'warning',
    bgcolor: '#fff8e1',
    icon: <Warning sx={{ fontSize: 14 }} />,
    label: 'SCRAPING',
    description: 'Dato obtenido por web scraping del sitio oficial',
  },
  MANUAL: {
    color: 'default',
    bgcolor: '#e3f2fd',
    icon: <CheckCircle sx={{ fontSize: 14 }} />,
    label: 'MANUAL',
    description: 'Tasa ingresada manualmente por un administrador',
  },
  INFERENCE: {
    color: 'error',
    bgcolor: '#ffebee',
    icon: <ErrorIcon sx={{ fontSize: 14 }} />,
    label: 'INFERIDA',
    description: 'Tasa estimada — sin fuente en tiempo real. NO usar en transacciones sin confirmación.',
  },
};

const SourceBadge: React.FC<{ method: string; sourceUrl?: string | null; confidence?: number; fetchedAt?: string | null }> = ({
  method, sourceUrl, confidence, fetchedAt,
}) => {
  const cfg = SOURCE_CONFIG[method] ?? SOURCE_CONFIG['MANUAL'];
  const tooltipContent = (
    <Box sx={{ p: 0.5, maxWidth: 260 }}>
      <Typography variant="caption" fontWeight="bold" display="block">{cfg.label}</Typography>
      <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>{cfg.description}</Typography>
      {confidence !== undefined && (
        <Typography variant="caption" display="block">
          Confianza: <strong>{(confidence * 100).toFixed(0)}%</strong>
        </Typography>
      )}
      {fetchedAt && (
        <Typography variant="caption" display="block">
          Consultado: {format(new Date(fetchedAt), 'dd/MM/yyyy HH:mm:ss', { locale: es })}
        </Typography>
      )}
      {sourceUrl && (
        <Typography variant="caption" display="block" sx={{ mt: 0.5, wordBreak: 'break-all' }}>
          URL: {sourceUrl}
        </Typography>
      )}
    </Box>
  );

  return (
    <Tooltip title={tooltipContent} arrow placement="top">
      <Chip
        icon={cfg.icon as any}
        label={cfg.label}
        size="small"
        color={cfg.color}
        variant="filled"
        sx={{
          bgcolor: cfg.bgcolor,
          cursor: 'help',
          fontWeight: 600,
          fontSize: '0.65rem',
          height: 22,
        }}
      />
    </Tooltip>
  );
};

const ConfidenceBar: React.FC<{ value: number }> = ({ value }) => {
  const pct   = Math.round(value * 100);
  const color = pct >= 90 ? '#4caf50' : pct >= 70 ? '#ff9800' : '#f44336';
  return (
    <Tooltip title={`Confianza: ${pct}%`} arrow>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, cursor: 'help' }}>
        <Box sx={{ width: 40, height: 4, bgcolor: '#e0e0e0', borderRadius: 2, overflow: 'hidden' }}>
          <Box sx={{ width: `${pct}%`, height: '100%', bgcolor: color, borderRadius: 2 }} />
        </Box>
        <Typography variant="caption" color="text.secondary">{pct}%</Typography>
      </Box>
    </Tooltip>
  );
};

// ── Main component ────────────────────────────────────────────────────────────
const Rates: React.FC = () => {
  const [rates,      setRates]      = useState<any[]>([]);
  const [currencies, setCurrencies] = useState<any[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [editOpen,   setEditOpen]   = useState(false);
  const [selected,   setSelected]   = useState<any>(null);
  const [tab,        setTab]        = useState(0);
  const { user }                    = useAuth();
  const { enqueueSnackbar }         = useSnackbar();
  const { lastSheetsSync }          = useWebSocket();

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

  useEffect(() => {
    if (!lastSheetsSync) return;
    loadRates();
  }, [lastSheetsSync, loadRates]);

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
          valid_from:    new Date().toISOString(),
          source_method: 'MANUAL',
          is_validated:  true,
        });
        enqueueSnackbar('Tasa actualizada (marcada como MANUAL/validada)', { variant: 'success' });
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

  // Count inference rates for the warning banner
  const inferenceRates = rates.filter(r => r.source_method === 'INFERENCE' && !r.is_validated);

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4" fontWeight="bold">Tasas de Cambio</Typography>
        <Box display="flex" gap={1}>
          {tab === 0 && user?.role === 'ADMIN' && (
            <Button variant="outlined" startIcon={<Refresh />} onClick={handleUpdateFromBCB}>
              Actualizar desde BCB
            </Button>
          )}
          {tab === 0 && (
            <Button variant="outlined" startIcon={<Refresh />} onClick={loadRates}>
              Recargar
            </Button>
          )}
        </Box>
      </Box>

      {/* ── INFERENCE warning banner ── */}
      {inferenceRates.length > 0 && tab === 0 && (
        <Alert severity="error" sx={{ mb: 2 }} icon={<ErrorIcon />}>
          <AlertTitle>Advertencia de Cumplimiento — Tasas Estimadas</AlertTitle>
          {inferenceRates.length} tasa(s) marcadas como <strong>INFERIDAS</strong> (sin fuente en tiempo real).
          Estas tasas <strong>no deben usarse en transacciones</strong> hasta que un administrador
          las valide manualmente o las fuentes en línea se restauren.
          <Box mt={1} display="flex" gap={1} flexWrap="wrap">
            {inferenceRates.map(r => (
              <Chip
                key={r.id}
                label={`${r.currency_from?.code}/${r.currency_to?.code} — ${r.market_type}`}
                size="small"
                color="error"
                variant="outlined"
              />
            ))}
          </Box>
        </Alert>
      )}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Tasas Actuales" />
        <Tab label="Análisis de Arbitraje" icon={<Analytics />} iconPosition="start" />
        <Tab label="Historial" icon={<TrendingUp />} iconPosition="start" />
      </Tabs>

      {tab === 1 && <ArbitrageAlerts />}
      {tab === 2 && <RateHistoryChart />}

      {tab === 0 && (
        <Box>
          {/* ── KPI Cards ── */}
          <Grid container spacing={2} mb={3}>
            {rates.slice(0, 4).map((rate) => {
              const scale   = rate.currency_from?.scale_factor ?? 1;
              const scaled  = isScaled(scale);
              const cfg     = SOURCE_CONFIG[rate.source_method] ?? SOURCE_CONFIG['MANUAL'];
              return (
                <Grid item xs={12} sm={6} md={3} key={rate.id}>
                  <Card sx={{ border: rate.source_method === 'INFERENCE' ? '1px solid #f44336' : undefined }}>
                    <CardContent>
                      <Box display="flex" alignItems="center" gap={1} mb={0.5} flexWrap="wrap">
                        <Typography variant="h6" color="primary">
                          {rate.currency_from?.code} / {rate.currency_to?.code}
                        </Typography>
                        {scaled && (
                          <Chip label={`×${formatScale(scale)}`} size="small"
                            sx={{ bgcolor: 'warning.main', color: 'warning.contrastText', fontSize: '0.6rem', height: 18 }} />
                        )}
                        <SourceBadge
                          method={rate.source_method}
                          sourceUrl={rate.source_url}
                          confidence={parseFloat(rate.confidence)}
                          fetchedAt={rate.fetched_at}
                        />
                      </Box>
                      <Box display="flex" justifyContent="space-between" mt={1}>
                        <Box>
                          <Typography variant="caption" color="text.secondary">Compra</Typography>
                          <Typography variant="h6" color="success.main" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                            {formatRate(rate.buy_rate)}
                          </Typography>
                        </Box>
                        <Box textAlign="right">
                          <Typography variant="caption" color="text.secondary">Venta</Typography>
                          <Typography variant="h6" color="error.main" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                            {formatRate(rate.sell_rate)}
                          </Typography>
                        </Box>
                      </Box>
                      <Typography variant="caption" color="text.secondary">
                        Spread: {rate.spread_percentage}%
                        {scaled && ` · por ${formatScale(scale)} ${rate.currency_from?.code}`}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              );
            })}
          </Grid>

          {/* ── Leyenda de colores ── */}
          <Box display="flex" gap={1} mb={2} flexWrap="wrap" alignItems="center">
            <Typography variant="caption" color="text.secondary" mr={1}>Fuente:</Typography>
            {Object.entries(SOURCE_CONFIG).map(([key, cfg]) => (
              <Chip
                key={key}
                icon={cfg.icon as any}
                label={cfg.label}
                size="small"
                color={cfg.color}
                sx={{ bgcolor: cfg.bgcolor, fontSize: '0.65rem', height: 22 }}
              />
            ))}
            <Tooltip title="Haz click en el badge de cada tasa para ver detalles de la fuente" arrow>
              <HelpOutline sx={{ fontSize: 16, color: 'text.disabled', cursor: 'help' }} />
            </Tooltip>
          </Box>

          {/* ── Tabla completa ── */}
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Par</TableCell>
                  <TableCell>Mercado</TableCell>
                  <TableCell align="right">Oficial BCB</TableCell>
                  <TableCell align="right">Compra</TableCell>
                  <TableCell align="right">Venta</TableCell>
                  <TableCell align="right">Spread</TableCell>
                  <TableCell>Escala</TableCell>
                  <TableCell>Fuente / Origen</TableCell>
                  <TableCell>Confianza</TableCell>
                  <TableCell>Consultado</TableCell>
                  <TableCell>Estado</TableCell>
                  {user?.role === 'ADMIN' && <TableCell>Acciones</TableCell>}
                </TableRow>
              </TableHead>
              <TableBody>
                {rates.map((rate) => {
                  const scale       = rate.currency_from?.scale_factor ?? 1;
                  const scaled      = isScaled(scale);
                  const rateLabel   = scaled ? `por ${formatScale(scale)} ${rate.currency_from?.code}` : 'por unidad';
                  const isInference = rate.source_method === 'INFERENCE';
                  return (
                    <TableRow
                      key={rate.id}
                      hover
                      sx={isInference ? { bgcolor: '#fff8f8' } : undefined}
                    >
                      <TableCell>
                        <Typography fontWeight="bold">
                          {rate.currency_from?.code} / {rate.currency_to?.code}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={rate.market_type === 'official' ? 'Oficial' :
                                 rate.market_type === 'bcb'      ? 'BCB Ref.' :
                                 rate.market_type?.includes('paralelo_digital') ? 'Digital' :
                                 rate.market_type?.includes('paralelo') ? 'Paralelo' : rate.market_type}
                          size="small"
                          color={rate.market_type === 'official' ? 'primary' : 'default'}
                          variant={rate.market_type === 'official' ? 'filled' : 'outlined'}
                        />
                      </TableCell>
                      <TableCell align="right">
                        <Tooltip title="Tasa BCB por unidad individual" arrow>
                          <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums', cursor: 'help' }}>
                            {parseFloat(rate.official_rate).toFixed(4)}
                          </Typography>
                        </Tooltip>
                      </TableCell>
                      <TableCell align="right">
                        <Typography color="success.main" fontWeight="medium" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {formatRate(rate.buy_rate)}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography color="error.main" fontWeight="medium" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {formatRate(rate.sell_rate)}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">{rate.spread_percentage}%</TableCell>
                      <TableCell>
                        {scaled
                          ? <Chip label={`×${formatScale(scale)}`} size="small"
                              sx={{ bgcolor: 'warning.main', color: 'warning.contrastText', fontSize: '0.65rem' }} />
                          : <Typography variant="caption" color="text.secondary">×1</Typography>
                        }
                        <Typography variant="caption" color="text.secondary" display="block">
                          {rateLabel}
                        </Typography>
                      </TableCell>

                      {/* ── Source origin (Phase 7) ── */}
                      <TableCell>
                        <Box display="flex" flexDirection="column" gap={0.5}>
                          <SourceBadge
                            method={rate.source_method}
                            sourceUrl={rate.source_url}
                            confidence={parseFloat(rate.confidence)}
                            fetchedAt={rate.fetched_at}
                          />
                          {rate.source_url ? (
                            <Tooltip title={rate.source_url} arrow>
                              <Typography
                                variant="caption"
                                color="text.secondary"
                                sx={{
                                  maxWidth: 140, overflow: 'hidden',
                                  textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                  display: 'block', cursor: 'help',
                                }}
                              >
                                {rate.source_url}
                              </Typography>
                            </Tooltip>
                          ) : (
                            <Typography variant="caption" color="text.disabled" fontStyle="italic">
                              Sin URL registrada
                            </Typography>
                          )}
                        </Box>
                      </TableCell>

                      {/* ── Confidence bar ── */}
                      <TableCell>
                        <ConfidenceBar value={parseFloat(rate.confidence ?? '1')} />
                      </TableCell>

                      {/* ── Fetched at ── */}
                      <TableCell>
                        {rate.fetched_at ? (
                          <Typography variant="caption">
                            {format(new Date(rate.fetched_at), 'dd/MM/yy HH:mm', { locale: es })}
                          </Typography>
                        ) : (
                          <Typography variant="caption" color="text.disabled">—</Typography>
                        )}
                      </TableCell>

                      <TableCell>
                        <Box display="flex" flexDirection="column" gap={0.5}>
                          <Chip
                            label={rate.valid_until ? 'Vencida' : 'Vigente'}
                            color={rate.valid_until ? 'default' : 'success'}
                            size="small"
                          />
                          {rate.is_validated && (
                            <Chip label="Validada" color="primary" size="small" variant="outlined"
                              icon={<CheckCircle sx={{ fontSize: 12 }} />} />
                          )}
                          {isInference && !rate.is_validated && (
                            <Chip label="⚠ Sin validar" color="error" size="small" variant="outlined" />
                          )}
                        </Box>
                      </TableCell>

                      {user?.role === 'ADMIN' && (
                        <TableCell>
                          <Tooltip title={isInference ? 'Editar y validar esta tasa estimada' : 'Editar tasa'}>
                            <IconButton
                              size="small"
                              onClick={() => handleEdit(rate)}
                              color={isInference ? 'error' : 'default'}
                            >
                              <Edit />
                            </IconButton>
                          </Tooltip>
                        </TableCell>
                      )}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>

          {/* ── Dialog editar ── */}
          <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="xs" fullWidth>
            <DialogTitle>
              Editar Tasa — {selected?.currency_from?.code}/{selected?.currency_to?.code}
              {selected?.source_method === 'INFERENCE' && (
                <Typography variant="caption" color="error" display="block">
                  Esta tasa es ESTIMADA — al guardar quedará marcada como MANUAL y validada.
                </Typography>
              )}
            </DialogTitle>
            <DialogContent>
              <Grid container spacing={2} sx={{ mt: 0.5 }}>
                <Grid item xs={12}>
                  <TextField fullWidth label="Tasa Oficial BCB" name="official_rate" type="number"
                    inputProps={{ step: '0.0001' }}
                    value={formik.values.official_rate} onChange={formik.handleChange}
                    error={formik.touched.official_rate && Boolean(formik.errors.official_rate)} />
                </Grid>
                <Grid item xs={6}>
                  <TextField fullWidth label="Tasa Compra" name="buy_rate" type="number"
                    inputProps={{ step: '0.0001' }}
                    value={formik.values.buy_rate} onChange={formik.handleChange}
                    error={formik.touched.buy_rate && Boolean(formik.errors.buy_rate)} />
                </Grid>
                <Grid item xs={6}>
                  <TextField fullWidth label="Tasa Venta" name="sell_rate" type="number"
                    inputProps={{ step: '0.0001' }}
                    value={formik.values.sell_rate} onChange={formik.handleChange}
                    error={formik.touched.sell_rate && Boolean(formik.errors.sell_rate)} />
                </Grid>
                <Grid item xs={12}>
                  <Alert severity="info" sx={{ py: 0.5 }}>
                    Al guardar, la tasa quedará como <strong>MANUAL</strong> e <strong>is_validated = true</strong>.
                  </Alert>
                </Grid>
              </Grid>
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setEditOpen(false)}>Cancelar</Button>
              <Button variant="contained" onClick={() => formik.submitForm()}>Guardar y Validar</Button>
            </DialogActions>
          </Dialog>
        </Box>
      )}
    </Box>
  );
};

export default Rates;
