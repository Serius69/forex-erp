import React, { memo, useState } from 'react';
import { Box, Typography, IconButton, Chip } from '@mui/material';
import { Warning, Error, Info, Close, ExpandMore, ExpandLess } from '@mui/icons-material';
import { motion, AnimatePresence } from 'framer-motion';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';

export interface AlertItem {
  id: string;
  message: string;
  severity: 'critical' | 'warning' | 'info';
  category?: string;
  time?: string;
}

interface AlertBannerProps {
  alerts: AlertItem[];
  loading?: boolean;
  maxVisible?: number;
}

const SEV: Record<AlertItem['severity'], { color: string; bg: string; border: string; icon: React.ReactNode; label: string }> = {
  critical: {
    color:  TOKENS.red,
    bg:     alpha(TOKENS.red, 0.07),
    border: alpha(TOKENS.red, 0.2),
    icon:   <Error sx={{ fontSize: 16 }} />,
    label:  'Crítico',
  },
  warning: {
    color:  TOKENS.amber,
    bg:     alpha(TOKENS.amber, 0.07),
    border: alpha(TOKENS.amber, 0.2),
    icon:   <Warning sx={{ fontSize: 16 }} />,
    label:  'Alerta',
  },
  info: {
    color:  TOKENS.blue,
    bg:     alpha(TOKENS.blue, 0.07),
    border: alpha(TOKENS.blue, 0.2),
    icon:   <Info sx={{ fontSize: 16 }} />,
    label:  'Info',
  },
};

const AlertBanner: React.FC<AlertBannerProps> = memo(({ alerts, maxVisible = 3 }) => {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [expanded, setExpanded]   = useState(false);

  const visible = alerts.filter(a => !dismissed.has(a.id));
  const shown   = expanded ? visible : visible.slice(0, maxVisible);
  const extra   = visible.length - maxVisible;

  if (visible.length === 0) return null;

  return (
    <Box sx={{ mb: 2.5 }}>
      <AnimatePresence initial={false}>
        {shown.map(alert => {
          const meta = SEV[alert.severity];
          return (
            <motion.div
              key={alert.id}
              initial={{ opacity: 0, height: 0, marginBottom: 0 }}
              animate={{ opacity: 1, height: 'auto', marginBottom: 6 }}
              exit={{ opacity: 0, height: 0, marginBottom: 0 }}
              transition={{ duration: 0.18 }}
            >
              <Box sx={{
                display: 'flex', alignItems: 'center', gap: 1.25,
                px: 2, py: 1.25, borderRadius: 2,
                bgcolor: meta.bg, border: `1px solid ${meta.border}`,
              }}>
                <Box sx={{ color: meta.color, display: 'flex', flexShrink: 0 }}>{meta.icon}</Box>
                <Typography variant="body2" sx={{ flex: 1, color: meta.color, fontWeight: 500 }}>
                  {alert.message}
                </Typography>
                {alert.time && (
                  <Typography variant="caption" sx={{ color: meta.color, opacity: 0.65, flexShrink: 0 }}>
                    {alert.time}
                  </Typography>
                )}
                <Chip
                  label={meta.label}
                  size="small"
                  sx={{
                    height: 18, fontSize: '0.6rem', fontWeight: 700, flexShrink: 0,
                    bgcolor: alpha(meta.color, 0.15), color: meta.color, border: 'none',
                  }}
                />
                <IconButton
                  size="small"
                  onClick={() => setDismissed(prev => new Set([...prev, alert.id]))}
                  sx={{ color: meta.color, p: 0.25, flexShrink: 0 }}
                >
                  <Close sx={{ fontSize: 14 }} />
                </IconButton>
              </Box>
            </motion.div>
          );
        })}
      </AnimatePresence>

      {extra > 0 && (
        <Box
          onClick={() => setExpanded(!expanded)}
          sx={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5,
            cursor: 'pointer', color: TOKENS.textSub,
            '&:hover': { color: TOKENS.text },
            transition: 'color 0.15s',
            mt: 0.5,
          }}
        >
          {expanded
            ? <ExpandLess sx={{ fontSize: 16 }} />
            : <ExpandMore sx={{ fontSize: 16 }} />}
          <Typography variant="caption" fontWeight={600}>
            {expanded ? 'Mostrar menos' : `Ver ${extra} alerta${extra > 1 ? 's' : ''} más`}
          </Typography>
        </Box>
      )}
    </Box>
  );
});

AlertBanner.displayName = 'AlertBanner';
export default AlertBanner;
