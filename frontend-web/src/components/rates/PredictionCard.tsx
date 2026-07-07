// src/components/rates/PredictionCard.tsx
// Card de predicción ML con sparkline Recharts y banda de confianza.
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Skeleton,
  Tooltip, LinearProgress, Divider,
} from '@mui/material';
import { Psychology, BubbleChart, TrendingUp, Error as ErrorIcon } from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip as RTooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { format, parseISO, isValid } from 'date-fns';
import { es } from 'date-fns/locale';
import { TOKENS } from '../../styles/theme';
import { ratesApi, ForecastResult } from '../../services/ratesApi';

// ── Helpers ───────────────────────────────────────────────────────────────────

const MODEL_COLORS: Record<string, string> = {
  Prophet:  '#2563eb',
  BiLSTM:   '#7c3aed',
  LSTM:     '#7c3aed',
  XGBoost:  '#059669',
  ARIMA:    '#d97706',
  Ridge:    '#db2777',
  Ensemble: '#0f172a',
};

const healthStatus = (mape: number | null | undefined): { label: string; color: 'success' | 'warning' | 'error'; bg: string } => {
  if (mape === null || mape === undefined) return { label: 'Sin datos', color: 'error',   bg: '#ffebee' };
  if (mape < 2)  return { label: 'Excelente', color: 'success', bg: '#e8f5e9' };
  if (mape < 5)  return { label: 'Bueno',     color: 'success', bg: '#e8f5e9' };
  if (mape < 10) return { label: 'Regular',   color: 'warning', bg: '#fff8e1' };
  return              { label: 'Degradado', color: 'error',   bg: '#ffebee' };
};

/** Extrae la predicción más cercana a N horas desde ahora */
const predAtHorizon = (
  predictions: ForecastResult['predictions'],
  hoursAhead: number,
): ForecastResult['predictions'][0] | null => {
  if (!predictions.length) return null;
  const target = Date.now() + hoursAhead * 3_600_000;
  return predictions.reduce((best, p) => {
    const dBest = Math.abs(new Date(best.datetime).getTime() - target);
    const dP    = Math.abs(new Date(p.datetime).getTime()    - target);
    return dP < dBest ? p : best;
  });
};

// ── Sparkline Recharts ─────────────────────────────────────────────────────

const ForecastSparkline: React.FC<{ data: ForecastResult['predictions']; color: string }> = ({ data, color }) => {
  if (!data.length) return null;

  const chartData = data.map(p => ({
    t:     format(parseISO(p.datetime), 'HH:mm', { locale: es }),
    rate:  p.rate,
    lower: p.lower,
    upper: p.upper,
    band:  [p.lower, p.upper] as [number, number],
  }));

  const midRate = data[0]?.rate;

  return (
    <ResponsiveContainer width="100%" height={72}>
      <AreaChart data={chartData} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={`fc-grad-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={color} stopOpacity={0.25} />
            <stop offset="95%" stopColor={color} stopOpacity={0}    />
          </linearGradient>
          <linearGradient id={`fc-ci-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={color} stopOpacity={0.10} />
            <stop offset="95%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>

        {/* Banda de confianza: lower → upper */}
        <Area
          type="monotone"
          dataKey="upper"
          stroke="none"
          fill={`url(#fc-ci-${color.replace('#', '')})`}
          isAnimationActive={false}
        />
        <Area
          type="monotone"
          dataKey="lower"
          stroke="none"
          fill="white"
          isAnimationActive={false}
        />

        {/* Línea principal */}
        <Area
          type="monotone"
          dataKey="rate"
          stroke={color}
          strokeWidth={2}
          fill={`url(#fc-grad-${color.replace('#', '')})`}
          dot={false}
          isAnimationActive={false}
        />

        {midRate && (
          <ReferenceLine y={midRate} stroke={alpha(color, 0.3)} strokeDasharray="3 3" />
        )}

        <RTooltip
          contentStyle={{ fontSize: '0.65rem', padding: '4px 8px' }}
          formatter={(v: any) => [Number(v).toFixed(4), 'Tasa']}
          labelFormatter={(l) => `${l}`}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
};

// ── Horizons ──────────────────────────────────────────────────────────────────

const HorizonRow: React.FC<{
  label: string;
  hours: number;
  predictions: ForecastResult['predictions'];
  color: string;
}> = ({ label, hours, predictions, color }) => {
  const p = predAtHorizon(predictions, hours);
  if (!p) return null;
  return (
    <Box
      display="flex"
      alignItems="center"
      justifyContent="space-between"
      sx={{
        px: 1.25, py: 0.6,
        borderRadius: '6px',
        bgcolor: alpha(color, 0.05),
        border: '1px solid',
        borderColor: alpha(color, 0.15),
      }}
    >
      <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ minWidth: 28 }}>
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={900} sx={{ color, fontVariantNumeric: 'tabular-nums' }}>
        {p.rate.toFixed(4)}
      </Typography>
      <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.62rem', fontVariantNumeric: 'tabular-nums' }}>
        [{p.lower.toFixed(3)} – {p.upper.toFixed(3)}]
      </Typography>
    </Box>
  );
};

// ── PredictionCard ─────────────────────────────────────────────────────────────

interface PredictionCardProps {
  /** Par en formato "USD-BOB" (se convierte a "USD/BOB" para la API) */
  pair:    string;
  horizon?: '1h' | '4h' | '24h' | '7d';
  color?:  string;
}

const PredictionCard: React.FC<PredictionCardProps> = ({
  pair, horizon = '24h', color = TOKENS.blue,
}) => {
  const [data,    setData]    = useState<ForecastResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const fetchForecast = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const result = await ratesApi.getForecast(pair, horizon);
      setData(result);
    } catch (e: any) {
      setError(e?.response?.data?.error ?? 'Error al obtener predicción');
    } finally {
      setLoading(false);
    }
  }, [pair, horizon]);

  useEffect(() => { fetchForecast(); }, [fetchForecast]);

  // ── Modelo dominante ─────────────────────────────────────────────────────
  const dominantModel = React.useMemo(() => {
    if (!data?.model_weights) return null;
    return Object.entries(data.model_weights).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
  }, [data]);

  const mape    = data?.backtesting_metrics?.mape ?? null;
  const health  = healthStatus(mape);
  const modColor = dominantModel ? (MODEL_COLORS[dominantModel] ?? color) : color;

  // ── Loading ──────────────────────────────────────────────────────────────
  if (loading) return (
    <Card sx={{ border: '1px solid', borderColor: 'divider', minHeight: 260 }}>
      <CardContent>
        <Box display="flex" alignItems="center" gap={1} mb={1.5}>
          <Skeleton variant="circular" width={28} height={28} />
          <Skeleton variant="text" width={100} height={24} />
        </Box>
        <Skeleton variant="rectangular" width="100%" height={72} sx={{ borderRadius: 1, mb: 1.5 }} />
        <Skeleton variant="text" width="80%" height={18} />
        <Skeleton variant="text" width="60%" height={18} />
      </CardContent>
    </Card>
  );

  // ── Error ────────────────────────────────────────────────────────────────
  if (error || !data) return (
    <Card sx={{ border: '1px solid', borderColor: 'error.light', bgcolor: alpha(TOKENS.red, 0.03), minHeight: 160 }}>
      <CardContent>
        <Box display="flex" alignItems="center" gap={1} mb={1}>
          <ErrorIcon color="error" sx={{ fontSize: 20 }} />
          <Typography fontWeight={800} color="error.main">{pair.replace('-', '/')}</Typography>
        </Box>
        <Typography variant="caption" color="text.disabled" fontStyle="italic">
          {error ?? 'Sin datos de predicción'}
        </Typography>
      </CardContent>
    </Card>
  );

  return (
    <Card sx={{
      position: 'relative', overflow: 'hidden', minHeight: 260,
      border: '1px solid', borderColor: alpha(modColor, 0.25),
      bgcolor: alpha(modColor, 0.02),
      transition: 'transform 0.18s, box-shadow 0.18s',
      '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 8px 24px rgba(15,23,42,0.10)' },
    }}>
      <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, bgcolor: modColor }} />

      <CardContent sx={{ pt: 2, pb: '10px !important' }}>
        {/* Header */}
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={0.75} flexWrap="wrap" gap={0.5}>
          <Box display="flex" alignItems="center" gap={0.75}>
            <Psychology sx={{ color: modColor, fontSize: 18 }} />
            <Typography variant="subtitle1" fontWeight={900}>
              {data.currency_pair.replace('/', ' / ')}
            </Typography>
          </Box>
          <Box display="flex" alignItems="center" gap={0.5} flexWrap="wrap">
            <Chip
              label={health.label}
              size="small"
              color={health.color}
              sx={{ fontSize: '0.6rem', height: 20, fontWeight: 700, bgcolor: health.bg }}
            />
            {dominantModel && (
              <Chip
                label={dominantModel}
                size="small"
                sx={{
                  fontSize: '0.6rem', height: 20, fontWeight: 700,
                  bgcolor: alpha(modColor, 0.12), color: modColor,
                }}
              />
            )}
          </Box>
        </Box>

        {/* Tasa predicha principal */}
        <Box display="flex" alignItems="baseline" gap={0.75} mb={0.5}>
          <Typography variant="h4" fontWeight={900} sx={{ color: modColor, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
            {data.predicted_rate.toFixed(4)}
          </Typography>
          <Typography variant="caption" color="text.secondary">BOB</Typography>
          {data.confidence_interval && (
            <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.62rem' }}>
              IC 95%: [{data.confidence_interval.lower.toFixed(3)} – {data.confidence_interval.upper.toFixed(3)}]
            </Typography>
          )}
        </Box>

        {/* MAPE */}
        {mape !== null && (
          <Box display="flex" alignItems="center" gap={0.5} mb={0.75}>
            <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.62rem' }}>
              MAPE:
            </Typography>
            <Typography variant="caption" fontWeight={700} sx={{ color: health.color === 'success' ? '#2e7d32' : health.color === 'warning' ? '#e65100' : '#c62828', fontSize: '0.65rem' }}>
              {mape.toFixed(2)}%
            </Typography>
          </Box>
        )}

        {/* Sparkline */}
        {data.predictions.length > 0 && (
          <Box mx={-0.5} mb={1}>
            <ForecastSparkline data={data.predictions} color={modColor} />
          </Box>
        )}

        <Divider sx={{ my: 0.75, opacity: 0.5 }} />

        {/* Horizontes */}
        <Box display="flex" flexDirection="column" gap={0.5}>
          <HorizonRow label="1h"  hours={1}  predictions={data.predictions} color={modColor} />
          <HorizonRow label="4h"  hours={4}  predictions={data.predictions} color={modColor} />
          <HorizonRow label="8h"  hours={8}  predictions={data.predictions} color={modColor} />
          <HorizonRow label="24h" hours={24} predictions={data.predictions} color={modColor} />
        </Box>

        {/* Pesos de modelos */}
        {data.model_weights && Object.keys(data.model_weights).length > 0 && (
          <Box mt={1}>
            <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.6rem', display: 'block', mb: 0.5 }}>
              Pesos del ensemble
            </Typography>
            <Box display="flex" gap={0.4} flexWrap="wrap">
              {Object.entries(data.model_weights)
                .sort((a, b) => b[1] - a[1])
                .map(([model, weight]) => (
                  <Tooltip key={model} title={`${model}: ${(weight * 100).toFixed(1)}%`} arrow>
                    <Box sx={{
                      display: 'flex', alignItems: 'center', gap: 0.25,
                      px: 0.6, py: 0.15, borderRadius: '4px',
                      bgcolor: alpha(MODEL_COLORS[model] ?? TOKENS.blue, 0.1),
                    }}>
                      <Typography variant="caption" sx={{
                        fontSize: '0.58rem', fontWeight: 700,
                        color: MODEL_COLORS[model] ?? TOKENS.blue,
                      }}>
                        {model}
                      </Typography>
                      <Box sx={{
                        width: Math.max(8, weight * 32), height: 3, borderRadius: 1,
                        bgcolor: MODEL_COLORS[model] ?? TOKENS.blue,
                      }} />
                    </Box>
                  </Tooltip>
                ))}
            </Box>
          </Box>
        )}

        {/* Timestamp */}
        <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.58rem', display: 'block', mt: 0.75 }}>
          {(() => { const d = parseISO(data.generated_at); return isValid(d) ? `Generado: ${format(d, 'dd/MM HH:mm', { locale: es })}` : ''; })()}
          {' · '}Datos hasta:{' '}
          {data.data_freshness && data.data_freshness !== 'INFERENCE'
            ? (() => { const d = parseISO(data.data_freshness); return isValid(d) ? format(d, 'dd/MM HH:mm', { locale: es }) : '—'; })()
            : data.data_freshness === 'INFERENCE' ? 'Inferida' : '—'}
        </Typography>
      </CardContent>
    </Card>
  );
};

export default PredictionCard;
