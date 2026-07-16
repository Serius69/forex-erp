import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Chip, Button, Tab, Tabs,
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Grid, IconButton, Tooltip, Card, CardContent,
  Alert, AlertTitle, Link, Slider, Switch, FormControlLabel,
  CircularProgress, Divider, LinearProgress,
} from '@mui/material';
import {
  Refresh, Edit, TrendingUp, Analytics,
  CheckCircle, Warning, Error as ErrorIcon, HelpOutline,
  CurrencyExchange, AutoMode, MonetizationOn, Savings,
  FlashOn, KeyboardArrowRight, InfoOutlined,
  Psychology, EditNote, FlashOnOutlined,
} from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';
import { useSnackbar } from 'notistack';
import { useFormik } from 'formik';
import * as yup from 'yup';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { isScaled, formatScale, formatRate, formatPercent } from '../../utils/finance';
import ArbitrageAlerts from './ArbitrageAlerts';
import RateHistoryChart from './RateHistoryChart';
import RateCard from './RateCard';
import PredictionCard from './PredictionCard';
import ManualRatesTable from './ManualRatesTable';
import WebSocketStatus from './WebSocketStatus';
import { useRatesWebSocket } from '../../hooks/useRatesWebSocket';
import RatesPanel from './RatesPanel';
import SourcesGrid from './SourcesGrid';

// ── Source method config ──────────────────────────────────────────────────────
const SOURCE_CONFIG: Record<string, {
  color: 'success' | 'warning' | 'error' | 'default';
  bgcolor: string;
  icon: React.ReactNode;
  label: string;
  description: string;
}> = {
  API: {
    color: 'success', bgcolor: '#e8f5e9',
    icon: <CheckCircle sx={{ fontSize: 14 }} />,
    label: 'API',
    description: 'Dato en tiempo real desde API externa verificada',
  },
  SCRAP: {
    color: 'warning', bgcolor: '#fff8e1',
    icon: <Warning sx={{ fontSize: 14 }} />,
    label: 'SCRAPING',
    description: 'Dato obtenido por web scraping del sitio oficial',
  },
  MANUAL: {
    color: 'default', bgcolor: '#e3f2fd',
    icon: <CheckCircle sx={{ fontSize: 14 }} />,
    label: 'MANUAL',
    description: 'Tasa ingresada manualmente por un administrador',
  },
  INFERENCE: {
    color: 'error', bgcolor: '#ffebee',
    icon: <ErrorIcon sx={{ fontSize: 14 }} />,
    label: 'INFERIDA',
    description: 'Tasa estimada — sin fuente en tiempo real. NO usar en transacciones.',
  },
};

const LIVE_SOURCE_CONFIG: Record<string, {
  color: 'success' | 'warning' | 'info' | 'default';
  bgcolor: string; dot: string; label: string; description: string;
}> = {
  binance:  { color: 'success', bgcolor: '#e8f5e9', dot: '🟢', label: 'BINANCE',     description: 'Binance P2P en tiempo real (USDT/BOB)' },
  dolarblue:{ color: 'warning', bgcolor: '#fff8e1', dot: '🟡', label: 'DOLARBLUE',   description: 'Referencia paralela — DolarBlueBolivia (scraping)' },
  db_cache: { color: 'warning', bgcolor: '#fff8e1', dot: '🟡', label: 'SCRAPING',    description: 'Dato en caché de fuente scrapeada' },
  MANUAL:   { color: 'info',    bgcolor: '#e3f2fd', dot: '🔵', label: 'MANUAL',      description: 'Tasa ingresada manualmente' },
};

// ── Confidence helpers ────────────────────────────────────────────────────────
const confidenceColor = (v: number) =>
  v >= 0.90 ? '#4caf50' : v >= 0.70 ? '#ff9800' : '#f44336';

const confidenceDot = (v: number) =>
  v >= 0.90 ? '🟢' : v >= 0.70 ? '🟡' : '🔴';

const isStale = (timestamp: string | null | undefined, thresholdMinutes = 30): boolean => {
  if (!timestamp) return true;
  return (Date.now() - new Date(timestamp).getTime()) > thresholdMinutes * 60 * 1000;
};

const confidenceLabel = (v: number) =>
  v >= 0.90 ? 'Alta' : v >= 0.70 ? 'Media' : 'Baja';

// ── Sub-components ────────────────────────────────────────────────────────────
interface LiveRate {
  pair: string; buy: number; sell: number; spread: number; spread_pct: number;
  source: string; source_url: string | null; confidence: number;
  timestamp: string; is_live: boolean;
  anomalies: { type: string; severity: string; message: string }[];
}

const LiveSourceBadge: React.FC<{ source: string; confidence: number }> = ({ source, confidence }) => {
  const cfg = LIVE_SOURCE_CONFIG[source] ?? LIVE_SOURCE_CONFIG['db_cache'];
  return (
    <Tooltip title={cfg.description} arrow>
      <Chip
        label={`${cfg.dot} ${cfg.label}`}
        size="small" color={cfg.color} variant="filled"
        sx={{ bgcolor: cfg.bgcolor, fontWeight: 700, fontSize: '0.65rem', height: 22, cursor: 'help' }}
      />
    </Tooltip>
  );
};

const LiveRateCard: React.FC<{ currency?: string }> = ({ currency = 'USD' }) => {
  const [rate, setRate]       = React.useState<LiveRate | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError]     = React.useState(false);

  const fetchLive = React.useCallback(async () => {
    setLoading(true); setError(false);
    try {
      const res = await api.get(`/rates/exchange-rates/live/?currency=${currency}`);
      setRate(res.data);
    } catch { setError(true); }
    finally { setLoading(false); }
  }, [currency]);

  React.useEffect(() => { fetchLive(); }, [fetchLive]);
  React.useEffect(() => {
    const id = setInterval(fetchLive, 60_000);
    return () => clearInterval(id);
  }, [fetchLive]);

  if (loading) return (
    <Box sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2, minHeight: 130, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Typography variant="caption" color="text.secondary">Consultando mercado…</Typography>
    </Box>
  );

  if (error || !rate) return (
    <Box sx={{ p: 2, border: '1px solid', borderColor: 'error.light', borderRadius: 2, bgcolor: '#fff8f8' }}>
      <Typography variant="caption" color="error">Sin conexión a fuentes en vivo</Typography>
    </Box>
  );

  const cfg = LIVE_SOURCE_CONFIG[rate.source] ?? LIVE_SOURCE_CONFIG['db_cache'];
  const hasAnomalies   = rate.anomalies.length > 0;
  const criticalAnomaly = rate.anomalies.find(a => a.severity === 'CRITICAL');

  return (
    <Card sx={{
      position: 'relative', overflow: 'hidden',
      bgcolor: hasAnomalies ? alpha(TOKENS.amber, 0.04) : alpha(TOKENS.green, 0.03),
      border: '1px solid',
      borderColor: criticalAnomaly ? 'error.light' : hasAnomalies ? 'warning.light' : alpha(TOKENS.green, 0.3),
    }}>
      <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3,
        bgcolor: cfg.color === 'success' ? TOKENS.green : cfg.color === 'warning' ? TOKENS.amber : TOKENS.blue }} />
      <CardContent sx={{ pb: '12px !important' }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={0.75}>
          <Typography variant="subtitle2" fontWeight={800}>{rate.pair} — EN VIVO</Typography>
          <Box display="flex" gap={0.5} alignItems="center">
            <LiveSourceBadge source={rate.source} confidence={rate.confidence} />
            {!rate.is_live && <Chip label="CACHÉ" size="small" color="default" sx={{ fontSize: '0.6rem', height: 18 }} />}
          </Box>
        </Box>
        <Box display="flex" justifyContent="space-between" mb={1}>
          <Box>
            <Typography variant="overline" sx={{ fontSize: '0.58rem', color: TOKENS.muted }}>Compra</Typography>
            <Typography variant="h4" fontWeight={900} sx={{ color: TOKENS.green, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
              {formatRate(rate.buy)}
            </Typography>
          </Box>
          <Box textAlign="center" sx={{ color: 'text.disabled' }}><Typography variant="body2">BOB</Typography></Box>
          <Box textAlign="right">
            <Typography variant="overline" sx={{ fontSize: '0.58rem', color: TOKENS.muted }}>Venta</Typography>
            <Typography variant="h4" fontWeight={900} sx={{ color: TOKENS.red, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
              {formatRate(rate.sell)}
            </Typography>
          </Box>
        </Box>
        <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={0.5}>
          <Typography variant="caption" color="text.secondary">
            Spread: <strong>{formatPercent(rate.spread_pct)}</strong>
            {' · '}Confianza: <strong style={{ color: confidenceColor(rate.confidence) }}>
              {confidenceDot(rate.confidence)} {(rate.confidence * 100).toFixed(0)}%
            </strong>
          </Typography>
          <Box display="flex" alignItems="center" gap={0.5}>
            {isStale(rate.timestamp) && (
              <Chip
                label="⚠ Precio desactualizado"
                size="small"
                color="warning"
                variant="outlined"
                sx={{ fontSize: '0.6rem', height: 18, fontWeight: 700 }}
              />
            )}
            <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.6rem' }}>
              {rate.timestamp ? format(new Date(rate.timestamp), 'HH:mm:ss', { locale: es }) : '—'}
            </Typography>
          </Box>
        </Box>
        {hasAnomalies && (
          <Box mt={0.75}>
            {rate.anomalies.map((a, i) => (
              <Alert key={i}
                severity={a.severity === 'CRITICAL' ? 'error' : a.severity === 'WARNING' ? 'warning' : 'info'}
                sx={{ py: 0, px: 1, fontSize: '0.65rem', mb: 0.25 }} icon={false}>
                {a.message}
              </Alert>
            ))}
          </Box>
        )}
        {rate.source_url && (
          <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.58rem', display: 'block', mt: 0.5 }}>
            <Link href={rate.source_url} target="_blank" rel="noopener" color="inherit" underline="hover">
              {rate.source_url}
            </Link>
          </Typography>
        )}
      </CardContent>
    </Card>
  );
};

const SourceBadge: React.FC<{
  method: string; sourceUrl?: string | null;
  confidence?: number; fetchedAt?: string | null;
}> = ({ method, sourceUrl, confidence, fetchedAt }) => {
  const cfg = SOURCE_CONFIG[method] ?? SOURCE_CONFIG['MANUAL'];
  const tooltipContent = (
    <Box sx={{ p: 0.5, maxWidth: 280 }}>
      <Typography variant="caption" fontWeight="bold" display="block">{cfg.label}</Typography>
      <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>{cfg.description}</Typography>
      {confidence !== undefined && (
        <Typography variant="caption" display="block">
          Confianza: <strong style={{ color: confidenceColor(confidence) }}>
            {confidenceDot(confidence)} {(confidence * 100).toFixed(0)}% — {confidenceLabel(confidence)}
          </strong>
        </Typography>
      )}
      {fetchedAt && (
        <Typography variant="caption" display="block">
          Consultado: {format(new Date(fetchedAt), 'dd/MM/yyyy HH:mm:ss', { locale: es })}
        </Typography>
      )}
      {sourceUrl && (
        <Typography variant="caption" display="block" sx={{ mt: 0.5, wordBreak: 'break-all' }}>
          URL: <Link href={sourceUrl} target="_blank" rel="noopener" color="inherit">{sourceUrl}</Link>
        </Typography>
      )}
    </Box>
  );
  return (
    <Tooltip title={tooltipContent} arrow placement="top">
      <Chip
        icon={cfg.icon as any} label={cfg.label} size="small" color={cfg.color} variant="filled"
        sx={{ bgcolor: cfg.bgcolor, cursor: 'help', fontWeight: 600, fontSize: '0.65rem', height: 22 }}
      />
    </Tooltip>
  );
};

const ConfidenceBar: React.FC<{ value: number }> = ({ value }) => {
  const pct   = Math.round(value * 100);
  const color = confidenceColor(value);
  return (
    <Tooltip title={`Confianza: ${pct}% — ${confidenceLabel(value)}`} arrow>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, cursor: 'help' }}>
        <Typography variant="caption" sx={{ color, fontWeight: 700, fontSize: '0.7rem', minWidth: 16 }}>
          {confidenceDot(value)}
        </Typography>
        <Box sx={{ width: 44, height: 4, bgcolor: '#e0e0e0', borderRadius: 2, overflow: 'hidden' }}>
          <Box sx={{ width: `${pct}%`, height: '100%', bgcolor: color, borderRadius: 2 }} />
        </Box>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem', minWidth: 28 }}>
          {pct}%
        </Typography>
      </Box>
    </Tooltip>
  );
};

// ── Auto Profit Mode Panel ────────────────────────────────────────────────────
const VARIANT_OPTIONS = [
  { value: '',               label: 'Estándar (billetes 20/50/100)' },
  { value: 'USD_CASH_LOOSE', label: '💵 USD Sueltos (5, 10)' },
  { value: 'USD_SMALL_BILLS',label: '🪙 USD Billetes 1 y 2' },
  { value: 'PEN_COINS',      label: '🪙 PEN Monedas' },
];

const AutoProfitPanel: React.FC = () => {
  const [currency, setCurrency]     = useState('USD');
  const [variant, setVariant]       = useState('');
  const [params, setParams]         = useState({
    max_buy_discount_pct:  1.5,
    max_sell_premium_pct:  1.5,
    min_spread_bob:        0.30,
    max_spread_pct:        5.0,
  });
  const [result, setResult]         = useState<any>(null);
  const [loading, setLoading]       = useState(false);
  const [allResults, setAllResults] = useState<Record<string, any> | null>(null);
  const [loadingAll, setLoadingAll] = useState(false);
  const { enqueueSnackbar }         = useSnackbar();

  const calculate = async () => {
    setLoading(true);
    setResult(null);
    try {
      const res = await api.post('/rates/profit-optimizer/', {
        currency,
        variant: variant || null,
        ...params,
      });
      setResult(res.data);
    } catch (e: any) {
      enqueueSnackbar(e?.response?.data?.error ?? 'Error al calcular', { variant: 'error' });
    } finally { setLoading(false); }
  };

  const calculateAll = async () => {
    setLoadingAll(true);
    setAllResults(null);
    try {
      const res = await api.get('/rates/profit-optimizer/?all=true');
      setAllResults(res.data.optimized_rates);
    } catch (e: any) {
      enqueueSnackbar(e?.response?.data?.error ?? 'Error al calcular', { variant: 'error' });
    } finally { setLoadingAll(false); }
  };

  return (
    <Box>
      <Alert severity="info" sx={{ mb: 3 }} icon={<AutoMode />}>
        <AlertTitle>Auto Profit Mode — Optimizador de Máximo Beneficio</AlertTitle>
        Calcula las tasas óptimas de compra y venta que <strong>maximizan el margen</strong> sin salir
        del rango competitivo del mercado paralelo boliviano. El sistema busca el punto en que
        pagamos menos al cliente (compra) y cobramos más (venta) dentro de los límites configurados.
      </Alert>

      <Grid container spacing={3}>
        {/* Parámetros */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3, height: '100%' }}>
            <Typography variant="subtitle1" fontWeight={800} mb={2.5} display="flex" alignItems="center" gap={1}>
              <FlashOn color="warning" /> Parámetros de Optimización
            </Typography>

            <Box mb={2}>
              <Typography variant="body2" fontWeight={600} mb={0.75}>Divisa</Typography>
              <TextField
                select size="small" fullWidth value={currency}
                onChange={e => setCurrency(e.target.value)}
                SelectProps={{ native: true }}
              >
                {['USD', 'EUR', 'BRL', 'ARS', 'CLP', 'PEN', 'GBP', 'CNY'].map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </TextField>
            </Box>

            <Box mb={2}>
              <Typography variant="body2" fontWeight={600} mb={0.75}>Variante de Efectivo</Typography>
              <TextField
                select size="small" fullWidth value={variant}
                onChange={e => setVariant(e.target.value)}
                SelectProps={{ native: true }}
              >
                {VARIANT_OPTIONS
                  .filter(v => v.value === '' || v.value.startsWith(currency) || (currency === 'PEN' && v.value === 'PEN_COINS'))
                  .map(v => <option key={v.value} value={v.value}>{v.label}</option>)
                }
              </TextField>
            </Box>

            <Divider sx={{ my: 2 }} />

            <Typography variant="caption" color="text.secondary" fontWeight={600} display="block" mb={1.5}>
              AJUSTE DE COMPETITIVIDAD
            </Typography>

            <Box mb={2.5}>
              <Box display="flex" justifyContent="space-between">
                <Typography variant="body2">Descuento máx. en compra</Typography>
                <Typography variant="body2" fontWeight={700} color="error.main">
                  -{params.max_buy_discount_pct.toFixed(1)}%
                </Typography>
              </Box>
              <Slider
                value={params.max_buy_discount_pct} min={0.5} max={5.0} step={0.1}
                onChange={(_, v) => setParams(p => ({ ...p, max_buy_discount_pct: v as number }))}
                color="error" size="small" sx={{ mt: 0.5 }}
              />
              <Typography variant="caption" color="text.secondary">
                Pagamos este % menos que el precio de mercado al cliente
              </Typography>
            </Box>

            <Box mb={2.5}>
              <Box display="flex" justifyContent="space-between">
                <Typography variant="body2">Premium máx. en venta</Typography>
                <Typography variant="body2" fontWeight={700} color="success.main">
                  +{params.max_sell_premium_pct.toFixed(1)}%
                </Typography>
              </Box>
              <Slider
                value={params.max_sell_premium_pct} min={0.5} max={5.0} step={0.1}
                onChange={(_, v) => setParams(p => ({ ...p, max_sell_premium_pct: v as number }))}
                color="success" size="small" sx={{ mt: 0.5 }}
              />
              <Typography variant="caption" color="text.secondary">
                Cobramos este % más que el precio de mercado al cliente
              </Typography>
            </Box>

            <Box mb={2.5}>
              <Box display="flex" justifyContent="space-between">
                <Typography variant="body2">Spread mínimo (BOB)</Typography>
                <Typography variant="body2" fontWeight={700}>{params.min_spread_bob.toFixed(2)}</Typography>
              </Box>
              <Slider
                value={params.min_spread_bob} min={0.05} max={1.0} step={0.05}
                onChange={(_, v) => setParams(p => ({ ...p, min_spread_bob: v as number }))}
                size="small" sx={{ mt: 0.5 }}
              />
            </Box>

            <Box mb={3}>
              <Box display="flex" justifyContent="space-between">
                <Typography variant="body2">Spread máximo</Typography>
                <Typography variant="body2" fontWeight={700}>{params.max_spread_pct.toFixed(1)}%</Typography>
              </Box>
              <Slider
                value={params.max_spread_pct} min={1.0} max={10.0} step={0.5}
                onChange={(_, v) => setParams(p => ({ ...p, max_spread_pct: v as number }))}
                size="small" sx={{ mt: 0.5 }}
              />
              <Typography variant="caption" color="text.secondary">
                Tope ético/regulatorio del margen permitido
              </Typography>
            </Box>

            <Button
              fullWidth variant="contained" color="warning" size="large"
              onClick={calculate} disabled={loading}
              startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <AutoMode />}
              sx={{ fontWeight: 800 }}
            >
              {loading ? 'Calculando…' : 'Calcular Tasa Óptima'}
            </Button>

            <Button
              fullWidth variant="outlined" size="small" sx={{ mt: 1 }}
              onClick={calculateAll} disabled={loadingAll}
              startIcon={loadingAll ? <CircularProgress size={14} color="inherit" /> : <MonetizationOn />}
            >
              {loadingAll ? 'Procesando…' : 'Calcular Todas las Divisas'}
            </Button>
          </Paper>
        </Grid>

        {/* Resultado individual */}
        <Grid item xs={12} md={8}>
          {result ? (
            <Paper sx={{ p: 3 }}>
              <Typography variant="subtitle1" fontWeight={800} mb={2} display="flex" alignItems="center" gap={1}>
                <MonetizationOn color="success" />
                Resultado Óptimo — {result.currency_code}{result.variant ? ` (${result.variant})` : ''}
              </Typography>

              {result.constraints_hit?.length > 0 && (
                <Alert severity="warning" sx={{ mb: 2, py: 0.5 }} icon={<InfoOutlined />}>
                  Restricciones activas: {result.constraints_hit.join(', ')}
                  {result.constraints_hit.includes('MIN_SPREAD_FORCED') && ' — Spread elevado para garantizar rentabilidad mínima'}
                  {result.constraints_hit.includes('MAX_SPREAD_CAPPED') && ' — Spread recortado al máximo permitido'}
                </Alert>
              )}

              <Grid container spacing={2} mb={2}>
                <Grid item xs={6} sm={3}>
                  <Paper sx={{ p: 2, bgcolor: alpha(TOKENS.muted, 0.08), textAlign: 'center' }}>
                    <Typography variant="caption" color="text.secondary" display="block">Mercado — Compra</Typography>
                    <Typography variant="h5" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {result.market_buy?.toFixed(4)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">BOB (referencia)</Typography>
                  </Paper>
                </Grid>
                <Grid item xs={6} sm={3}>
                  <Paper sx={{ p: 2, bgcolor: alpha(TOKENS.muted, 0.08), textAlign: 'center' }}>
                    <Typography variant="caption" color="text.secondary" display="block">Mercado — Venta</Typography>
                    <Typography variant="h5" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {result.market_sell?.toFixed(4)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">BOB (referencia)</Typography>
                  </Paper>
                </Grid>
                <Grid item xs={6} sm={3}>
                  <Paper sx={{ p: 2, bgcolor: alpha(TOKENS.green, 0.08), border: '2px solid', borderColor: 'success.light', textAlign: 'center' }}>
                    <Typography variant="caption" color="success.main" display="block" fontWeight={600}>
                      ÓPTIMO — Compra
                    </Typography>
                    <Typography variant="h4" fontWeight={900} color="success.main" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {result.optimal_buy?.toFixed(4)}
                    </Typography>
                    <Typography variant="caption" color="success.dark" fontWeight={600}>
                      -{result.buy_discount_pct?.toFixed(2)}% vs mercado
                    </Typography>
                  </Paper>
                </Grid>
                <Grid item xs={6} sm={3}>
                  <Paper sx={{ p: 2, bgcolor: alpha(TOKENS.red, 0.08), border: '2px solid', borderColor: 'error.light', textAlign: 'center' }}>
                    <Typography variant="caption" color="error.main" display="block" fontWeight={600}>
                      ÓPTIMO — Venta
                    </Typography>
                    <Typography variant="h4" fontWeight={900} color="error.main" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {result.optimal_sell?.toFixed(4)}
                    </Typography>
                    <Typography variant="caption" color="error.dark" fontWeight={600}>
                      +{result.sell_premium_pct?.toFixed(2)}% vs mercado
                    </Typography>
                  </Paper>
                </Grid>
              </Grid>

              {/* Métricas de beneficio */}
              <Box sx={{ p: 2, bgcolor: alpha('#ffd700', 0.10), border: '1px solid', borderColor: alpha('#ffd700', 0.4), borderRadius: 2, mb: 2 }}>
                <Grid container spacing={2}>
                  <Grid item xs={6} sm={3} textAlign="center">
                    <Typography variant="caption" color="text.secondary" display="block">Margen por Unidad</Typography>
                    <Typography variant="h5" fontWeight={800} color="warning.dark">
                      {result.optimal_spread?.toFixed(4)} BOB
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={3} textAlign="center">
                    <Typography variant="caption" color="text.secondary" display="block">Spread Efectivo</Typography>
                    <Typography variant="h5" fontWeight={800} color="warning.dark">
                      {result.optimal_spread_pct?.toFixed(2)}%
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={3} textAlign="center">
                    <Typography variant="caption" color="text.secondary" display="block">Spread Mercado</Typography>
                    <Typography variant="h5" fontWeight={700} color="text.secondary">
                      {result.market_spread_pct?.toFixed(2)}%
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={3} textAlign="center">
                    <Typography variant="caption" color="text.secondary" display="block">Fuente</Typography>
                    <Chip
                      label={result.source_used?.toUpperCase()}
                      size="small"
                      color={result.source_used === 'binance' ? 'success' : 'warning'}
                      sx={{ fontWeight: 700 }}
                    />
                    <Typography variant="caption" color="text.secondary" display="block">
                      Confianza: {((result.confidence ?? 0) * 100).toFixed(0)}%
                    </Typography>
                  </Grid>
                </Grid>
              </Box>

              {result.notes && (
                <Alert severity="info" sx={{ mb: 2, py: 0.5 }} icon={false}>
                  <Typography variant="caption">{result.notes}</Typography>
                </Alert>
              )}

              <Alert severity="warning" sx={{ py: 0.5 }}>
                <Typography variant="caption">
                  <strong>Nota operacional:</strong> Estas tasas son sugerencias del optimizador.
                  Aplíquelas solo si están dentro de las políticas vigentes.
                  Use el botón de edición manual en la tabla de tasas para persistirlas.
                </Typography>
              </Alert>
            </Paper>
          ) : (
            <Paper sx={{ p: 4, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 280, bgcolor: alpha(TOKENS.blue, 0.03), border: '2px dashed', borderColor: alpha(TOKENS.blue, 0.2) }}>
              <AutoMode sx={{ fontSize: 56, color: alpha(TOKENS.blue, 0.3), mb: 2 }} />
              <Typography variant="h6" color="text.secondary" fontWeight={600}>Configura los parámetros</Typography>
              <Typography variant="body2" color="text.disabled" textAlign="center" mt={1} maxWidth={360}>
                Ajusta los sliders y presiona "Calcular Tasa Óptima" para ver las tasas que maximizan tu margen.
              </Typography>
            </Paper>
          )}

          {/* Resultados de todas las divisas */}
          {allResults && (
            <Paper sx={{ p: 3, mt: 3 }}>
              <Typography variant="subtitle1" fontWeight={800} mb={2}>
                Optimización Global — Todas las Divisas
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Divisa</TableCell>
                      <TableCell align="right">Mkt Compra</TableCell>
                      <TableCell align="right">Mkt Venta</TableCell>
                      <TableCell align="right">Óptimo Compra</TableCell>
                      <TableCell align="right">Óptimo Venta</TableCell>
                      <TableCell align="right">Margen/Unit</TableCell>
                      <TableCell align="right">Spread %</TableCell>
                      <TableCell>Fuente</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {Object.entries(allResults).map(([code, r]: [string, any]) => (
                      <TableRow key={code} hover>
                        <TableCell>
                          <Typography fontWeight={700}>{code}</Typography>
                          {r.variant && <Chip label={r.variant} size="small" sx={{ fontSize: '0.6rem', height: 16, ml: 0.5 }} />}
                        </TableCell>
                        <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {r.market_buy?.toFixed(4)}
                        </TableCell>
                        <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {r.market_sell?.toFixed(4)}
                        </TableCell>
                        <TableCell align="right">
                          <Typography color="success.main" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                            {r.optimal_buy?.toFixed(4)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Typography color="error.main" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                            {r.optimal_sell?.toFixed(4)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Chip
                            label={`${r.optimal_spread?.toFixed(3)} BOB`}
                            size="small"
                            color={r.optimal_spread > 0.5 ? 'success' : 'default'}
                            sx={{ fontWeight: 700, fontSize: '0.65rem' }}
                          />
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="body2" fontWeight={600}
                            sx={{ color: r.optimal_spread_pct > 3 ? 'success.main' : r.optimal_spread_pct > 1 ? 'warning.main' : 'text.secondary' }}>
                            {r.optimal_spread_pct?.toFixed(2)}%
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={r.source_used?.toUpperCase()}
                            size="small"
                            color={r.source_used === 'binance' ? 'success' : 'default'}
                            sx={{ fontSize: '0.6rem', height: 20 }}
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          )}
        </Grid>
      </Grid>
    </Box>
  );
};

// ── Cash Variants Panel ───────────────────────────────────────────────────────
const CashVariantsPanel: React.FC = () => {
  const [variants, setVariants]   = useState<Record<string, any>>({});
  const [loading, setLoading]     = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { enqueueSnackbar }       = useSnackbar();
  const { user }                  = useAuth();

  const loadVariants = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/rates/cash-variants/');
      setVariants(res.data.variants ?? {});
    } catch {
      enqueueSnackbar('Error al cargar variantes de efectivo', { variant: 'error' });
    } finally { setLoading(false); }
  }, [enqueueSnackbar]);

  useEffect(() => { loadVariants(); }, [loadVariants]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.post('/rates/cash-variants/');
      enqueueSnackbar('Recálculo de variantes encolado', { variant: 'success' });
      setTimeout(loadVariants, 3000);
    } catch { enqueueSnackbar('Error al refrescar', { variant: 'error' }); }
    finally { setRefreshing(false); }
  };

  if (loading) return (
    <Box display="flex" justifyContent="center" p={4}>
      <CircularProgress />
    </Box>
  );

  const variantDefs = [
    { code: 'USD',              icon: '💵', name: 'USD Estándar',         desc: 'Billetes 20/50/100 en buen estado', isStandard: true },
    { code: 'USD_CASH_LOOSE',   icon: '💵', name: 'USD Sueltos/Sencillos', desc: 'Billetes de 5 y 10 dólares',       isStandard: false },
    { code: 'USD_SMALL_BILLS',  icon: '🪙', name: 'USD Billetes 1 y 2',   desc: 'Muy baja liquidez en Bolivia',     isStandard: false },
    { code: 'PEN',              icon: '🇵🇪', name: 'PEN Estándar',         desc: 'Billetes sol peruano',             isStandard: true },
    { code: 'PEN_COINS',        icon: '🪙', name: 'PEN Monedas',           desc: 'Monedas sol peruano',              isStandard: false },
  ];

  return (
    <Box>
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={3}>
        <Box>
          <Typography variant="h6" fontWeight={800}>Variantes de Efectivo Físico</Typography>
          <Typography variant="body2" color="text.secondary">
            Tasas diferenciadas según denominación y condición física del billete.
            La casa de cambios aplica descuentos en compra para divisas de baja liquidez.
          </Typography>
        </Box>
        {user?.role === 'ADMIN' && (
          <Button
            variant="outlined" size="small" startIcon={<Refresh />}
            onClick={handleRefresh} disabled={refreshing}
          >
            {refreshing ? 'Recalculando…' : 'Recalcular'}
          </Button>
        )}
      </Box>

      <Alert severity="info" sx={{ mb: 3 }} icon={<Savings />}>
        <strong>Lógica de negocio:</strong> La tasa de <strong>VENTA</strong> es igual al estándar
        (cobramos lo mismo al cliente). La tasa de <strong>COMPRA</strong> es inferior —
        pagamos menos al cliente por billetes de menor liquidez o difícil recolocación en el mercado.
      </Alert>

      <Grid container spacing={2}>
        {variantDefs.map((def) => {
          const v = variants[def.code];
          const isVariant = !def.isStandard;

          return (
            <Grid item xs={12} sm={6} md={4} key={def.code}>
              <Card sx={{
                position: 'relative', overflow: 'hidden',
                border: '1px solid',
                borderColor: isVariant ? alpha('#ff9800', 0.4) : 'divider',
                bgcolor: isVariant ? alpha('#fff8e1', 0.5) : 'white',
              }}>
                <Box sx={{
                  position: 'absolute', top: 0, left: 0, right: 0, height: 3,
                  bgcolor: isVariant ? '#ff9800' : TOKENS.blue,
                }} />
                <CardContent>
                  <Box display="flex" alignItems="center" gap={1} mb={1.5}>
                    <Typography sx={{ fontSize: '1.5rem', lineHeight: 1 }}>{def.icon}</Typography>
                    <Box>
                      <Typography variant="subtitle2" fontWeight={800}>{def.name}</Typography>
                      <Typography variant="caption" color="text.secondary">{def.desc}</Typography>
                    </Box>
                    {isVariant && (
                      <Chip label="VARIANTE" size="small"
                        sx={{ ml: 'auto', bgcolor: alpha('#ff9800', 0.15), color: '#e65100',
                             fontSize: '0.6rem', height: 18, fontWeight: 700 }} />
                    )}
                  </Box>

                  {v ? (
                    <>
                      <Box display="flex" justifyContent="space-between" mb={1}>
                        <Box>
                          <Typography variant="overline" sx={{ fontSize: '0.6rem', color: TOKENS.muted }}>Compra</Typography>
                          <Typography variant="h5" fontWeight={900} color="success.main" sx={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
                            {parseFloat(v.buy_rate).toFixed(4)}
                          </Typography>
                        </Box>
                        <Box textAlign="right">
                          <Typography variant="overline" sx={{ fontSize: '0.6rem', color: TOKENS.muted }}>Venta</Typography>
                          <Typography variant="h5" fontWeight={900} color="error.main" sx={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
                            {parseFloat(v.sell_rate).toFixed(4)}
                          </Typography>
                        </Box>
                      </Box>

                      <Box display="flex" justifyContent="space-between" alignItems="center">
                        <Typography variant="caption" color="text.secondary">
                          Spread: <strong>{parseFloat(v.spread_pct).toFixed(2)}%</strong>
                        </Typography>
                        {isVariant && v.buy_discount_pct > 0 && (
                          <Chip
                            label={`Compra -${parseFloat(v.buy_discount_pct).toFixed(1)}%`}
                            size="small"
                            color="warning"
                            sx={{ fontSize: '0.6rem', height: 20, fontWeight: 700 }}
                          />
                        )}
                      </Box>

                      {isVariant && v.buy_discount_bob > 0 && (
                        <Typography variant="caption" color="text.disabled" display="block" mt={0.5}>
                          Descuento: {parseFloat(v.buy_discount_bob).toFixed(4)} BOB/unidad vs estándar
                        </Typography>
                      )}
                    </>
                  ) : (
                    <Typography variant="caption" color="text.disabled" fontStyle="italic">
                      Sin datos disponibles — actualice para calcular
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>
          );
        })}
      </Grid>
    </Box>
  );
};

// ── Digital Rates Section (Tab 0) ─────────────────────────────────────────────
const DIGITAL_CURRENCIES = ['USD', 'EUR', 'BRL', 'PEN', 'CLP', 'ARS'];

const DigitalRatesSection: React.FC = () => {
  return (
    <Box>
      {/* Motor FX — Cards en tiempo real */}
      <Box mb={4}>
        <Box display="flex" alignItems="center" gap={1.5} mb={2}>
          <Box>
            <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem', letterSpacing: 1 }}>
              MOTOR FX — FUENTE EN TIEMPO REAL
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Tasas obtenidas directamente desde P2P crypto y scraping. Confianza, anomalías y trazabilidad completa.
            </Typography>
          </Box>
        </Box>
        <Grid container spacing={2}>
          {DIGITAL_CURRENCIES.map(cur => (
            <Grid item xs={12} sm={6} md={4} key={cur}>
              <RateCard currency={cur} refreshInterval={60_000} />
            </Grid>
          ))}
        </Grid>
      </Box>

      {/* Todas las fuentes por plataforma */}
      <Box mb={4}>
        <Box mb={1.5}>
          <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem', letterSpacing: 1 }}>
            TODAS LAS PLATAFORMAS — TIEMPO REAL
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Tasas individuales por fuente: Binance, Bitget, Bybit, OKX, El Dorado, Wallbit, Airtm, SaldoAR y más.
            Actualización automática cada 90 segundos.
          </Typography>
        </Box>
        <SourcesGrid />
      </Box>

      {/* Consenso WebSocket — RatesPanel */}
      <Box>
        <Box mb={1.5}>
          <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem', letterSpacing: 1 }}>
            CONSENSO MULTI-FUENTE (WEBSOCKET)
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Tasas de consenso calculadas en tiempo real ponderando múltiples fuentes.
            Variación 24h, tendencia y confianza global.
          </Typography>
        </Box>
        <RatesPanel />
      </Box>
    </Box>
  );
};

// ── Predictions Section (Tab 1) ───────────────────────────────────────────────
const PREDICTION_PAIRS = [
  { pair: 'USD-BOB', color: '#2563eb' },
  { pair: 'EUR-BOB', color: '#7c3aed' },
  { pair: 'BRL-BOB', color: '#059669' },
  { pair: 'PEN-BOB', color: '#d97706' },
  { pair: 'CLP-BOB', color: '#db2777' },
  { pair: 'ARS-BOB', color: '#dc2626' },
];

const PredictionsSection: React.FC = () => {
  const [horizon, setHorizon] = React.useState<'1h' | '4h' | '24h' | '7d'>('24h');

  return (
    <Box>
      {/* Header con selector de horizonte */}
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={2} flexWrap="wrap" gap={1}>
        <Box>
          <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem', letterSpacing: 1 }}>
            MOTOR ML — ENSEMBLE DE 5 MODELOS
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Prophet · BiLSTM · XGBoost · ARIMA · Ridge. Pesos dinámicos por PSI drift.
            Intervalo de confianza 95%.
          </Typography>
        </Box>
        <Box display="flex" gap={0.5}>
          {(['1h', '4h', '24h', '7d'] as const).map(h => (
            <Chip
              key={h}
              label={h}
              size="small"
              onClick={() => setHorizon(h)}
              color={horizon === h ? 'info' : 'default'}
              variant={horizon === h ? 'filled' : 'outlined'}
              sx={{ fontWeight: 700, fontSize: '0.7rem', cursor: 'pointer' }}
            />
          ))}
        </Box>
      </Box>

      <Alert severity="info" sx={{ mb: 2.5, py: 0.5 }} icon={<Psychology />}>
        Los pronósticos son estimaciones estadísticas basadas en datos históricos.
        <strong> No garantizan valores futuros.</strong> Úsalos como referencia operacional, no como base única de decisión.
      </Alert>

      <Grid container spacing={2}>
        {PREDICTION_PAIRS.map(({ pair, color }) => (
          <Grid item xs={12} sm={6} md={4} key={pair}>
            <PredictionCard pair={pair} horizon={horizon} color={color} />
          </Grid>
        ))}
      </Grid>
    </Box>
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

  const handleEdit = (rate: any) => {
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
          <Grid container spacing={2} mb={3}>
            {rates.slice(0, 4).map((rate) => {
              const scale      = rate.currency_from?.scale_factor ?? 1;
              const scaled     = isScaled(scale);
              const isInfer    = rate.source_method === 'INFERENCE';
              const spreadNum  = parseFloat(rate.spread_percentage ?? '0');
              const isHighSprd = spreadNum > 3;
              const conf       = parseFloat(rate.confidence ?? '1');
              const accentColor = isInfer ? TOKENS.red : isHighSprd ? TOKENS.amber : TOKENS.blue;
              return (
                <Grid item xs={12} sm={6} md={3} key={rate.id}>
                  <Card sx={{
                    position: 'relative', overflow: 'hidden',
                    bgcolor: isInfer ? alpha(TOKENS.red, 0.04) : 'white',
                    borderColor: isInfer ? alpha(TOKENS.red, 0.3) : TOKENS.border,
                    transition: 'box-shadow 0.2s, transform 0.2s',
                    '&:hover': { transform: 'translateY(-1px)', boxShadow: '0 6px 20px rgba(15,23,42,0.10)' },
                  }}>
                    <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, bgcolor: accentColor, borderRadius: '14px 14px 0 0' }} />
                    <CardContent>
                      <Box display="flex" alignItems="center" justifyContent="space-between" mb={0.5} flexWrap="wrap" gap={0.5}>
                        <Typography variant="subtitle1" fontWeight={800} sx={{ color: TOKENS.text }}>
                          {rate.currency_from?.code}
                          <Typography component="span" sx={{ color: TOKENS.muted, fontWeight: 400, mx: 0.5 }}>/</Typography>
                          {rate.currency_to?.code}
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                          {scaled && <Chip label={`×${formatScale(scale)}`} size="small" sx={{ bgcolor: alpha(TOKENS.amber, 0.15), color: TOKENS.amber, fontSize: '0.6rem', height: 18, fontWeight: 700 }} />}
                          <SourceBadge method={rate.source_method} sourceUrl={rate.source_url} confidence={conf} fetchedAt={rate.fetched_at} />
                        </Box>
                      </Box>
                      <Box display="flex" justifyContent="space-between" mt={1.5}>
                        <Box>
                          <Typography variant="overline" sx={{ fontSize: '0.6rem', color: TOKENS.muted }}>Compra</Typography>
                          <Typography variant="h5" fontWeight={800} sx={{ color: TOKENS.green, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
                            {formatRate(rate.buy_rate)}
                          </Typography>
                        </Box>
                        <Box textAlign="right">
                          <Typography variant="overline" sx={{ fontSize: '0.6rem', color: TOKENS.muted }}>Venta</Typography>
                          <Typography variant="h5" fontWeight={800} sx={{ color: TOKENS.red, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
                            {formatRate(rate.sell_rate)}
                          </Typography>
                        </Box>
                      </Box>
                      <Box sx={{ mt: 1.25, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                        <Typography variant="caption" sx={{ color: isHighSprd ? TOKENS.amber : TOKENS.muted, fontWeight: isHighSprd ? 700 : 400 }}>
                          Spread: {rate.spread_percentage}%{isHighSprd ? ' ⚠' : ''}
                        </Typography>
                        <ConfidenceBar value={conf} />
                      </Box>
                      {rate.is_primary && (
                        <Chip label="✓ EN USO" size="small" color="primary" variant="outlined"
                          sx={{ fontSize: '0.6rem', height: 18, mt: 0.75 }} />
                      )}
                    </CardContent>
                  </Card>
                </Grid>
              );
            })}
          </Grid>

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
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Par</TableCell>
                  <TableCell>Mercado</TableCell>
                  <TableCell align="right">Tasa mercado</TableCell>
                  <TableCell align="right">Compra</TableCell>
                  <TableCell align="right">Venta</TableCell>
                  <TableCell align="right">Spread</TableCell>
                  <TableCell>Escala</TableCell>
                  <TableCell>Fuente / URL</TableCell>
                  <TableCell>Confianza</TableCell>
                  <TableCell>Actualizado</TableCell>
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
                  const conf        = parseFloat(rate.confidence ?? '1');

                  return (
                    <TableRow key={rate.id} hover
                      sx={isInference ? { bgcolor: '#fff8f8' } : undefined}>
                      <TableCell>
                        <Box display="flex" alignItems="center" gap={0.5}>
                          <Typography fontWeight="bold">
                            {rate.currency_from?.code} / {rate.currency_to?.code}
                          </Typography>
                          {rate.is_primary && (
                            <Tooltip title="Tasa activa — usada en transacciones" arrow>
                              <Chip label="★" size="small" color="primary"
                                sx={{ fontSize: '0.6rem', height: 16, minWidth: 0, px: 0.5 }} />
                            </Tooltip>
                          )}
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={
                            rate.market_type?.includes('paralelo_digital') ? 'Digital' :
                            rate.market_type?.includes('paralelo') ? 'Paralelo' :
                            rate.market_type === 'digital' ? 'Digital' : 'Paralelo'
                          }
                          size="small"
                          color="default"
                          variant="outlined"
                        />
                      </TableCell>
                      <TableCell align="right">
                        <Tooltip title="Mid-rate paralelo por unidad" arrow>
                          <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums', cursor: 'help' }}>
                            {((parseFloat(rate.buy_rate) + parseFloat(rate.sell_rate)) / 2).toFixed(4)}
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
                      <TableCell align="right">
                        <Typography variant="body2" fontWeight={parseFloat(rate.spread_percentage) > 3 ? 700 : 400}
                          color={parseFloat(rate.spread_percentage) > 3 ? 'warning.main' : 'text.secondary'}>
                          {rate.spread_percentage}%
                        </Typography>
                      </TableCell>
                      <TableCell>
                        {scaled
                          ? <Chip label={`×${formatScale(scale)}`} size="small"
                              sx={{ bgcolor: 'warning.main', color: 'warning.contrastText', fontSize: '0.65rem' }} />
                          : <Typography variant="caption" color="text.secondary">×1</Typography>
                        }
                        <Typography variant="caption" color="text.secondary" display="block">{rateLabel}</Typography>
                      </TableCell>

                      {/* Source with clickable URL */}
                      <TableCell>
                        <Box display="flex" flexDirection="column" gap={0.5}>
                          <SourceBadge
                            method={rate.source_method}
                            sourceUrl={rate.source_url}
                            confidence={conf}
                            fetchedAt={rate.fetched_at}
                          />
                          {rate.source_url ? (
                            <Link
                              href={rate.source_url}
                              target="_blank"
                              rel="noopener"
                              underline="hover"
                              sx={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap', display: 'block', fontSize: '0.65rem', color: 'text.secondary' }}
                            >
                              {rate.source_url}
                            </Link>
                          ) : (
                            <Typography variant="caption" color="text.disabled" fontStyle="italic">
                              Sin URL
                            </Typography>
                          )}
                        </Box>
                      </TableCell>

                      {/* Confidence indicator */}
                      <TableCell>
                        <ConfidenceBar value={conf} />
                      </TableCell>

                      {/* Last updated */}
                      <TableCell>
                        {rate.fetched_at ? (
                          <Typography variant="caption">
                            {format(new Date(rate.fetched_at), 'dd/MM HH:mm', { locale: es })}
                          </Typography>
                        ) : (
                          <Typography variant="caption" color="text.disabled">—</Typography>
                        )}
                      </TableCell>

                      {/* Status */}
                      <TableCell>
                        <Box display="flex" flexDirection="column" gap={0.5}>
                          <Chip
                            label={rate.valid_until ? 'Vencida' : 'Vigente'}
                            color={rate.valid_until ? 'default' : 'success'}
                            size="small"
                          />
                          {rate.is_validated && (
                            <Chip label="✓ Validada" color="primary" size="small" variant="outlined"
                              icon={<CheckCircle sx={{ fontSize: 12 }} />} />
                          )}
                          {isInference && !rate.is_validated && (
                            <Chip label="⚠ Sin validar" color="error" size="small" variant="outlined" />
                          )}
                        </Box>
                      </TableCell>

                      {user?.role === 'ADMIN' && (
                        <TableCell>
                          <Tooltip title={isInference ? 'Editar y validar tasa estimada' : 'Editar tasa'}>
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
