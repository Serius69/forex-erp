// src/components/common/KPICard.tsx
import React from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Skeleton,
  Tooltip, IconButton,
} from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import TrendingFlatIcon from '@mui/icons-material/TrendingFlat';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type KPITrend = 'up' | 'down' | 'stable';
export type KPIVariant = 'default' | 'success' | 'warning' | 'error' | 'info';

export interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: KPITrend;
  trendValue?: string;
  trendLabel?: string;
  variant?: KPIVariant;
  icon?: React.ReactNode;
  tooltip?: string;
  loading?: boolean;
  compact?: boolean;
  onClick?: () => void;
  prefix?: string;
  suffix?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Color map
// ─────────────────────────────────────────────────────────────────────────────

const VARIANT_COLORS: Record<KPIVariant, { bg: string; border: string; value: string }> = {
  default: { bg: 'background.paper',   border: 'divider',           value: 'text.primary' },
  success: { bg: 'success.50',          border: 'success.200',       value: 'success.dark' },
  warning: { bg: 'warning.50',          border: 'warning.200',       value: 'warning.dark' },
  error:   { bg: 'error.50',            border: 'error.200',         value: 'error.dark' },
  info:    { bg: 'info.50',             border: 'info.200',          value: 'info.dark' },
};

const TREND_COLORS: Record<KPITrend, 'success' | 'error' | 'default'> = {
  up:     'success',
  down:   'error',
  stable: 'default',
};

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function KPICard({
  title,
  value,
  subtitle,
  trend,
  trendValue,
  trendLabel,
  variant = 'default',
  icon,
  tooltip,
  loading = false,
  compact = false,
  onClick,
  prefix,
  suffix,
}: KPICardProps) {
  const colors = VARIANT_COLORS[variant];

  const TrendIcon =
    trend === 'up'     ? TrendingUpIcon :
    trend === 'down'   ? TrendingDownIcon :
    TrendingFlatIcon;

  const trendColor = trend ? TREND_COLORS[trend] : 'default';

  return (
    <Card
      elevation={0}
      onClick={onClick}
      sx={{
        bgcolor: colors.bg,
        border: '1px solid',
        borderColor: colors.border,
        cursor: onClick ? 'pointer' : 'default',
        transition: 'box-shadow 0.2s, transform 0.1s',
        '&:hover': onClick ? {
          boxShadow: 3,
          transform: 'translateY(-1px)',
        } : {},
        height: '100%',
      }}
    >
      <CardContent sx={{ p: compact ? 1.5 : 2, '&:last-child': { pb: compact ? 1.5 : 2 } }}>
        {/* Header row */}
        <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flex: 1, minWidth: 0 }}>
            {icon && (
              <Box sx={{ color: colors.value, flexShrink: 0, '& svg': { fontSize: 18 } }}>
                {icon}
              </Box>
            )}
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{
                fontWeight: 500,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                lineHeight: 1.3,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {title}
            </Typography>
          </Box>
          {tooltip && (
            <Tooltip title={tooltip} placement="top" arrow>
              <IconButton size="small" sx={{ p: 0.25, color: 'text.disabled' }}>
                <InfoOutlinedIcon sx={{ fontSize: 14 }} />
              </IconButton>
            </Tooltip>
          )}
        </Box>

        {/* Value */}
        {loading ? (
          <Skeleton variant="text" width="75%" height={compact ? 32 : 40} />
        ) : (
          <Typography
            variant={compact ? 'h6' : 'h5'}
            sx={{
              fontWeight: 700,
              color: colors.value,
              lineHeight: 1.2,
              letterSpacing: '-0.01em',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {prefix && <span style={{ fontSize: '0.7em', fontWeight: 400, marginRight: 2 }}>{prefix}</span>}
            {value}
            {suffix && <span style={{ fontSize: '0.65em', fontWeight: 400, marginLeft: 3 }}>{suffix}</span>}
          </Typography>
        )}

        {/* Subtitle */}
        {subtitle && !loading && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            {subtitle}
          </Typography>
        )}

        {/* Trend chip */}
        {(trend || trendValue) && !loading && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 1 }}>
            <Chip
              icon={<TrendIcon sx={{ fontSize: '14px !important' }} />}
              label={trendValue || ''}
              size="small"
              color={trendColor as 'success' | 'error' | 'default'}
              variant="outlined"
              sx={{
                height: 20,
                fontSize: 11,
                fontWeight: 600,
                '& .MuiChip-label': { px: 0.75 },
                '& .MuiChip-icon': { ml: 0.5 },
              }}
            />
            {trendLabel && (
              <Typography variant="caption" color="text.secondary">
                {trendLabel}
              </Typography>
            )}
          </Box>
        )}
      </CardContent>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// KPI Grid — helper to render a row of KPI cards
// ─────────────────────────────────────────────────────────────────────────────

import { Grid } from '@mui/material';

export interface KPIGridItem extends KPICardProps {
  key: string;
  xs?: number;
  sm?: number;
  md?: number;
}

export function KPIGrid({ items }: { items: KPIGridItem[] }) {
  const colSize = Math.max(2, Math.floor(12 / items.length));
  return (
    <Grid container spacing={2}>
      {items.map(({ key, xs = 12, sm = 6, md = colSize, ...cardProps }) => (
        <Grid item xs={xs} sm={sm} md={md} key={key}>
          <KPICard {...cardProps} />
        </Grid>
      ))}
    </Grid>
  );
}

export default KPICard;
