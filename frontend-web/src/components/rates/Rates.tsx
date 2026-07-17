import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Chip, Button, Tab, Tabs,
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Grid, Alert, AlertTitle, Tooltip,
} from '@mui/material';
import {
  Refresh, Edit, TrendingUp, Analytics,
  CheckCircle, Error as ErrorIcon, HelpOutline,
  CurrencyExchange, AutoMode, Savings,
  Psychology, EditNote, FlashOnOutlined,
} from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';
import { useSnackbar } from 'notistack';
import { useFormik } from 'formik';
import * as yup from 'yup';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { useWebSocket } from '../../contexts/WebSocketContext';
import ArbitrageAlerts from './ArbitrageAlerts';
import RateHistoryChart from './RateHistoryChart';
import ManualRatesTable from './ManualRatesTable';
import WebSocketStatus from './WebSocketStatus';
import { useRatesWebSocket } from '../../hooks/useRatesWebSocket';
import { SOURCE_CONFIG } from './rateConfig';
import LiveRateCard from './LiveRateCard';
import DigitalRatesSection from './DigitalRatesSection';
import PredictionsSection from './PredictionsSection';
import AutoProfitPanel from './AutoProfitPanel';
import CashVariantsPanel from './CashVariantsPanel';
import RatesKpiCards from './RatesKpiCards';
import RatesTable from './RatesTable';
import type { ExchangeRate, RateCurrency } from './rateTypes';

// ── Main component ────────────────────────────────────────────────────────────
const Rates: React.FC = () => {
  const [rates,      setRates]      = useState<ExchangeRate[]>([]);
  const [currencies, setCurrencies] = useState<RateCurrency[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [editOpen,   setEditOpen]   = useState(false);
  const [selected,   setSelected]   = useState<ExchangeRate | null>(null);
  const [tab,        setTab]        = useState(0);
  const { user }                           = useAuth();
  const { enqueueSnackbar }                = useSnackbar();
  const { lastSheetsSync }                 = useWebSocket();
  const { connected: wsConnected,
          lastUpdate: wsLastUpdate }        = useRatesWebSocket();

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
    } finally { setLoading(false); }
  }, [enqueueSnackbar]);

  useEffect(() => { loadRates(); }, [loadRates]);
  useEffect(() => {
    if (!lastSheetsSync) return;
    loadRates();
  }, [lastSheetsSync, loadRates]);

  const handleUpdateParallelRate = async () => {
    try {
      await api.post('/rates/exchange-rates/update_rates/', { source: 'dolarbluebolivia_click' });
      enqueueSnackbar('Tasa paralela actualizada desde mercado paralelo', { variant: 'success' });
      loadRates();
    } catch {
      enqueueSnackbar('Error al actualizar tasas', { variant: 'error' });
    }
  };

  const formik = useFormik({
    initialValues: { buy_rate: '', sell_rate: '' },
    validationSchema: yup.object({
      buy_rate:  yup.number().min(0.0001).required('Requerido'),
      sell_rate: yup.number().min(0.0001).required('Requerido'),
    }),
    onSubmit: async (values) => {
      if (!selected) return;
      try {
        const buy = parseFloat(values.buy_rate);
        const sell = parseFloat(values.sell_rate);
        await api.patch(`/rates/exchange-rates/${selected.id}/`, {
          ...values,
          official_rate: ((buy + sell) / 2).toFixed(4),
          valid_from:    new Date().toISOString(),
          source_method: 'MANUAL',
          is_validated:  true,
        });
        enqueueSnackbar('Tasa actualizada (MANUAL/validada)', { variant: 'success' });
        setEditOpen(false);
        loadRates();
      } catch {
        enqueueSnackbar('Error al actualizar', { variant: 'error' });
      }
    },
  });

  const handleEdit = (rate: ExchangeRate) => {
    setSelected(rate);
    formik.setValues({
      buy_rate:  rate.buy_rate,
      sell_rate: rate.sell_rate,
    });
    setEditOpen(true);
  };

  const inferenceRates = rates.filter(r => r.source_method === 'INFERENCE' && !r.is_validated);

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box sx={{ width: 40, height: 40, borderRadius: '11px', bgcolor: alpha(TOKENS.blue, 0.1),
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <CurrencyExchange sx={{ color: TOKENS.blue, fontSize: 20 }} />
          </Box>
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="h4" fontWeight={800}>Tasas de Cambio</Typography>
              <Chip label="EN VIVO" size="small" color="success" sx={{ height: 20, fontSize: '0.6rem', fontWeight: 800 }} />
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.125 }}>
              {rates.length} pares activos · spread, fuentes y trazabilidad ASFI
            </Typography>
          </Box>
        </Box>
        <Box display="flex" gap={1} alignItems="center">
          <WebSocketStatus connected={wsConnected} lastUpdate={wsLastUpdate} />
          {tab === 3 && user?.role === 'ADMIN' && (
            <Button variant="outlined" startIcon={<Refresh />} onClick={handleUpdateParallelRate}>
              Actualizar mercado paralelo
            </Button>
          )}
          {tab === 3 && (
            <Button variant="outlined" startIcon={<Refresh />} onClick={loadRates}>
              Recargar
            </Button>
          )}
        </Box>
      </Box>

      {/* INFERENCE warning */}
      {inferenceRates.length > 0 && tab === 3 && (
        <Alert severity="error" sx={{ mb: 2 }} icon={<ErrorIcon />}>
          <AlertTitle>Advertencia — Tasas Estimadas (INFERENCE)</AlertTitle>
          {inferenceRates.length} tasa(s) <strong>sin fuente verificable</strong>.
          No usar en transacciones. Valide manualmente o espere la restauración de las fuentes.
          <Box mt={1} display="flex" gap={1} flexWrap="wrap">
            {inferenceRates.map(r => (
              <Chip key={r.id}
                label={`${r.currency_from?.code}/${r.currency_to?.code} — ${r.market_type}`}
                size="small" color="error" variant="outlined" />
            ))}
          </Box>
        </Alert>
      )}

      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}
        variant="scrollable"
        scrollButtons="auto"
      >
        <Tab label="Tasas Digitales"  icon={<FlashOnOutlined />} iconPosition="start"
          sx={{ fontWeight: 700, color: 'success.main', '&.Mui-selected': { color: 'success.dark' } }} />
        <Tab label="Predicciones ML"  icon={<Psychology />}      iconPosition="start"
          sx={{ fontWeight: 700, color: 'info.main',    '&.Mui-selected': { color: 'info.dark'    } }} />
        <Tab label="Tasas Manuales"   icon={<EditNote />}        iconPosition="start"
          sx={{ fontWeight: 700, color: 'warning.main', '&.Mui-selected': { color: 'warning.dark' } }} />
        <Tab label="Tabla Completa" />
        <Tab label="Arbitraje"        icon={<Analytics />}       iconPosition="start" />
        <Tab label="Historial"        icon={<TrendingUp />}      iconPosition="start" />
        <Tab label="Auto Profit"      icon={<AutoMode />}        iconPosition="start"
          sx={{ fontWeight: 700, color: 'warning.main', '&.Mui-selected': { color: 'warning.dark' } }} />
        <Tab label="Efectivo Físico"  icon={<Savings />}         iconPosition="start" />
      </Tabs>

      {/* ── Tab 0: Tasas Digitales ─────────────────────────────────────── */}
      {tab === 0 && <DigitalRatesSection />}

      {/* ── Tab 1: Predicciones ML ─────────────────────────────────────── */}
      {tab === 1 && <PredictionsSection />}

      {/* ── Tab 2: Tasas Manuales ──────────────────────────────────────── */}
      {tab === 2 && <ManualRatesTable manualOnly />}

      {tab === 4 && <ArbitrageAlerts />}
      {tab === 5 && <RateHistoryChart />}
      {tab === 6 && <AutoProfitPanel />}
      {tab === 7 && <CashVariantsPanel />}

      {tab === 3 && (
        <Box>
          {/* Live Rate Cards */}
          <Box mb={3}>
            <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem', letterSpacing: 1 }}>
              MOTOR DE TASAS EN TIEMPO REAL
            </Typography>
            <Grid container spacing={2} mt={0.25}>
              {['USD', 'EUR', 'BRL'].map(cur => (
                <Grid item xs={12} sm={4} key={cur}>
                  <LiveRateCard currency={cur} />
                </Grid>
              ))}
            </Grid>
          </Box>

          {/* KPI Cards */}
          <RatesKpiCards rates={rates} />

          {/* Legend */}
          <Box display="flex" gap={1} mb={2} flexWrap="wrap" alignItems="center">
            <Typography variant="caption" color="text.secondary" mr={1}>Fuente:</Typography>
            {Object.entries(SOURCE_CONFIG).map(([key, cfg]) => (
              <Chip key={key} icon={cfg.icon as any} label={cfg.label} size="small" color={cfg.color}
                sx={{ bgcolor: cfg.bgcolor, fontSize: '0.65rem', height: 22 }} />
            ))}
            <Box mx={1} sx={{ width: 1, height: 16, bgcolor: 'divider' }} />
            <Typography variant="caption" color="text.secondary">Confianza:</Typography>
            {[['🟢', 'Alta (≥90%)'], ['🟡', 'Media (≥70%)'], ['🔴', 'Baja (<70%)']].map(([dot, label]) => (
              <Typography key={dot} variant="caption" color="text.secondary">{dot} {label}</Typography>
            ))}
            <Tooltip title="Haz click en el badge de cada tasa para ver detalles" arrow>
              <HelpOutline sx={{ fontSize: 16, color: 'text.disabled', cursor: 'help' }} />
            </Tooltip>
          </Box>

          {/* Main table */}
          <RatesTable rates={rates} isAdmin={user?.role === 'ADMIN'} onEdit={handleEdit} />

          {/* Edit dialog */}
          <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="xs" fullWidth>
            <DialogTitle>
              Editar Tasa — {selected?.currency_from?.code}/{selected?.currency_to?.code}
              {selected?.source_method === 'INFERENCE' && (
                <Typography variant="caption" color="error" display="block">
                  Tasa ESTIMADA — al guardar quedará MANUAL y validada.
                </Typography>
              )}
            </DialogTitle>
            <DialogContent>
              <Grid container spacing={2} sx={{ mt: 0.5 }}>
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
                    Al guardar → <strong>MANUAL</strong> + <strong>is_validated = true</strong>
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
