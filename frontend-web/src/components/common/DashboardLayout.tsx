import React, { memo, useState, useEffect } from 'react';
import { Box, Typography, IconButton, Tooltip, Chip } from '@mui/material';
import { Refresh, AccessTime } from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { motion } from 'framer-motion';
import { TOKENS } from '../../styles/theme';

interface DashboardLayoutProps {
  title:       string;
  subtitle?:   string;
  badge?:      string;
  badgeColor?: string;
  onRefresh?:  () => void;
  refreshing?: boolean;
  filters?:    React.ReactNode;
  children:    React.ReactNode;
}

const DashboardLayout: React.FC<DashboardLayoutProps> = memo(({
  title, subtitle, badge, badgeColor = TOKENS.green,
  onRefresh, refreshing = false, filters, children,
}) => {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const timeStr = now.toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' });

  return (
    <Box>
      {/* ── Page header ── */}
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
      >
        <Box sx={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
          mb: 3, gap: 2,
        }}>
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
              <Typography variant="h4" fontWeight={800} sx={{ letterSpacing: '-0.02em' }}>
                {title}
              </Typography>
              {badge && (
                <Box sx={{
                  px: 1, py: 0.2, borderRadius: '5px',
                  bgcolor: alpha(badgeColor, 0.12),
                  border: `1px solid ${alpha(badgeColor, 0.25)}`,
                }}>
                  <Typography variant="overline" sx={{ color: badgeColor, fontWeight: 800, fontSize: '0.6rem', lineHeight: 1 }}>
                    {badge}
                  </Typography>
                </Box>
              )}
            </Box>
            {subtitle && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, textTransform: 'capitalize' }}>
                {subtitle}
              </Typography>
            )}
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, flexShrink: 0 }}>
            {filters}

            {/* Live clock */}
            <Chip
              icon={<AccessTime sx={{ fontSize: '13px !important', color: `${TOKENS.textSub} !important` }} />}
              label={timeStr}
              size="small"
              sx={{
                height: 28, fontSize: '0.75rem', fontWeight: 600,
                bgcolor: TOKENS.surface, border: `1px solid ${TOKENS.border}`,
                color: TOKENS.textSub, fontVariantNumeric: 'tabular-nums',
                '& .MuiChip-label': { px: 1 },
              }}
            />

            {onRefresh && (
              <Tooltip title="Actualizar datos" arrow>
                <span>
                  <IconButton
                    size="small"
                    onClick={onRefresh}
                    disabled={refreshing}
                    sx={{
                      bgcolor: TOKENS.surface,
                      border: `1px solid ${TOKENS.border}`,
                      width: 28, height: 28,
                      '&:hover': { bgcolor: alpha(TOKENS.blue, 0.06), borderColor: TOKENS.blue },
                      '&:disabled': { opacity: 0.45 },
                    }}
                  >
                    <Refresh
                      sx={{
                        fontSize: 16,
                        animation: refreshing ? 'layout-spin 0.8s linear infinite' : 'none',
                        color: refreshing ? TOKENS.blue : TOKENS.textSub,
                      }}
                    />
                  </IconButton>
                </span>
              </Tooltip>
            )}
          </Box>
        </Box>
      </motion.div>

      {children}

      <style>{`
        @keyframes layout-spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </Box>
  );
});

DashboardLayout.displayName = 'DashboardLayout';
export default DashboardLayout;
