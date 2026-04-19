/**
 * Panel de detección de arbitraje entre fuentes de tasas de cambio.
 *
 * Detecta y muestra:
 *   - cross_source   → comprar en fuente A más barato que vender en B
 *   - spread_margin  → divisas con margen compra/venta excepcional
 *   - bcb_premium    → cuánto cotiza el mercado sobre la tasa BCB oficial
 *   - triangular     → rutas indirectas A→C→BOB más rentables que A→BOB
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, Grid, Card, CardContent, CardHeader,
  Chip, Button, Tooltip, Divider, LinearProgress, Alert,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  IconButton, Collapse,
} from '@mui/material';
import {
  Refresh, TrendingUp, SwapHoriz, AccountBalance, Timeline,
  ExpandMore, ExpandLess, InfoOutlined, Warning, CheckCircle,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { formatRate, isScaled, formatScale } from '../../utils/finance';

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface Opportunity {
  type:            'cross_source' | 'spread_margin' | 'bcb_premium' | 'triangular';
  currency:        string;
  currency_via:    string;
  buy_at:          number;
  sell_at:         number;
  profit_per_unit: number;
  profit_pct:      number;
  scale_factor:    number;
  buy_source:      string;
  sell_source:     string;
  market_buy:      string;
  market_sell:     string;
  risk:            'LOW' | 'MEDIUM' | 'HIGH';
  confidence:      number;
  description:     string;
  detected_at:     string;
}

interface CurrencyRank {
  currency:       string;
  buy:            number;
  sell:           number;
  spread_pct:     number;
  profit_per_lot: number;
  scale_factor:   number;
  market_type:    string;
  source:         string;
}

interface ArbitrageAlert {
  level:   'HIGH' | 'MEDIUM' | 'LOW';
  message: string;
  count:   number;
}

interface ArbitrageData {
  detected_at:          string;
  total_opportunities:  number;
  opportunities:        Opportunity[];
  best_opportunity:     Opportunity | null;
  currency_ranking:     CurrencyRank[];
  market_spread_map:    Record<string, { avg_spread_pct: number; count: number }>;
  alerts:               ArbitrageAlert[];
}

// ─── Colores y etiquetas por tipo ─────────────────────────────────────────────

const OPP_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  cross_source:  { label: 'Multi-fuente',  color: '#1976d2', icon: <SwapHoriz fontSize="small" /> },
  spread_margin: { label: 'Spread alto',   color: '#2e7d32', icon: <TrendingUp fontSize="small" /> },
  bcb_premium:   { label: 'Prima BCB',     color: '#e65100', icon: <AccountBalance fontSize="small" /> },
  triangular:    { label: 'Triangular',    color: '#6a1b9a', icon: <Timeline fontSize="small" /> },
};

const RISK_COLOR: Record<string, 'success' | 'warning' | 'error'> = {
  LOW: 'success', MEDIUM: 'warning', HIGH: 'error',
};

const MARKET_LABEL: Record<string, string> = {
  official: 'BCB Oficial', bcb: 'BCB Ref.', digital: 'Digital', parallel: 'Paralelo',
};

// ─── Subcomponentes ───────────────────────────────────────────────────────────

function ProfitBar({ pct }: { pct: number }) {
  const capped = Math.min(pct, 50);   // cap visual en 50 % para que no aplaste la barra
  const color  = pct >= 10 ? 'error' : pct >= 5 ? 'warning' : 'success';
  return (
    <Box display="flex" alignItems="center" gap={1}>
      <LinearProgress
        variant="determinate"
        value={(capped / 50) * 100}
        color={color}
        sx={{ flex: 1, height: 6, borderRadius: 3 }}
      />
      <Typography variant="caption" fontWeight="bold" color={`${color}.main`}
        sx={{ minWidth: 42, fontVariantNumeric: 'tabular-nums' }}>
        {pct.toFixed(1)}%
      </Typography>
    </Box>
  );
}

function ConfidenceBar({ conf }: { conf: number }) {
  const pct   = Math.round(conf * 100);
  const color = conf >= 0.8 ? 'success' : conf >= 0.6 ? 'warning' : 'error';
  return (
    <Tooltip title={`Confianza: ${pct}% — basada en calidad de las fuentes`} arrow>
      <Box display="flex" alignItems="center" gap={0.5} sx={{ cursor: 'help' }}>
        <LinearProgress
          variant="determinate" value={pct} color={color}
          sx={{ width: 48, height: 4, borderRadius: 2 }}
        />
        <Typography variant="caption" color="text.secondary">{pct}%</Typography>
      </Box>
    </Tooltip>
  );
}

function OpportunityCard({ opp, index }: { opp: Opportunity; index: number }) {
  const [expanded, setExpanded] = useState(index === 0);
  const meta    = OPP_META[opp.type] || OPP_META.cross_source;
  const scaled  = isScaled(opp.scale_factor);
  const scaleLabel = scaled ? ` / ${formatScale(opp.scale_factor)} ${opp.currency}` : `/${opp.currency}`;

  return (
    <Card variant="outlined"
      sx={{ borderLeft: 4, borderColor: meta.color, mb: 1.5, transition: 'box-shadow 0.2s',
            '&:hover': { boxShadow: 3 } }}>
      <CardHeader
        disableTypography
        sx={{ py: 1.5, cursor: 'pointer' }}
        onClick={() => setExpanded(e => !e)}
        title={
          <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
            <Box sx={{ color: meta.color }}>{meta.icon}</Box>
            <Typography fontWeight="bold" variant="body1">
              {opp.currency}
              {opp.currency_via && ` → ${opp.currency_via}`}
              {' '}→ BOB
            </Typography>
            <Chip label={meta.label} size="small"
              sx={{ bgcolor: meta.color, color: '#fff', fontSize: '0.65rem', height: 18 }} />
            <Chip label={`Riesgo ${opp.risk}`} size="small"
              color={RISK_COLOR[opp.risk]} variant="outlined"
              sx={{ fontSize: '0.65rem', height: 18 }} />
          </Box>
        }
        action={
          <Box display="flex" alignItems="center" gap={1} pr={1}>
            <Box textAlign="right">
              <Typography variant="h6" fontWeight="bold"
                color={opp.profit_pct >= 10 ? 'error.main' : opp.profit_pct >= 5 ? 'warning.main' : 'success.main'}>
                +{opp.profit_pct.toFixed(1)}%
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                +{opp.profit_per_unit.toFixed(4)} BOB{scaleLabel}
              </Typography>
            </Box>
            <IconButton size="small">
              {expanded ? <ExpandLess /> : <ExpandMore />}
            </IconButton>
          </Box>
        }
      />

      <Collapse in={expanded}>
        <Divider />
        <CardContent sx={{ pt: 1.5 }}>
          <Grid container spacing={2}>
            {/* Precios */}
            <Grid item xs={12} sm={6}>
              <Box display="flex" gap={2}>
                <Box>
                  <Typography variant="caption" color="text.secondary">Compra en</Typography>
                  <Typography fontWeight="medium" color="success.main"
                    sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    {formatRate(opp.buy_at)} BOB
                  </Typography>
                  <Chip label={MARKET_LABEL[opp.market_buy] ?? opp.market_buy}
                    size="small" variant="outlined"
                    sx={{ fontSize: '0.6rem', height: 16, mt: 0.25 }} />
                </Box>
                <Box sx={{ color: 'text.disabled', alignSelf: 'center' }}>→</Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Venta en</Typography>
                  <Typography fontWeight="medium" color="error.main"
                    sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    {formatRate(opp.sell_at)} BOB
                  </Typography>
                  <Chip label={MARKET_LABEL[opp.market_sell] ?? opp.market_sell}
                    size="small" variant="outlined"
                    sx={{ fontSize: '0.6rem', height: 16, mt: 0.25 }} />
                </Box>
              </Box>
            </Grid>

            {/* Ganancia + confianza */}
            <Grid item xs={12} sm={6}>
              <Typography variant="caption" color="text.secondary" display="block" mb={0.25}>
                Ganancia estimada
              </Typography>
              <ProfitBar pct={opp.profit_pct} />
              <Box mt={0.75}>
                <Typography variant="caption" color="text.secondary">Confianza de fuentes</Typography>
                <Box mt={0.25}><ConfidenceBar conf={opp.confidence} /></Box>
              </Box>
            </Grid>

            {/* Descripción */}
            <Grid item xs={12}>
              <Alert severity={opp.risk === 'HIGH' ? 'warning' : 'info'}
                icon={<InfoOutlined fontSize="small" />}
                sx={{ py: 0.5, fontSize: '0.8rem' }}>
                {opp.description}
              </Alert>
            </Grid>
          </Grid>
        </CardContent>
      </Collapse>
    </Card>
  );
}

// ─── Componente principal ─────────────────────────────────────────────────────

const ArbitrageAlerts: React.FC = () => {
  const [data,      setData]      = useState<ArbitrageData | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [activeTab, setActiveTab] = useState<string>('all');
  const { enqueueSnackbar }       = useSnackbar();

  const load = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    try {
      const params = forceRefresh ? { refresh: 'true' } : {};
      const res    = await api.get('/rates/arbitrage/', { params });
      setData(res.data);
    } catch {
      enqueueSnackbar('Error al cargar análisis de arbitraje', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const OPP_TYPES = ['all', 'cross_source', 'spread_margin', 'bcb_premium', 'triangular'];

  const filtered = data
    ? activeTab === 'all'
      ? data.opportunities
      : data.opportunities.filter(o => o.type === activeTab)
    : [];

  const bestSpread = data?.currency_ranking?.[0];

  return (
    <Box>
      {/* ── Header ── */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Box>
          <Typography variant="h5" fontWeight="bold">Análisis de Arbitraje</Typography>
          {data && (
            <Typography variant="caption" color="text.secondary">
              Actualizado: {new Date(data.detected_at).toLocaleTimeString('es-BO')}
            </Typography>
          )}
        </Box>
        <Button startIcon={<Refresh />} variant="outlined" size="small"
          onClick={() => load(true)} disabled={loading}>
          Recalcular
        </Button>
      </Box>

      {loading && <LinearProgress sx={{ mb: 2, borderRadius: 1 }} />}

      {/* ── Alertas de cabecera ── */}
      {data?.alerts && data.alerts.length > 0 && (
        <Box mb={2} display="flex" flexDirection="column" gap={1}>
          {data.alerts.map((a, i) => (
            <Alert key={i}
              severity={a.level === 'HIGH' ? 'error' : a.level === 'MEDIUM' ? 'warning' : 'info'}
              icon={a.level === 'HIGH' ? <Warning /> : <CheckCircle />}
              sx={{ py: 0.5 }}>
              {a.message}
            </Alert>
          ))}
        </Box>
      )}

      {/* ── KPIs ── */}
      <Grid container spacing={2} mb={3}>
        <Grid item xs={6} sm={3}>
          <Card sx={{ borderLeft: 4, borderColor: 'primary.main', height: '100%' }}>
            <CardContent sx={{ py: 1.5 }}>
              <Typography variant="caption" color="text.secondary">Oportunidades</Typography>
              <Typography variant="h4" color="primary.main">
                {data?.total_opportunities ?? '—'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={6} sm={3}>
          <Card sx={{ borderLeft: 4, borderColor: 'success.main', height: '100%' }}>
            <CardContent sx={{ py: 1.5 }}>
              <Typography variant="caption" color="text.secondary">Mejor ganancia</Typography>
              <Typography variant="h4" color="success.main">
                {data?.best_opportunity
                  ? `+${data.best_opportunity.profit_pct.toFixed(1)}%`
                  : '—'
                }
              </Typography>
              {data?.best_opportunity && (
                <Typography variant="caption" color="text.secondary">
                  {data.best_opportunity.currency}
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={6} sm={3}>
          <Card sx={{ borderLeft: 4, borderColor: 'warning.main', height: '100%' }}>
            <CardContent sx={{ py: 1.5 }}>
              <Typography variant="caption" color="text.secondary">Divisa más rentable</Typography>
              <Typography variant="h4" color="warning.main">
                {bestSpread?.currency ?? '—'}
              </Typography>
              {bestSpread && (
                <Typography variant="caption" color="text.secondary">
                  Spread: {bestSpread.spread_pct.toFixed(1)}%
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={6} sm={3}>
          <Card sx={{ borderLeft: 4, borderColor: 'info.main', height: '100%' }}>
            <CardContent sx={{ py: 1.5 }}>
              <Typography variant="caption" color="text.secondary">Spread medio paralelo</Typography>
              <Typography variant="h4" color="info.main">
                {data?.market_spread_map?.parallel
                  ? `${data.market_spread_map.parallel.avg_spread_pct.toFixed(1)}%`
                  : '—'
                }
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        {/* ── Oportunidades detalladas ── */}
        <Grid item xs={12} md={8}>
          <Paper variant="outlined" sx={{ p: 2 }}>
            {/* Filtro por tipo */}
            <Box display="flex" gap={0.75} flexWrap="wrap" mb={2}>
              {OPP_TYPES.map(t => {
                const meta = OPP_META[t];
                const count = t === 'all'
                  ? data?.opportunities.length ?? 0
                  : data?.opportunities.filter(o => o.type === t).length ?? 0;
                return (
                  <Chip
                    key={t}
                    label={`${meta?.label ?? 'Todas'} (${count})`}
                    onClick={() => setActiveTab(t)}
                    variant={activeTab === t ? 'filled' : 'outlined'}
                    color={activeTab === t ? 'primary' : 'default'}
                    size="small"
                    icon={meta?.icon as React.ReactElement | undefined}
                  />
                );
              })}
            </Box>

            {filtered.length === 0 && !loading ? (
              <Box textAlign="center" py={4}>
                <CheckCircle sx={{ fontSize: 48, color: 'success.light', mb: 1 }} />
                <Typography color="text.secondary">
                  Sin oportunidades en esta categoría con datos actuales.
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Las tasas están alineadas entre fuentes o no hay datos suficientes.
                </Typography>
              </Box>
            ) : (
              filtered.map((opp, i) => (
                <OpportunityCard key={`${opp.type}-${opp.currency}-${opp.currency_via}`}
                  opp={opp} index={i} />
              ))
            )}
          </Paper>
        </Grid>

        {/* ── Ranking de divisas ── */}
        <Grid item xs={12} md={4}>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle1" fontWeight="bold" mb={1.5}>
              Ranking por Rentabilidad
            </Typography>
            <Tooltip title="Ordenado por spread compra/venta — mayor spread = mayor ganancia potencial por operación" arrow>
              <Typography variant="caption" color="text.secondary" display="block" mb={1.5}
                sx={{ cursor: 'help' }}>
                Spread compra/venta actual
              </Typography>
            </Tooltip>

            <TableContainer>
              <Table size="small" sx={{ '& td, & th': { px: 0.75, py: 0.5 } }}>
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 'bold' }}>#</TableCell>
                    <TableCell sx={{ fontWeight: 'bold' }}>Divisa</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 'bold' }}>Compra</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 'bold' }}>Venta</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 'bold' }}>Spread</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(data?.currency_ranking ?? []).map((r, i) => {
                    const scaled  = isScaled(r.scale_factor);
                    const isTop3  = i < 3;
                    return (
                      <TableRow key={r.currency} hover
                        sx={{ bgcolor: isTop3 ? 'action.hover' : 'inherit' }}>
                        <TableCell>
                          <Typography variant="caption" fontWeight={isTop3 ? 'bold' : 'normal'}
                            color={i === 0 ? 'warning.main' : 'text.primary'}>
                            {i + 1}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Box display="flex" alignItems="center" gap={0.5}>
                            <Typography variant="body2" fontWeight="medium">{r.currency}</Typography>
                            {scaled && (
                              <Chip label={`×${formatScale(r.scale_factor)}`} size="small"
                                sx={{ fontSize: '0.5rem', height: 14,
                                      bgcolor: 'warning.light', color: 'warning.dark' }} />
                            )}
                          </Box>
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="caption" color="success.main"
                            sx={{ fontVariantNumeric: 'tabular-nums' }}>
                            {formatRate(r.buy)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="caption" color="error.main"
                            sx={{ fontVariantNumeric: 'tabular-nums' }}>
                            {formatRate(r.sell)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Chip
                            label={`${r.spread_pct.toFixed(1)}%`}
                            size="small"
                            color={r.spread_pct >= 5 ? 'warning' : r.spread_pct >= 2 ? 'success' : 'default'}
                            sx={{ fontSize: '0.6rem', height: 18, fontWeight: 'bold' }}
                          />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>

            {/* Spread por mercado */}
            {data?.market_spread_map && (
              <Box mt={2.5}>
                <Divider sx={{ mb: 1.5 }} />
                <Typography variant="subtitle2" fontWeight="bold" mb={1}>
                  Spread por Mercado
                </Typography>
                {Object.entries(data.market_spread_map).map(([market, info]) => (
                  <Box key={market} display="flex" justifyContent="space-between"
                    alignItems="center" mb={0.75}>
                    <Box>
                      <Typography variant="caption" fontWeight="medium">
                        {MARKET_LABEL[market] ?? market}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {info.count} divisa{info.count !== 1 ? 's' : ''}
                      </Typography>
                    </Box>
                    <Chip
                      label={`${info.avg_spread_pct.toFixed(1)}%`}
                      size="small"
                      color={info.avg_spread_pct >= 5 ? 'warning' : 'default'}
                      sx={{ fontSize: '0.65rem' }}
                    />
                  </Box>
                ))}
              </Box>
            )}
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
};

export default ArbitrageAlerts;
