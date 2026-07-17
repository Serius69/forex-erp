import React from 'react';
import { Box, Typography, Card, CardContent, Chip, Alert, Link } from '@mui/material';
import { alpha } from '@mui/material/styles';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { TOKENS } from '../../styles/theme';
import { api } from '../../services/api';
import { formatRate, formatPercent } from '../../utils/finance';
import { LIVE_SOURCE_CONFIG, confidenceColor, confidenceDot, isStale } from './rateConfig';
import { LiveSourceBadge } from './RateBadges';
import type { LiveRate } from './rateTypes';

// Tarjeta de tasa en vivo (compra/venta EN VIVO, con badges de fuente,
// confianza, staleness y anomalías) para una divisa.
const LiveRateCard: React.FC<{ currency?: string }> = ({ currency = 'USD' }) => {
  const [rate, setRate]       = React.useState<LiveRate | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError]     = React.useState(false);

  const fetchLive = React.useCallback(async () => {
    setLoading(true); setError(false);
    try {
      const res = await api.get<LiveRate>(`/rates/exchange-rates/live/?currency=${currency}`);
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

export default LiveRateCard;
