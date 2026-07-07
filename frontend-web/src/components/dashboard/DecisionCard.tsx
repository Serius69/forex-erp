/**
 * DecisionCard — Per-currency intelligent trading decision panel.
 *
 * Shows:
 *   • Semáforo signal (COMPRAR / VENDER / ESPERAR)
 *   • Confidence %, risk badge, suggested buy/sell prices
 *   • Sparkline: last 7 suggested_sell values
 *   • Rate comparison: Binance · Empresa · Competencia
 *   • Backend reasoning text
 *   • "USAR RECOMENDACIÓN" button → preloads TransactionForm
 *
 * Auto-refresh via useDecisions (30 s, no duplicate requests).
 */
import React from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Skeleton,
  Button, Alert, Tooltip, LinearProgress, Divider,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import { FlashOn, Psychology, TrendingUp, TrendingDown, Remove } from '@mui/icons-material';
import {
  AreaChart, Area, ResponsiveContainer, Tooltip as RTooltip,
} from 'recharts';
import { useDecisions } from '../../hooks/useDecisions';
import type { DecisionSignal, RiskLevel, PricingDecision } from '../../hooks/useDecisions';
import { TOKENS } from '../../styles/theme';

// ── Signal config ─────────────────────────────────────────────────────────────

const SIGNAL_CFG: Record<DecisionSignal, {
  label: string; color: string; bg: string; icon: React.ReactNode; dot: string;
}> = {
  COMPRAR: {
    label: 'COMPRAR',
    color: TOKENS.green,
    bg:    TOKENS.greenBg,
    icon:  <TrendingUp sx={{ fontSize: 18 }} />,
    dot:   '🟢',
  },
  VENDER: {
    label: 'VENDER',
    color: TOKENS.red,
    bg:    TOKENS.redBg,
    icon:  <TrendingDown sx={{ fontSize: 18 }} />,
    dot:   '🔴',
  },
  ESPERAR: {
    label: 'ESPERAR',
    color: TOKENS.amber,
    bg:    TOKENS.amberBg,
    icon:  <Remove sx={{ fontSize: 18 }} />,
    dot:   '🟡',
  },
};

const RISK_CFG: Record<RiskLevel, { label: string; color: 'error' | 'warning' | 'success' }> = {
  ALTO:  { label: 'Riesgo ALTO',  color: 'error'   },
  MEDIO: { label: 'Riesgo MEDIO', color: 'warning' },
  BAJO:  { label: 'Riesgo BAJO',  color: 'success' },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const FLAGS: Record<string, string> = {
  USD:'🇺🇸', EUR:'🇪🇺', CLP:'🇨🇱', PEN:'🇵🇪', BRL:'🇧🇷', ARS:'🇦🇷',
};

const f4 = (n: number | null | undefined) =>
  n != null ? `Bs ${n.toFixed(4)}` : '—';

// ── Rate comparison bar ───────────────────────────────────────────────────────

const RateBar = ({ label, value, reference }: {
  label: string; value: number | null | undefined; reference: number;
}) => {
  if (!value) return null;
  const diff    = ((value - reference) / reference) * 100;
  const isAbove = diff > 0;
  return (
    <Box display="flex" alignItems="center" gap={0.75}>
      <Typography variant="caption" color="text.secondary" sx={{ width: 80, flexShrink: 0 }}>
        {label}
      </Typography>
      <Typography variant="caption" fontWeight={700}
        sx={{ fontVariantNumeric: 'tabular-nums', color: isAbove ? TOKENS.green : TOKENS.red }}>
        {value.toFixed(4)}
      </Typography>
      <Typography variant="caption"
        sx={{ color: isAbove ? TOKENS.green : TOKENS.red, fontSize: '0.65rem' }}>
        ({isAbove ? '+' : ''}{diff.toFixed(2)}%)
      </Typography>
    </Box>
  );
};

// ── Props ─────────────────────────────────────────────────────────────────────

export interface TransactionPreset {
  currency: string;
  txType:   'BUY' | 'SELL';
  rate:     number;
}

interface DecisionCardProps {
  currency: string;
  onUseRecommendation: (preset: TransactionPreset) => void;
  /** Compact variant for mobile / tight grids */
  compact?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

const DecisionCard: React.FC<DecisionCardProps> = ({
  currency, onUseRecommendation, compact = false,
}) => {
  const { latest, analysis, loading, error } = useDecisions(currency);

  // ── Loading ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <Card sx={{ height: compact ? 200 : 320 }}>
        <CardContent>
          <Box display="flex" justifyContent="space-between" mb={1.5}>
            <Skeleton width={60} height={28} />
            <Skeleton width={80} height={24} sx={{ borderRadius: 3 }} />
          </Box>
          <Skeleton variant="rectangular" height={compact ? 60 : 80} sx={{ borderRadius: 1, mb: 1.5 }} />
          {!compact && <Skeleton height={20} width="80%" />}
          {!compact && <Skeleton height={20} width="60%" />}
          <Skeleton height={compact ? 40 : 60} sx={{ mt: 1.5, borderRadius: 1 }} />
        </CardContent>
      </Card>
    );
  }

  // ── Error / empty ────────────────────────────────────────────────────────────
  if (error || !latest || !analysis) {
    return (
      <Card>
        <CardContent>
          <Box display="flex" alignItems="center" gap={1} mb={1}>
            <Typography sx={{ fontSize: 18 }}>{FLAGS[currency] ?? '🌐'}</Typography>
            <Typography variant="subtitle2" fontWeight={700}>{currency}</Typography>
          </Box>
          <Alert severity={error ? 'error' : 'info'} sx={{ fontSize: '0.75rem' }}>
            {error ?? `Sin datos AI para ${currency}`}
          </Alert>
        </CardContent>
      </Card>
    );
  }

  const { signal, confidence, risk, sparkline } = analysis;
  const cfg  = SIGNAL_CFG[signal];
  const rCfg = RISK_CFG[risk];

  // Decide preset for the button
  const preset: TransactionPreset = {
    currency,
    txType: signal === 'COMPRAR' ? 'BUY' : 'SELL',
    rate:   signal === 'COMPRAR' ? latest.suggested_buy : latest.suggested_sell,
  };

  return (
    <Card
      variant="outlined"
      sx={{
        borderTop: `3px solid ${cfg.color}`,
        transition: 'box-shadow 0.2s',
        '&:hover': { boxShadow: `0 4px 20px ${alpha(cfg.color, 0.15)}` },
      }}
    >
      <CardContent sx={{ p: compact ? 1.5 : 2, '&:last-child': { pb: compact ? 1.5 : 2 } }}>

        {/* ── Top row: currency + semáforo + risk ── */}
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={1.5}>
          <Box display="flex" alignItems="center" gap={0.75}>
            <Typography sx={{ fontSize: compact ? 16 : 20, lineHeight: 1 }}>
              {FLAGS[currency] ?? '🌐'}
            </Typography>
            <Typography variant={compact ? 'body2' : 'subtitle1'} fontWeight={800}>
              {currency}
            </Typography>
          </Box>
          <Box display="flex" gap={0.75} alignItems="center">
            <Chip
              size="small"
              color={rCfg.color}
              label={rCfg.label}
              variant="outlined"
              sx={{ height: 18, fontSize: '0.6rem', fontWeight: 700 }}
            />
            <Tooltip title="Actualización automática cada 30 segundos">
              <Chip
                size="small"
                label="LIVE"
                color="success"
                sx={{ height: 18, fontSize: '0.6rem', fontWeight: 800 }}
              />
            </Tooltip>
          </Box>
        </Box>

        {/* ── Signal block ── */}
        <Box
          sx={{
            bgcolor: alpha(cfg.color, 0.08),
            border: `1px solid ${alpha(cfg.color, 0.25)}`,
            borderRadius: 2,
            p: compact ? 1 : 1.5,
            mb: 1.5,
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
          }}
        >
          {/* Semáforo dot */}
          <Typography sx={{ fontSize: compact ? 22 : 28, lineHeight: 1 }}>
            {cfg.dot}
          </Typography>

          <Box flex={1}>
            <Box display="flex" alignItems="center" gap={0.75} mb={0.25}>
              <Box sx={{ color: cfg.color }}>{cfg.icon}</Box>
              <Typography
                variant={compact ? 'subtitle1' : 'h6'}
                fontWeight={900}
                sx={{ color: cfg.color, letterSpacing: 1 }}
              >
                {cfg.label}
              </Typography>
            </Box>
            {/* Confidence bar */}
            <Box display="flex" alignItems="center" gap={1}>
              <LinearProgress
                variant="determinate"
                value={confidence}
                sx={{
                  flex: 1, height: 5, borderRadius: 3,
                  bgcolor: alpha(cfg.color, 0.12),
                  '& .MuiLinearProgress-bar': { bgcolor: cfg.color, borderRadius: 3 },
                }}
              />
              <Typography variant="caption" fontWeight={800} sx={{ color: cfg.color, minWidth: 34 }}>
                {confidence}%
              </Typography>
            </Box>
          </Box>
        </Box>

        {/* ── Prices ── */}
        {!compact && (
          <Box display="flex" gap={2} mb={1.5}>
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">
                Precio sugerido compra
              </Typography>
              <Typography variant="body2" fontWeight={800} sx={{ color: TOKENS.green, fontVariantNumeric: 'tabular-nums' }}>
                {f4(latest.suggested_buy)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">
                Precio sugerido venta
              </Typography>
              <Typography variant="body2" fontWeight={800} sx={{ color: TOKENS.blue, fontVariantNumeric: 'tabular-nums' }}>
                {f4(latest.suggested_sell)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">
                Spread
              </Typography>
              <Typography variant="body2" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                {latest.suggested_spread_pct.toFixed(3)}%
              </Typography>
            </Box>
          </Box>
        )}

        {/* ── Sparkline (7-day trend) ── */}
        {sparkline.length > 1 && (
          <Box mb={1.5}>
            <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
              Tendencia precio venta (últimas {sparkline.length} decisiones)
            </Typography>
            <ResponsiveContainer width="100%" height={compact ? 36 : 52}>
              <AreaChart data={sparkline} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id={`grad-${currency}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%"   stopColor={cfg.color} stopOpacity={0.25} />
                    <stop offset="100%" stopColor={cfg.color} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke={cfg.color}
                  strokeWidth={1.5}
                  fill={`url(#grad-${currency})`}
                  dot={false}
                  activeDot={{ r: 3, fill: cfg.color }}
                />
                <RTooltip
                  formatter={(v: any) => [`Bs ${Number(v).toFixed(4)}`, 'Venta sugerida']}
                  contentStyle={{ fontSize: 11, borderRadius: 6, border: `1px solid ${TOKENS.border}` }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </Box>
        )}

        {/* ── Rate comparison: Binance · Empresa · Competencia ── */}
        {!compact && (
          <Box mb={1.5}>
            <Typography variant="caption" color="text.secondary" fontWeight={700}
              textTransform="uppercase" letterSpacing={0.5} display="block" mb={0.5}>
              Indicadores de mercado
            </Typography>
            <Box display="flex" flexDirection="column" gap={0.3}>
              <RateBar
                label="Binance"
                value={latest.rates_used.binance}
                reference={latest.base_rate}
              />
              <RateBar
                label="Empresa"
                value={latest.actual_sell}
                reference={latest.base_rate}
              />
              <RateBar
                label="Competencia"
                value={latest.rates_used.competition}
                reference={latest.base_rate}
              />
              <RateBar
                label="BCB"
                value={latest.rates_used.bcb}
                reference={latest.base_rate}
              />
            </Box>
          </Box>
        )}

        {/* ── Reasoning ── */}
        {latest.recommendation && !compact && (
          <>
            <Divider sx={{ mb: 1 }} />
            <Box display="flex" gap={0.75} mb={1.5}>
              <Psychology sx={{ fontSize: 14, color: TOKENS.muted, flexShrink: 0, mt: 0.15 }} />
              <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic', lineHeight: 1.4 }}>
                {latest.recommendation}
              </Typography>
            </Box>
          </>
        )}

        {/* ── Action button ── */}
        <Tooltip
          title={
            signal === 'ESPERAR'
              ? 'Las señales son neutrales — puedes usar los precios sugeridos de todas formas'
              : `Precarga ${preset.txType === 'BUY' ? 'compra' : 'venta'} de ${currency} al precio sugerido`
          }
        >
          <Button
            fullWidth
            variant={signal === 'ESPERAR' ? 'outlined' : 'contained'}
            size={compact ? 'small' : 'medium'}
            startIcon={<FlashOn />}
            onClick={() => onUseRecommendation(preset)}
            sx={{
              fontWeight: 700,
              bgcolor: signal !== 'ESPERAR' ? cfg.color : undefined,
              borderColor: signal === 'ESPERAR' ? cfg.color : undefined,
              color: signal === 'ESPERAR' ? cfg.color : 'white',
              '&:hover': {
                bgcolor: signal !== 'ESPERAR' ? alpha(cfg.color, 0.85) : alpha(cfg.color, 0.08),
              },
            }}
          >
            Usar recomendación
          </Button>
        </Tooltip>

      </CardContent>
    </Card>
  );
};

export default DecisionCard;
