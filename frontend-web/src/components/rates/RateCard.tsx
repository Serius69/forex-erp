// src/components/rates/RateCard.tsx
// Card de tasa digital en tiempo real para una divisa.
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Skeleton,
  Tooltip, Alert, Link,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { TOKENS } from '../../styles/theme';
import { ratesApi, LiveRate } from '../../services/ratesApi';
import RateSourceBadge from './RateSourceBadge';
import RateVariationChip from './RateVariationChip';

// ── Helpers ───────────────────────────────────────────────────────────────────

const isStale = (ts: string | null | undefined, minutes = 30) =>
  !ts || (Date.now() - new Date(ts).getTime()) > minutes * 60_000;

const confidenceColor = (v: number) =>
  v >= 0.90 ? '#4caf50' : v >= 0.70 ? '#ff9800' : '#f44336';

const StatusBadge: React.FC<{ isLive: boolean; stale: boolean }> = ({ isLive, stale }) => {
  if (stale)   return <Chip label="SIN DATOS" size="small" color="error"   variant="outlined" sx={{ fontSize: '0.6rem', height: 20, fontWeight: 700 }} />;
  if (!isLive) return <Chip label="CACHÉ"     size="small" color="warning" variant="outlined" sx={{ fontSize: '0.6rem', height: 20, fontWeight: 700 }} />;
  return (
    <Chip
      label="EN VIVO"
      size="small"
      color="success"
      sx={{
        fontSize: '0.6rem', height: 20, fontWeight: 800,
        animation: 'live-pulse 2.5s ease-in-out infinite',
      }}
    />
  );
};

// ── RateCard ──────────────────────────────────────────────────────────────────

interface RateCardProps {
  currency:          string;
  /** Tasas previas para calcular variación (opcional) */
  previousBuy?:      number | null;
  previousSell?:     number | null;
  /** Refresco periódico en ms (default: 60s) */
  refreshInterval?:  number;
  /** Callback cuando se recibe la tasa (para propagarla a padre) */
  onRateLoaded?:     (rate: LiveRate) => void;
}

const CURRENCY_FLAGS: Record<string, string> = {
  USD: '🇺🇸', EUR: '🇪🇺', BRL: '🇧🇷', PEN: '🇵🇪', CLP: '🇨🇱', ARS: '🇦🇷', GBP: '🇬🇧',
};

const RateCard: React.FC<RateCardProps> = ({
  currency, previousBuy, previousSell, refreshInterval = 60_000, onRateLoaded,
}) => {
  const [rate,    setRate]    = useState<LiveRate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(false);
  const prevBuyRef  = useRef<number | null>(null);
  const prevSellRef = useRef<number | null>(null);

  const fetchRate = useCallback(async () => {
    try {
      // Guardar previo antes de actualizar
      if (rate) {
        prevBuyRef.current  = rate.buy;
        prevSellRef.current = rate.sell;
      }
      const data = await ratesApi.getLiveRate(currency);
      setRate(data);
      setError(false);
      onRateLoaded?.(data);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [currency, onRateLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchRate();
    const id = setInterval(fetchRate, refreshInterval);
    return () => clearInterval(id);
  }, [fetchRate, refreshInterval]);

  const flag    = CURRENCY_FLAGS[currency] ?? '💱';
  const stale   = isStale(rate?.timestamp);

  // ── Loading ──────────────────────────────────────────────────────────────
  if (loading) return (
    <Card sx={{ minHeight: 160, border: '1px solid', borderColor: 'divider' }}>
      <CardContent>
        <Box display="flex" alignItems="center" gap={1} mb={1.5}>
          <Skeleton variant="circular" width={28} height={28} />
          <Skeleton variant="text" width={80} height={24} />
        </Box>
        <Box display="flex" justifyContent="space-between" mb={1}>
          <Skeleton variant="text" width={70} height={44} />
          <Skeleton variant="text" width={70} height={44} />
        </Box>
        <Skeleton variant="text" width={140} height={18} />
      </CardContent>
    </Card>
  );

  // ── Error / sin datos ────────────────────────────────────────────────────
  if (error || !rate) return (
    <Card sx={{ minHeight: 120, border: '1px solid', borderColor: 'error.light', bgcolor: alpha(TOKENS.red, 0.03) }}>
      <CardContent>
        <Box display="flex" alignItems="center" gap={1} mb={1}>
          <Typography sx={{ fontSize: '1.4rem' }}>{flag}</Typography>
          <Typography fontWeight={800}>{currency}/BOB</Typography>
          <Chip label="SIN DATOS" size="small" color="error" variant="outlined" sx={{ fontSize: '0.6rem', height: 20 }} />
        </Box>
        <Typography variant="caption" color="text.disabled" fontStyle="italic">
          Sin conexión a fuentes en tiempo real
        </Typography>
      </CardContent>
    </Card>
  );

  const accentColor = stale
    ? TOKENS.red
    : rate.source === 'binance' ? TOKENS.green
    : rate.is_live ? TOKENS.green : TOKENS.amber;

  const effectivePrevBuy  = previousBuy  ?? prevBuyRef.current;
  const effectivePrevSell = previousSell ?? prevSellRef.current;

  return (
    <Card sx={{
      position: 'relative', overflow: 'hidden', minHeight: 160,
      border: '1px solid',
      borderColor: stale ? alpha(TOKENS.red, 0.3) :
                   rate.anomalies.length > 0 ? 'warning.light' :
                   alpha(accentColor, 0.25),
      bgcolor: stale ? alpha(TOKENS.red, 0.02) :
               rate.anomalies.length > 0 ? alpha(TOKENS.amber, 0.03) :
               alpha(accentColor, 0.02),
      transition: 'transform 0.18s, box-shadow 0.18s',
      '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 8px 24px rgba(15,23,42,0.10)' },
    }}>
      {/* Barra de color superior */}
      <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, bgcolor: accentColor }} />

      <CardContent sx={{ pt: 2, pb: '12px !important' }}>
        {/* Header */}
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={1} flexWrap="wrap" gap={0.5}>
          <Box display="flex" alignItems="center" gap={0.75}>
            <Typography sx={{ fontSize: '1.3rem', lineHeight: 1 }}>{flag}</Typography>
            <Typography variant="subtitle1" fontWeight={900} sx={{ letterSpacing: '-0.01em' }}>
              {currency}
              <Typography component="span" sx={{ color: TOKENS.muted, fontWeight: 400, mx: 0.4 }}>/</Typography>
              BOB
            </Typography>
          </Box>
          <Box display="flex" alignItems="center" gap={0.5} flexWrap="wrap">
            <StatusBadge isLive={rate.is_live} stale={stale} />
            <RateSourceBadge source={rate.source} confidence={rate.confidence} fetchedAt={rate.timestamp} sourceUrl={rate.source_url} />
          </Box>
        </Box>

        {/* Compra / Venta */}
        <Box display="flex" justifyContent="space-between" alignItems="flex-end" mb={1}>
          <Box>
            <Typography variant="overline" sx={{ fontSize: '0.58rem', color: TOKENS.muted, lineHeight: 1 }}>
              Compra
            </Typography>
            <Box display="flex" alignItems="baseline" gap={0.5}>
              <Typography variant="h4" fontWeight={900} sx={{ color: TOKENS.green, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
                {rate.buy.toFixed(4)}
              </Typography>
              {effectivePrevBuy !== null && (
                <RateVariationChip current={rate.buy} previous={effectivePrevBuy} compact />
              )}
            </Box>
          </Box>

          <Typography variant="body2" sx={{ color: 'text.disabled', mb: 0.25 }}>BOB</Typography>

          <Box textAlign="right">
            <Typography variant="overline" sx={{ fontSize: '0.58rem', color: TOKENS.muted, lineHeight: 1 }}>
              Venta
            </Typography>
            <Box display="flex" alignItems="baseline" gap={0.5}>
              {effectivePrevSell !== null && (
                <RateVariationChip current={rate.sell} previous={effectivePrevSell} compact />
              )}
              <Typography variant="h4" fontWeight={900} sx={{ color: TOKENS.red, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
                {rate.sell.toFixed(4)}
              </Typography>
            </Box>
          </Box>
        </Box>

        {/* Métricas inferiores */}
        <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={0.5}>
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem' }}>
            Spread:{' '}
            <strong style={{ color: rate.spread_pct > 3 ? TOKENS.amber : 'inherit' }}>
              {rate.spread_pct.toFixed(2)}%
            </strong>
            {' · '}
            Conf:{' '}
            <strong style={{ color: confidenceColor(rate.confidence) }}>
              {(rate.confidence * 100).toFixed(0)}%
            </strong>
          </Typography>
          <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.6rem' }}>
            {rate.timestamp
              ? format(new Date(rate.timestamp), 'HH:mm:ss', { locale: es })
              : '—'}
          </Typography>
        </Box>

        {/* Anomalías */}
        {rate.anomalies.length > 0 && (
          <Box mt={0.75}>
            {rate.anomalies.slice(0, 2).map((a, i) => (
              <Alert
                key={i}
                severity={a.severity === 'CRITICAL' ? 'error' : 'warning'}
                sx={{ py: 0, px: 0.75, fontSize: '0.62rem', mb: 0.25 }}
                icon={false}
              >
                {a.message}
              </Alert>
            ))}
          </Box>
        )}

        {/* URL de fuente */}
        {rate.source_url && (
          <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.58rem', display: 'block', mt: 0.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            <Link href={rate.source_url} target="_blank" rel="noopener" color="inherit" underline="hover">
              {rate.source_url}
            </Link>
          </Typography>
        )}
      </CardContent>

      <style>{`
        @keyframes live-pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.7; }
        }
      `}</style>
    </Card>
  );
};

export default RateCard;
