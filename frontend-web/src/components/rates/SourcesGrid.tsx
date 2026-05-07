// src/components/rates/SourcesGrid.tsx
// Grid multi-fuente: muestra todas las tasas activas por plataforma para una divisa.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Box, Chip, CircularProgress, IconButton, Paper, Tab, Table,
  TableBody, TableCell, TableContainer, TableHead, TableRow, Tabs,
  Tooltip, Typography, alpha, useTheme,
} from '@mui/material';
import { Refresh, OpenInNew, CheckCircle, Warning, Error as ErrorIcon } from '@mui/icons-material';
import { ratesApi, SourceLiveRate } from '../../services/ratesApi';

// ── Constants ────────────────────────────────────────────────────────────────

const CURRENCIES = ['USD', 'EUR', 'BRL', 'PEN', 'CLP', 'ARS'];

const CURRENCY_FLAGS: Record<string, string> = {
  USD: '🇺🇸', EUR: '🇪🇺', BRL: '🇧🇷', PEN: '🇵🇪', CLP: '🇨🇱', ARS: '🇦🇷',
};

const SOURCE_COLORS: Record<string, string> = {
  BINANCE_P2P:        '#F0B90B',
  BITGET_P2P:         '#00F0FF',
  BYBIT_P2P:          '#F7A600',
  OKX_P2P:            '#AAAAAA',
  BINANCE_ARS:        '#F0B90B',
  BINANCE_CLP:        '#F0B90B',
  BINANCE_PEN:        '#F0B90B',
  BINANCE_BRL:        '#F0B90B',
  BINANCE_EUR:        '#F0B90B',
  DOLARBLUE_BO:       '#1E4DB7',
  DOLARBLUE_ELDORADO: '#7C3AED',
  DOLARBLUE_WALLBIT:  '#059669',
  DOLARBLUE_AIRTM:    '#DC2626',
  DOLARBLUE_BINANCE:  '#F0B90B',
  DOLARBLUE_BYBIT:    '#F7A600',
  DOLARBLUE_SALDOAR:  '#2563EB',
  DOLARBLUE_BITGET:   '#00F0FF',
  AIRTM_QUOTE:        '#DC2626',
  ELDORADO:           '#7C3AED',
  WALLBIT:            '#059669',
  SALDOAR:            '#2563EB',
};

const METHOD_COLOR: Record<string, 'success' | 'warning' | 'error' | 'default'> = {
  API:       'success',
  SCRAP:     'warning',
  MANUAL:    'default',
  INFERENCE: 'error',
};

// ── Sub-components ────────────────────────────────────────────────────────────

interface FreshnessChipProps { isStale: boolean; fetchedAt: string | null }

const FreshnessChip: React.FC<FreshnessChipProps> = ({ isStale, fetchedAt }) => {
  const ago = fetchedAt
    ? Math.round((Date.now() - new Date(fetchedAt).getTime()) / 60000)
    : null;
  const label = ago !== null ? `${ago}m` : '—';

  if (isStale) return (
    <Chip
      icon={<Warning sx={{ fontSize: 12 }} />}
      label={label}
      size="small"
      color="warning"
      sx={{ fontSize: '0.65rem', height: 18, px: 0.5 }}
    />
  );
  return (
    <Chip
      icon={<CheckCircle sx={{ fontSize: 12 }} />}
      label={label}
      size="small"
      color="success"
      sx={{ fontSize: '0.65rem', height: 18, px: 0.5 }}
    />
  );
};

// ── Main component ────────────────────────────────────────────────────────────

const SourcesGrid: React.FC = () => {
  const theme = useTheme();
  const [tab, setTab] = useState(0);
  const [dataMap, setDataMap] = useState<Record<string, SourceLiveRate[]>>({});
  const [loadingSet, setLoadingSet] = useState<Set<string>>(new Set());
  const [errorMap, setErrorMap] = useState<Record<string, string>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const currency = CURRENCIES[tab];

  const load = useCallback(async (cur: string) => {
    setLoadingSet(prev => new Set([...prev, cur]));
    setErrorMap(prev => { const n = { ...prev }; delete n[cur]; return n; });
    try {
      const resp = await ratesApi.getSourcesLive(cur, 60);
      setDataMap(prev => ({ ...prev, [cur]: resp.sources }));
    } catch {
      setErrorMap(prev => ({ ...prev, [cur]: 'Error al cargar fuentes' }));
    } finally {
      setLoadingSet(prev => { const n = new Set(prev); n.delete(cur); return n; });
    }
  }, []);

  // Load on tab change + auto-refresh every 90 seconds
  useEffect(() => {
    if (!dataMap[currency]) {
      load(currency);
    }
    clearTimeout(timers.current[currency]);
    timers.current[currency] = setTimeout(() => load(currency), 90_000);
    return () => clearTimeout(timers.current[currency]);
  }, [currency, load]); // eslint-disable-line react-hooks/exhaustive-deps

  const sources   = dataMap[currency] ?? [];
  const isLoading = loadingSet.has(currency);
  const error     = errorMap[currency];

  return (
    <Box>
      {/* Header */}
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={1.5}>
        <Typography variant="subtitle1" fontWeight={700} color="text.secondary">
          Tasas por plataforma en tiempo real
        </Typography>
        <Tooltip title="Actualizar ahora">
          <span>
            <IconButton size="small" onClick={() => load(currency)} disabled={isLoading}>
              <Refresh fontSize="small" sx={{ animation: isLoading ? 'spin 1s linear infinite' : 'none' }} />
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {/* Currency tabs */}
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ mb: 1.5, minHeight: 36, '& .MuiTab-root': { minHeight: 36, py: 0.5, px: 1.5 } }}
      >
        {CURRENCIES.map(cur => (
          <Tab
            key={cur}
            label={
              <Box display="flex" alignItems="center" gap={0.5}>
                <span>{CURRENCY_FLAGS[cur]}</span>
                <span style={{ fontWeight: 700, fontSize: '0.78rem' }}>{cur}</span>
                {dataMap[cur] && (
                  <Chip
                    label={dataMap[cur].length}
                    size="small"
                    sx={{ height: 16, fontSize: '0.6rem', ml: 0.3,
                          bgcolor: alpha(theme.palette.primary.main, 0.12) }}
                  />
                )}
              </Box>
            }
          />
        ))}
      </Tabs>

      {/* Content */}
      {isLoading && !sources.length ? (
        <Box display="flex" justifyContent="center" py={4}>
          <CircularProgress size={28} />
        </Box>
      ) : error ? (
        <Box display="flex" alignItems="center" gap={1} py={3} justifyContent="center">
          <ErrorIcon color="error" />
          <Typography color="error.main" variant="body2">{error}</Typography>
        </Box>
      ) : sources.length === 0 ? (
        <Box py={3} textAlign="center">
          <Typography variant="body2" color="text.secondary">
            Sin datos de fuentes para {currency}/BOB
          </Typography>
        </Box>
      ) : (
        <TableContainer
          component={Paper}
          variant="outlined"
          sx={{ borderRadius: 2, maxHeight: 480, overflow: 'auto' }}
        >
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 700, width: 36 }}>#</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Plataforma</TableCell>
                <TableCell sx={{ fontWeight: 700 }} align="right">Compra</TableCell>
                <TableCell sx={{ fontWeight: 700 }} align="right">Venta</TableCell>
                <TableCell sx={{ fontWeight: 700 }} align="right">Spread</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Fuente</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Confianza</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Antigüedad</TableCell>
                <TableCell sx={{ fontWeight: 700, width: 36 }}></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sources.map((src, idx) => {
                const buy    = parseFloat(src.buy_rate);
                const sell   = parseFloat(src.sell_rate);
                const spread = sell > 0 && buy > 0 ? ((sell - buy) / buy * 100).toFixed(2) : '—';
                const color  = SOURCE_COLORS[src.source] ?? theme.palette.primary.main;

                return (
                  <TableRow
                    key={`${src.source}-${idx}`}
                    hover
                    sx={{
                      opacity: src.is_stale ? 0.6 : 1,
                      '&:hover': { opacity: 1 },
                      bgcolor: src.is_primary
                        ? alpha(theme.palette.success.main, 0.05)
                        : undefined,
                    }}
                  >
                    <TableCell>
                      <Typography variant="caption" color="text.disabled">{idx + 1}</Typography>
                    </TableCell>

                    <TableCell>
                      <Box display="flex" alignItems="center" gap={0.75}>
                        <Box
                          sx={{
                            width: 8, height: 8, borderRadius: '50%',
                            bgcolor: color, flexShrink: 0,
                          }}
                        />
                        <Box>
                          <Typography variant="body2" fontWeight={600} lineHeight={1.2}>
                            {src.source_label}
                          </Typography>
                          <Typography variant="caption" color="text.disabled" fontSize="0.6rem">
                            {src.market_type.replace(/_/g, ' ')}
                          </Typography>
                        </Box>
                        {src.is_primary && (
                          <Chip label="★" size="small" color="success"
                            sx={{ height: 16, fontSize: '0.55rem', ml: 0.5 }} />
                        )}
                      </Box>
                    </TableCell>

                    <TableCell align="right">
                      <Typography variant="body2" fontWeight={700} color="success.main">
                        {buy.toFixed(4)}
                      </Typography>
                    </TableCell>

                    <TableCell align="right">
                      <Typography variant="body2" fontWeight={700} color="error.main">
                        {sell.toFixed(4)}
                      </Typography>
                    </TableCell>

                    <TableCell align="right">
                      <Typography variant="caption" color="text.secondary">
                        {typeof spread === 'string' ? spread : `${spread}%`}
                      </Typography>
                    </TableCell>

                    <TableCell>
                      <Chip
                        label={src.source_method}
                        size="small"
                        color={METHOD_COLOR[src.source_method] ?? 'default'}
                        sx={{ fontSize: '0.6rem', height: 18 }}
                      />
                    </TableCell>

                    <TableCell>
                      <Box display="flex" alignItems="center" gap={0.5}>
                        <Box
                          sx={{
                            height: 4, width: 50, borderRadius: 2,
                            bgcolor: alpha(theme.palette.divider, 1),
                            overflow: 'hidden',
                          }}
                        >
                          <Box
                            sx={{
                              height: '100%',
                              width: `${Math.round(src.confidence * 100)}%`,
                              bgcolor: src.confidence >= 0.9 ? 'success.main'
                                : src.confidence >= 0.7 ? 'warning.main'
                                : 'error.main',
                              borderRadius: 2,
                            }}
                          />
                        </Box>
                        <Typography variant="caption" color="text.secondary">
                          {Math.round(src.confidence * 100)}%
                        </Typography>
                      </Box>
                    </TableCell>

                    <TableCell>
                      <FreshnessChip isStale={src.is_stale} fetchedAt={src.fetched_at} />
                    </TableCell>

                    <TableCell>
                      {src.source_url && (
                        <Tooltip title={src.source_url}>
                          <IconButton
                            size="small"
                            component="a"
                            href={src.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            <OpenInNew sx={{ fontSize: 14 }} />
                          </IconButton>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </Box>
  );
};

export default SourcesGrid;
