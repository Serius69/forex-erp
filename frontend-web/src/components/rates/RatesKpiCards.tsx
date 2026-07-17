import React from 'react';
import { Box, Typography, Card, CardContent, Chip, Grid } from '@mui/material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';
import { isScaled, formatScale, formatRate } from '../../utils/finance';
import { SourceBadge, ConfidenceBar } from './RateBadges';
import type { ExchangeRate } from './rateTypes';

// KPI cards con las primeras tasas (par, compra/venta, spread, confianza).
const RatesKpiCards: React.FC<{ rates: ExchangeRate[] }> = ({ rates }) => (
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
);

export default RatesKpiCards;
