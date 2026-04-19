import React, { memo } from 'react';
import { Box, Card, CardContent, Typography, Skeleton } from '@mui/material';
import { BarChart as BarChartIcon } from '@mui/icons-material';
import { motion } from 'framer-motion';
import { TOKENS } from '../../styles/theme';

interface ChartCardProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  loading?: boolean;
  height?: number;
  action?: React.ReactNode;
  emptyMessage?: string;
  isEmpty?: boolean;
  delay?: number;
  noPadding?: boolean;
}

const ChartCard: React.FC<ChartCardProps> = memo(({
  title, subtitle, children, loading = false,
  height = 240, action, emptyMessage = 'Sin datos disponibles',
  isEmpty = false, delay = 0, noPadding = false,
}) => (
  <motion.div
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.32, delay, ease: 'easeOut' }}
    style={{ height: '100%' }}
  >
    <Card sx={{ height: '100%' }}>
      <CardContent sx={noPadding ? { p: 0, '&:last-child': { pb: 0 } } : {}}>
        <Box sx={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
          mb: 2, ...(noPadding ? { px: 2.5, pt: 2.5 } : {}),
        }}>
          <Box>
            <Typography variant="h6" fontWeight={700}>{title}</Typography>
            {subtitle && (
              <Typography variant="caption" color="text.secondary">{subtitle}</Typography>
            )}
          </Box>
          {action && <Box>{action}</Box>}
        </Box>

        {loading ? (
          <Box sx={noPadding ? { px: 2.5, pb: 2.5 } : {}}>
            <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 2 }} />
          </Box>
        ) : isEmpty ? (
          <Box sx={{
            height, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 1,
            bgcolor: TOKENS.bg, borderRadius: 2,
            ...(noPadding ? { mx: 2.5, mb: 2.5 } : {}),
          }}>
            <BarChartIcon sx={{ fontSize: 36, color: TOKENS.border }} />
            <Typography variant="body2" color="text.secondary">{emptyMessage}</Typography>
          </Box>
        ) : (
          <Box sx={{ height, ...(noPadding ? { px: 2.5, pb: 2.5 } : {}) }}>
            {children}
          </Box>
        )}
      </CardContent>
    </Card>
  </motion.div>
));

ChartCard.displayName = 'ChartCard';
export default ChartCard;
