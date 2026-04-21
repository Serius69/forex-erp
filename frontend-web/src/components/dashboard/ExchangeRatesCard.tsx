import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, CardContent, Typography, Grid, Box,
  Chip, IconButton, Menu, MenuItem, Divider, Skeleton, Tooltip,
  LinearProgress, Collapse,
} from '@mui/material';
import {
  TrendingUp, TrendingDown, TrendingFlat, MoreVert, History,
  CheckCircle, Warning, Error as ErrorIcon, Star, StarBorder,
  ExpandMore, ExpandLess, Refresh,
} from '@mui/icons-material';
import { motion, AnimatePresence } from 'framer-motion';
import { parseRates, getAccessToken } from '../../services/api';
import { formatRate, isScaled, formatScale } from '../../utils/finance';

// ── API helpers ───────────────────────────────────────────────────────────────
const API_BASE = (import.meta as any).env?.VITE_API_URL ?? '/api';

async function fetchEnginePrimary(): Promise<Record<string, any>> {
  try {
    const res = await fetch(`${API_BASE}/rates/engine/primary/`, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
    });
    if (!res.ok) return {};
    const data = await res.json();
    return data.rates ?? {};
  } catch {
    return {};
  }
}

async function fetchEngineSummary(currency: string): Promise<any | null> {
  try {
    const res = await fetch(`${API_BASE}/rates/engine/summary/?currency=${currency}`, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ── Source badge (same palette as Rates.tsx) ─────────────────────────────────
const SOURCE_STYLES: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
  API:       { label: 'API',      color: '#2e7d32', bg: '#e8f5e9', icon: <CheckCircle sx={{ fontSize: 11 }} /> },
  SCRAP:     { label: 'SCRAP',   color: '#e65100', bg: '#fff3e0', icon: <Warning      sx={{ fontSize: 11 }} /> },
  MANUAL:    { label: 'MANUAL',  color: '#1565c0', bg: '#e3f2fd', icon: <CheckCircle sx={{ fontSize: 11 }} /> },
  INFERENCE: { label: 'ESTIMADA', color: '#c62828', bg: '#ffebee', icon: <ErrorIcon   sx={{ fontSize: 11 }} /> },
};

const SourceMicroBadge: React.FC<{ method?: string; url?: string | null; fetchedAt?: string | null; confidence?: number }> = ({
  method, url, fetchedAt, confidence,
}) => {
  if (!method) return null;
  const s = SOURCE_STYLES[method] ?? SOURCE_STYLES['MANUAL'];
  const tip = [
    `Fuente: ${s.label}`,
    confidence !== undefined ? `Confianza: ${(confidence * 100).toFixed(0)}%` : null,
    fetchedAt ? `Actualizado: ${new Date(fetchedAt).toLocaleTimeString('es-BO')}` : null,
    url ? `URL: ${url}` : null,
  ].filter(Boolean).join('\n');

  return (
    <Tooltip title={<Box component="span" sx={{ whiteSpace: 'pre-line' }}>{tip}</Box>} arrow>
      <Box
        component="span"
        sx={{
          display: 'inline-flex', alignItems: 'center', gap: '2px',
          px: '5px', py: '1px', borderRadius: '4px',
          bgcolor: s.bg, color: s.color,
          fontSize: '0.6rem', fontWeight: 700,
          cursor: 'help', verticalAlign: 'middle',
          border: `1px solid ${s.color}33`,
        }}
      >
        {s.icon}
        {s.label}
      </Box>
    </Tooltip>
  );
};

interface RateEntry {
  buy:           number;
  sell:          number;
  official:      number;
  scale_factor:  number;
  market_type:   'official' | 'parallel' | string;
  name?:         string;
  trend?:        'up' | 'down' | 'flat';
  changePercent?: number;
  // Traceability (Phase 7)
  source_method?:  'API' | 'SCRAP' | 'MANUAL' | 'INFERENCE';
  source_url?:     string | null;
  fetched_at?:     string | null;
  confidence?:     number;
  is_validated?:   boolean;
  requires_warning?: boolean;
  // Motor central (Phase 10)
  is_primary?:            boolean;
  is_safe_for_transaction?: boolean;
  avg_rate?:              number;
}

interface SourceComparison {
  source:        string;
  source_method: string;
  market_type:   string;
  buy:           string;
  sell:          string;
  official:      string;
  avg:           string;
  confidence:    number;
  fetched_at:    string | null;
  source_url:    string | null;
  is_validated:  boolean;
}

interface RateStatistics {
  weighted_avg_buy:  string | null;
  weighted_avg_sell: string | null;
  median_buy:        string | null;
  median_sell:       string | null;
  best_buy:          string | null;
  best_sell:         string | null;
  source_count:      number;
  divergence_pct:    number;
  has_divergence:    boolean;
}

interface ExchangeRatesCardProps {
  rates: Record<string, any>;
}

const CURRENCY_META: Record<string, { name: string; flag: string; color: string }> = {
  USD: { name: 'Dólar EE.UU.', flag: '🇺🇸', color: '#4caf50' },
  EUR: { name: 'Euro',          flag: '🇪🇺', color: '#2196f3' },
  BRL: { name: 'Real',          flag: '🇧🇷', color: '#ffeb3b' },
  ARS: { name: 'Peso Arg.',     flag: '🇦🇷', color: '#00bcd4' },
  CLP: { name: 'Peso Chileno',  flag: '🇨🇱', color: '#f44336' },
  PEN: { name: 'Sol Peruano',   flag: '🇵🇪', color: '#ff9800' },
};

// ── Source comparison table ───────────────────────────────────────────────────
const SourceComparisonTable: React.FC<{ sources: SourceComparison[]; stats: RateStatistics | null }> = ({
  sources, stats,
}) => (
  <Box sx={{ mt: 1.5, pt: 1, borderTop: '1px dashed', borderColor: 'divider' }}>
    <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
      Comparación entre fuentes ({sources.length})
    </Typography>
    {sources.map((s) => (
      <Box key={`${s.source}-${s.market_type}`}
        sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
          <SourceMicroBadge method={s.source_method} url={s.source_url} fetchedAt={s.fetched_at} confidence={s.confidence} />
          <Typography variant="caption" color="text.secondary" noWrap sx={{ maxWidth: 80, fontSize: '0.6rem' }}>
            {s.source}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Typography variant="caption" color="success.main" sx={{ fontVariantNumeric: 'tabular-nums', fontSize: '0.65rem' }}>
            C: {parseFloat(s.buy).toFixed(4)}
          </Typography>
          <Typography variant="caption" color="error.main" sx={{ fontVariantNumeric: 'tabular-nums', fontSize: '0.65rem' }}>
            V: {parseFloat(s.sell).toFixed(4)}
          </Typography>
        </Box>
      </Box>
    ))}
    {stats && (
      <Box sx={{ mt: 1, pt: 0.75, borderTop: '1px solid', borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
          {stats.weighted_avg_buy && (
            <Tooltip title="Promedio ponderado por confianza de todas las fuentes" arrow>
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.6rem', cursor: 'help' }}>
                Ṽ compra: <strong>{parseFloat(stats.weighted_avg_buy).toFixed(4)}</strong>
              </Typography>
            </Tooltip>
          )}
          {stats.median_buy && (
            <Tooltip title="Mediana de tasas de compra" arrow>
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.6rem', cursor: 'help' }}>
                Med: <strong>{parseFloat(stats.median_buy).toFixed(4)}</strong>
              </Typography>
            </Tooltip>
          )}
          {stats.has_divergence && (
            <Chip
              label={`Divergencia ${stats.divergence_pct.toFixed(1)}%`}
              size="small" color="warning" variant="outlined"
              sx={{ height: 16, fontSize: '0.55rem' }}
            />
          )}
        </Box>
      </Box>
    )}
  </Box>
);

// ── Tarjeta individual de divisa ──────────────────────────────────────────────
const RateDisplay: React.FC<{
  currency:       string;
  rate:           RateEntry;
  onMenu:         (e: React.MouseEvent<HTMLElement>, code: string) => void;
  primaryData?:   Record<string, any>;
  onExpandSource: (code: string) => void;
  sourceExpanded: boolean;
  sourceSummary?: { sources: SourceComparison[]; stats: RateStatistics | null } | null;
}> = ({ currency, rate, onMenu, primaryData, onExpandSource, sourceExpanded, sourceSummary }) => {
  const meta    = CURRENCY_META[currency];
  const scaled  = isScaled(rate.scale_factor);
  const scaleLabel = scaled ? `por ${formatScale(rate.scale_factor)} ${currency}` : `por 1 ${currency}`;

  const TrendIcon = rate.trend === 'up'   ? TrendingUp
                  : rate.trend === 'down' ? TrendingDown
                  : TrendingFlat;
  const trendColor = rate.trend === 'up'   ? 'success'
                   : rate.trend === 'down' ? 'error'
                   : 'disabled';

  const isInference   = rate.source_method === 'INFERENCE';
  const isPrimary     = primaryData ? primaryData[currency]?.is_primary === true : rate.is_primary;
  const isSafeForTx   = primaryData ? primaryData[currency]?.is_safe_for_transaction !== false : true;

  return (
    <motion.div initial={{ opacity: 0, scale: 0.93 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.25 }}>
      <Box sx={{
        p: 2, borderRadius: 2,
        bgcolor: 'background.default',
        border: '1px solid',
        borderColor: isInference ? 'error.light' : isPrimary ? 'primary.light' : 'divider',
        position: 'relative', overflow: 'hidden',
        '&:hover': { borderColor: isInference ? 'error.main' : 'primary.main', boxShadow: 1 },
      }}>
        {/* Barra de color superior — roja si INFERENCE, azul si primaria */}
        <Box sx={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 4,
          bgcolor: isInference ? 'error.main' : isPrimary ? 'primary.main' : (meta?.color ?? 'grey.300'),
        }} />

        {/* Encabezado: bandera + código + source badge + menú */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="h6" lineHeight={1}>{meta?.flag ?? '💱'}</Typography>
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap' }}>
                <Typography variant="subtitle2" fontWeight={700}>{currency}</Typography>
                {/* PRIMARY badge */}
                {isPrimary && (
                  <Tooltip title="Tasa primaria — usada en todas las transacciones del sistema" arrow>
                    <Chip
                      icon={<Star sx={{ fontSize: '10px !important' }} />}
                      label="PRIMARIA"
                      size="small"
                      sx={{
                        height: 17, fontSize: '0.55rem', fontWeight: 700,
                        bgcolor: 'primary.main', color: 'primary.contrastText',
                        cursor: 'help',
                        '& .MuiChip-icon': { color: 'primary.contrastText' },
                      }}
                    />
                  </Tooltip>
                )}
                {!isSafeForTx && !isInference && (
                  <Tooltip title="Esta tasa no es apta para transacciones (confianza baja)" arrow>
                    <Chip label="NO TX" size="small" color="warning" variant="outlined"
                      sx={{ height: 15, fontSize: '0.5rem' }} />
                  </Tooltip>
                )}
                {scaled && (
                  <Tooltip title={`Las tasas son por ${formatScale(rate.scale_factor)} unidades reales de ${currency}`} arrow>
                    <Chip
                      label={`×${formatScale(rate.scale_factor)}`}
                      size="small"
                      sx={{
                        height: 17, fontSize: '0.6rem', fontWeight: 700,
                        bgcolor: 'warning.main', color: 'warning.contrastText',
                        cursor: 'help',
                      }}
                    />
                  </Tooltip>
                )}
                {rate.market_type !== 'official' && (
                  <Chip
                    label={rate.market_type?.includes('digital') ? 'digital' : 'paralelo'}
                    size="small" variant="outlined"
                    sx={{ height: 15, fontSize: '0.55rem', color: 'text.secondary', borderColor: 'divider' }}
                  />
                )}
                {/* ── Source method badge (Phase 7) ── */}
                <SourceMicroBadge
                  method={rate.source_method}
                  url={rate.source_url}
                  fetchedAt={rate.fetched_at}
                  confidence={rate.confidence}
                />
              </Box>
              <Typography variant="caption" color="text.secondary">{meta?.name ?? rate.name ?? currency}</Typography>
            </Box>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <Tooltip title="Ver comparación entre fuentes" arrow>
              <IconButton size="small" onClick={() => onExpandSource(currency)}>
                {sourceExpanded ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
              </IconButton>
            </Tooltip>
            <IconButton size="small" onClick={(e) => onMenu(e, currency)}>
              <MoreVert fontSize="small" />
            </IconButton>
          </Box>
        </Box>

        {/* INFERENCE warning inline */}
        {isInference && (
          <Box sx={{
            display: 'flex', alignItems: 'center', gap: 0.5,
            bgcolor: 'error.50', border: '1px solid', borderColor: 'error.light',
            borderRadius: 1, px: 1, py: 0.5, mb: 1,
          }}>
            <ErrorIcon sx={{ fontSize: 13, color: 'error.main' }} />
            <Typography variant="caption" color="error.main" fontWeight={600}>
              Tasa estimada — no usar en transacciones
            </Typography>
          </Box>
        )}

        {/* Tasas compra / venta */}
        <Grid container spacing={1} mb={1}>
          <Grid item xs={6}>
            <Typography variant="caption" color="text.secondary" display="block">Compra</Typography>
            <Typography variant="h6" fontWeight={700} color="success.main" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatRate(rate.buy)}
            </Typography>
          </Grid>
          <Grid item xs={6}>
            <Typography variant="caption" color="text.secondary" display="block">Venta</Typography>
            <Typography variant="h6" fontWeight={700} color="error.main" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatRate(rate.sell)}
            </Typography>
          </Grid>
        </Grid>

        {/* Denominación de la tasa */}
        <Typography variant="caption" color="text.secondary" display="block" mb={0.75}
          sx={{ fontStyle: 'italic' }}>
          BOB {scaleLabel}
        </Typography>

        {/* Tendencia */}
        {rate.trend && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <TrendIcon fontSize="small" color={trendColor as any} />
            {rate.changePercent !== undefined && (
              <Chip
                label={`${rate.changePercent >= 0 ? '+' : ''}${rate.changePercent}%`}
                size="small"
                color={rate.changePercent >= 0 ? 'success' : 'error'}
                variant="outlined"
              />
            )}
          </Box>
        )}

        {/* ── Provenance footer (Phase 7) ── */}
        <Box sx={{ mt: 1, pt: 1, borderTop: '1px solid', borderColor: 'divider', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.6rem' }}>
            {rate.fetched_at
              ? new Date(rate.fetched_at).toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' })
              : '—'}
          </Typography>
          {rate.confidence !== undefined && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
              <Box sx={{
                width: 28, height: 3, bgcolor: '#e0e0e0', borderRadius: 1, overflow: 'hidden',
              }}>
                <Box sx={{
                  width: `${Math.round(rate.confidence * 100)}%`, height: '100%', borderRadius: 1,
                  bgcolor: rate.confidence >= 0.9 ? '#4caf50' : rate.confidence >= 0.7 ? '#ff9800' : '#f44336',
                }} />
              </Box>
              <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.6rem' }}>
                {Math.round((rate.confidence ?? 1) * 100)}%
              </Typography>
            </Box>
          )}
        </Box>

        {/* ── Source comparison (expandable) ── */}
        <Collapse in={sourceExpanded} timeout="auto" unmountOnExit>
          {sourceSummary ? (
            <SourceComparisonTable sources={sourceSummary.sources} stats={sourceSummary.stats} />
          ) : (
            <Box sx={{ mt: 1, pt: 1, borderTop: '1px dashed', borderColor: 'divider' }}>
              <LinearProgress sx={{ height: 2 }} />
              <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.6rem' }}>
                Cargando comparación entre fuentes…
              </Typography>
            </Box>
          )}
        </Collapse>
      </Box>
    </motion.div>
  );
};

// ── Componente principal ──────────────────────────────────────────────────────
const ExchangeRatesCard: React.FC<ExchangeRatesCardProps> = ({ rates }) => {
  const [anchorEl,          setAnchorEl]          = useState<null | HTMLElement>(null);
  const [selectedCurrency,  setSelectedCurrency]  = useState<string | null>(null);
  const [primaryData,       setPrimaryData]        = useState<Record<string, any>>({});
  const [expandedSource,    setExpandedSource]     = useState<string | null>(null);
  const [sourceSummaries,   setSourceSummaries]    = useState<Record<string, any>>({});
  const [loadingSummary,    setLoadingSummary]      = useState<string | null>(null);

  const handleMenuOpen = (e: React.MouseEvent<HTMLElement>, code: string) => {
    setAnchorEl(e.currentTarget);
    setSelectedCurrency(code);
  };
  const handleMenuClose = () => { setAnchorEl(null); setSelectedCurrency(null); };

  // Fetch primary rates on mount
  useEffect(() => {
    fetchEnginePrimary().then(setPrimaryData);
  }, []);

  const handleExpandSource = useCallback(async (code: string) => {
    if (expandedSource === code) {
      setExpandedSource(null);
      return;
    }
    setExpandedSource(code);
    if (!sourceSummaries[code]) {
      setLoadingSummary(code);
      const summary = await fetchEngineSummary(code);
      if (summary) {
        setSourceSummaries(prev => ({
          ...prev,
          [code]: {
            sources: summary.sources ?? [],
            stats:   summary.statistics ?? null,
          },
        }));
      }
      setLoadingSummary(null);
    }
  }, [expandedSource, sourceSummaries]);

  const ratesMap: Record<string, RateEntry> = React.useMemo(() => {
    if (!rates) return {};
    if (Array.isArray(rates)) return parseRates(rates) as Record<string, RateEntry>;
    return rates as Record<string, RateEntry>;
  }, [rates]);

  if (!rates || Object.keys(rates).length === 0) {
    return (
      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>Tasas de Cambio</Typography>
          <Grid container spacing={2}>
            {[1, 2, 3, 4].map(n => (
              <Grid item xs={6} key={n}><Skeleton variant="rectangular" height={130} sx={{ borderRadius: 2 }} /></Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>
    );
  }

  const hasScaled      = Object.values(ratesMap).some(r => isScaled(r.scale_factor));
  const inferenceCount = Object.values(ratesMap).filter(r => r.source_method === 'INFERENCE').length;
  const divergenceCount = Object.values(sourceSummaries).filter(
    (s: any) => s?.stats?.has_divergence
  ).length;

  return (
    <>
      <Card>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Box>
              <Typography variant="h6">Tasas de Cambio</Typography>
              {hasScaled && (
                <Typography variant="caption" color="text.secondary">
                  Divisas marcadas ×1.000 se cotizan por lotes de 1.000 unidades
                </Typography>
              )}
            </Box>
            <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center', flexWrap: 'wrap' }}>
              {inferenceCount > 0 && (
                <Chip
                  icon={<ErrorIcon sx={{ fontSize: 14 }} />}
                  label={`${inferenceCount} estimada${inferenceCount > 1 ? 's' : ''}`}
                  size="small" color="error" variant="outlined"
                />
              )}
              {divergenceCount > 0 && (
                <Tooltip title="Hay divergencia significativa entre fuentes de datos" arrow>
                  <Chip
                    icon={<Warning sx={{ fontSize: 14 }} />}
                    label={`${divergenceCount} diverg.`}
                    size="small" color="warning" variant="outlined"
                  />
                </Tooltip>
              )}
              {Object.keys(primaryData).length > 0 && (
                <Tooltip title="Tasas primarias cargadas desde el motor central" arrow>
                  <Chip
                    icon={<Star sx={{ fontSize: 12 }} />}
                    label="Motor activo"
                    size="small" color="primary" variant="outlined"
                    sx={{ height: 22, fontSize: '0.6rem' }}
                  />
                </Tooltip>
              )}
              <Chip
                label="En vivo"
                size="small"
                color={inferenceCount > 0 ? 'warning' : 'success'}
                icon={
                  <Box sx={{
                    width: 7, height: 7, borderRadius: '50%',
                    bgcolor: inferenceCount > 0 ? 'warning.main' : 'success.main',
                    animation: 'pulse 2s infinite',
                    '@keyframes pulse': { '0%': { opacity: 1 }, '50%': { opacity: 0.4 }, '100%': { opacity: 1 } },
                  }} />
                }
              />
            </Box>
          </Box>

          <Grid container spacing={2}>
            <AnimatePresence>
              {Object.entries(ratesMap).map(([code, rate]) => (
                <Grid item xs={12} sm={6} key={code}>
                  <RateDisplay
                    currency={code}
                    rate={rate}
                    onMenu={handleMenuOpen}
                    primaryData={primaryData}
                    onExpandSource={handleExpandSource}
                    sourceExpanded={expandedSource === code}
                    sourceSummary={
                      expandedSource === code && loadingSummary !== code
                        ? (sourceSummaries[code] ?? null)
                        : expandedSource === code && loadingSummary === code
                        ? undefined  // still loading
                        : null
                    }
                  />
                </Grid>
              ))}
            </AnimatePresence>
          </Grid>

          <Divider sx={{ my: 2 }} />
          {/* ── Footer: legend + last update ── */}
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
            <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center', flexWrap: 'wrap' }}>
              {(['API', 'SCRAP', 'MANUAL', 'INFERENCE'] as const).map(m => (
                <SourceMicroBadge key={m} method={m} />
              ))}
            </Box>
            <Typography variant="caption" color="text.secondary">
              {new Date().toLocaleTimeString('es-BO')}
            </Typography>
          </Box>
        </CardContent>
      </Card>

      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={handleMenuClose}>
        <MenuItem onClick={handleMenuClose}>
          <History sx={{ mr: 1 }} fontSize="small" />
          Ver historial
        </MenuItem>
        <MenuItem onClick={handleMenuClose}>Configurar alertas</MenuItem>
      </Menu>
    </>
  );
};

export default ExchangeRatesCard;
