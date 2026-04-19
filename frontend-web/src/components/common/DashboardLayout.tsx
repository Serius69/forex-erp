import React, { memo } from 'react';
import { Box, Typography, IconButton, Tooltip } from '@mui/material';
import { Refresh } from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';

interface DashboardLayoutProps {
  title: string;
  subtitle?: string;
  badge?: string;
  badgeColor?: string;
  onRefresh?: () => void;
  refreshing?: boolean;
  filters?: React.ReactNode;
  children: React.ReactNode;
}

const DashboardLayout: React.FC<DashboardLayoutProps> = memo(({
  title, subtitle, badge, badgeColor = TOKENS.green,
  onRefresh, refreshing = false, filters, children,
}) => (
  <Box>
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 3 }}>
      <Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Typography variant="h4" fontWeight={800}>{title}</Typography>
          {badge && (
            <Box sx={{
              px: 1, py: 0.2, borderRadius: '5px',
              bgcolor: alpha(badgeColor, 0.12),
              border: `1px solid ${alpha(badgeColor, 0.22)}`,
            }}>
              <Typography variant="overline" sx={{
                color: badgeColor, fontWeight: 800, fontSize: '0.6rem', lineHeight: 1,
              }}>
                {badge}
              </Typography>
            </Box>
          )}
        </Box>
        {subtitle && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
            {subtitle}
          </Typography>
        )}
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
        {filters}
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
                  '&:hover': { bgcolor: alpha(TOKENS.blue, 0.05) },
                  '&:disabled': { opacity: 0.5 },
                }}
              >
                <Refresh
                  fontSize="small"
                  sx={{ animation: refreshing ? 'layout-spin 0.8s linear infinite' : 'none' }}
                />
              </IconButton>
            </span>
          </Tooltip>
        )}
      </Box>
    </Box>

    {children}

    <style>{`
      @keyframes layout-spin {
        from { transform: rotate(0deg) }
        to   { transform: rotate(360deg) }
      }
    `}</style>
  </Box>
));

DashboardLayout.displayName = 'DashboardLayout';
export default DashboardLayout;
