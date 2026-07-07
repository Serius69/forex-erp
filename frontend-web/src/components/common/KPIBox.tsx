import React, { memo } from 'react';
import { Box, Card, CardContent, Typography, Skeleton, Tooltip } from '@mui/material';
import { ArrowUpward, ArrowDownward, TrendingFlat } from '@mui/icons-material';
import { motion } from 'framer-motion';
import { alpha } from '@mui/material/styles';
import { AreaChart, Area, ResponsiveContainer } from 'recharts';
import { TOKENS } from '../../styles/theme';

export type KPIStatus = 'good' | 'warning' | 'critical' | 'neutral';

interface KPIBoxProps {
  title:        string;
  value:        string;
  subtitle?:    string;
  change?:      number;
  changeLabel?: string;
  icon?:        React.ReactNode;
  accent?:      string;
  loading?:     boolean;
  sparkline?:   Array<{ v: number }>;
  size?:        'sm' | 'md' | 'lg';
  delay?:       number;
  status?:      KPIStatus;
  tooltip?:     string;
}

const STATUS_BG: Record<KPIStatus, string> = {
  good:    alpha(TOKENS.green,    0.04),
  warning: alpha(TOKENS.amber,    0.05),
  critical:alpha(TOKENS.red,      0.05),
  neutral: 'transparent',
};
const STATUS_BORDER: Record<KPIStatus, string> = {
  good:    alpha(TOKENS.green,    0.18),
  warning: alpha(TOKENS.amber,    0.22),
  critical:alpha(TOKENS.red,      0.22),
  neutral: TOKENS.border,
};

const KPIBox: React.FC<KPIBoxProps> = memo(({
  title, value, subtitle, change, changeLabel = 'vs ayer',
  icon, accent = TOKENS.blue, loading = false,
  sparkline, size = 'md', delay = 0,
  status = 'neutral', tooltip,
}) => {
  const positive  = (change ?? 0) > 0;
  const isNeutral = change === undefined || change === 0;
  const valueVariant = size === 'lg' ? 'h3' : size === 'sm' ? 'h5' : 'h4';

  const cardContent = (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, delay, ease: 'easeOut' }}
      style={{ height: '100%' }}
    >
      <Card sx={{
        height: '100%',
        position: 'relative',
        overflow: 'hidden',
        bgcolor: STATUS_BG[status],
        borderColor: STATUS_BORDER[status],
        ...(status === 'critical' ? {
          animation: 'kpi-critical-pulse 3s ease-in-out infinite',
        } : {}),
      }}>
        {/* Top accent bar */}
        <Box sx={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 3,
          bgcolor: accent,
          borderRadius: '14px 14px 0 0',
          ...(status === 'critical' ? { boxShadow: `0 0 8px ${alpha(accent, 0.6)}` } : {}),
        }} />

        <CardContent sx={{ pt: 2.5 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <Box sx={{ flex: 1, minWidth: 0, pr: icon ? 1 : 0 }}>
              <Typography variant="overline" color="text.secondary" noWrap sx={{ fontSize: '0.65rem' }}>
                {title}
              </Typography>
              {loading ? (
                <Skeleton width={100} height={size === 'lg' ? 48 : 38} sx={{ mt: 0.5 }} />
              ) : (
                <Typography
                  variant={valueVariant}
                  fontWeight={800}
                  sx={{
                    color: accent,
                    lineHeight: 1.1, mt: 0.25,
                    fontVariantNumeric: 'tabular-nums',
                    letterSpacing: '-0.01em',
                  }}
                >
                  {value}
                </Typography>
              )}
              {subtitle && !loading && (
                <Typography variant="caption" color="text.secondary" noWrap sx={{ mt: 0.125, display: 'block' }}>
                  {subtitle}
                </Typography>
              )}
            </Box>
            {icon && (
              <Box sx={{
                width: 40, height: 40, borderRadius: '11px', flexShrink: 0,
                bgcolor: alpha(accent, 0.1),
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: accent,
                transition: 'transform 0.2s ease',
                '&:hover': { transform: 'scale(1.08)' },
              }}>
                {icon}
              </Box>
            )}
          </Box>

          {sparkline && sparkline.length > 0 && !loading && (
            <Box sx={{ mt: 1.5, mx: -0.5 }}>
              <ResponsiveContainer width="100%" height={34}>
                <AreaChart data={sparkline} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id={`kpi-sg-${title.replace(/\s/g, '')}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={accent} stopOpacity={0.22} />
                      <stop offset="95%" stopColor={accent} stopOpacity={0}    />
                    </linearGradient>
                  </defs>
                  <Area type="monotone" dataKey="v" stroke={accent} strokeWidth={1.5}
                    fill={`url(#kpi-sg-${title.replace(/\s/g, '')})`}
                    dot={false} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </Box>
          )}

          {change !== undefined && !loading && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: sparkline ? 0.5 : 1.5 }}>
              <Box sx={{
                display: 'flex', alignItems: 'center', gap: 0.25,
                px: 0.75, py: 0.2, borderRadius: '5px',
                bgcolor: isNeutral
                  ? alpha(TOKENS.muted, 0.1)
                  : positive ? alpha(TOKENS.green, 0.12) : alpha(TOKENS.red, 0.1),
              }}>
                {isNeutral
                  ? <TrendingFlat sx={{ fontSize: 11, color: TOKENS.muted }} />
                  : positive
                    ? <ArrowUpward   sx={{ fontSize: 11, color: TOKENS.green }} />
                    : <ArrowDownward sx={{ fontSize: 11, color: TOKENS.red }} />
                }
                <Typography variant="caption" fontWeight={700} sx={{
                  color: isNeutral ? TOKENS.muted : positive ? TOKENS.green : TOKENS.red,
                }}>
                  {Math.abs(change).toFixed(1)}%
                </Typography>
              </Box>
              <Typography variant="caption" color="text.secondary">{changeLabel}</Typography>
            </Box>
          )}
        </CardContent>

        {/* Critical indicator dot */}
        {status === 'critical' && !loading && (
          <Box sx={{
            position: 'absolute', top: 12, right: 12,
            width: 7, height: 7, borderRadius: '50%',
            bgcolor: TOKENS.red,
            boxShadow: `0 0 6px ${alpha(TOKENS.red, 0.7)}`,
            animation: 'kpi-critical-pulse 1.5s ease-in-out infinite',
          }} />
        )}
      </Card>

      <style>{`
        @keyframes kpi-critical-pulse {
          0%, 100% { box-shadow: 0 1px 3px rgba(15,23,42,0.05); }
          50%       { box-shadow: 0 0 0 3px ${alpha(TOKENS.red, 0.12)}, 0 4px 16px rgba(239,68,68,0.1); }
        }
      `}</style>
    </motion.div>
  );

  return tooltip
    ? <Tooltip title={tooltip} placement="top" arrow>{cardContent}</Tooltip>
    : cardContent;
});

KPIBox.displayName = 'KPIBox';
export default KPIBox;
