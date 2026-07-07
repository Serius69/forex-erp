import React, { memo } from 'react';
import { Box, Card, CardContent, Typography, Skeleton, Button } from '@mui/material';
import { BarChart as BarChartIcon, AddCircleOutline } from '@mui/icons-material';
import { motion } from 'framer-motion';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';

interface ChartCardProps {
  title:            string;
  subtitle?:        string;
  children:         React.ReactNode;
  loading?:         boolean;
  height?:          number;
  action?:          React.ReactNode;
  emptyMessage?:    string;
  emptyHint?:       string;
  emptyActionLabel?:string;
  onEmptyAction?:   () => void;
  isEmpty?:         boolean;
  delay?:           number;
  noPadding?:       boolean;
}

const ChartCard: React.FC<ChartCardProps> = memo(({
  title, subtitle, children, loading = false,
  height = 240, action,
  emptyMessage = 'Sin datos disponibles',
  emptyHint, emptyActionLabel, onEmptyAction,
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
            {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
          </Box>
          {action && <Box>{action}</Box>}
        </Box>

        {loading ? (
          <Box sx={{ ...(noPadding ? { px: 2.5, pb: 2.5 } : {}) }}>
            <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 2 }} animation="wave" />
          </Box>
        ) : isEmpty ? (
          <Box sx={{
            height,
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 1.25,
            borderRadius: 2,
            border: `1.5px dashed ${TOKENS.border}`,
            bgcolor: alpha(TOKENS.bg, 0.6),
            ...(noPadding ? { mx: 2.5, mb: 2.5 } : {}),
          }}>
            <Box sx={{
              width: 44, height: 44, borderRadius: '12px',
              bgcolor: alpha(TOKENS.blue, 0.08),
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <BarChartIcon sx={{ fontSize: 22, color: alpha(TOKENS.blue, 0.4) }} />
            </Box>
            <Box sx={{ textAlign: 'center' }}>
              <Typography variant="body2" fontWeight={600} color="text.secondary">{emptyMessage}</Typography>
              {emptyHint && (
                <Typography variant="caption" color="text.disabled" sx={{ mt: 0.25, display: 'block' }}>
                  {emptyHint}
                </Typography>
              )}
            </Box>
            {emptyActionLabel && onEmptyAction && (
              <Button
                size="small"
                variant="outlined"
                startIcon={<AddCircleOutline sx={{ fontSize: '15px !important' }} />}
                onClick={onEmptyAction}
                sx={{
                  mt: 0.5, fontSize: '0.75rem', fontWeight: 600,
                  borderColor: alpha(TOKENS.blue, 0.35), color: TOKENS.blue,
                  '&:hover': { borderColor: TOKENS.blue, bgcolor: alpha(TOKENS.blue, 0.06) },
                }}
              >
                {emptyActionLabel}
              </Button>
            )}
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
