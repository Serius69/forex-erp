// src/components/rates/WebSocketStatus.tsx
import React from 'react';
import { Box, Chip, Tooltip, Typography } from '@mui/material';
import { Wifi, WifiOff, SignalWifi4Bar } from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { formatDistanceToNow, parseISO } from 'date-fns';
import { es } from 'date-fns/locale';

interface WebSocketStatusProps {
  connected:   boolean;
  lastUpdate?:  string | null;
  /** Si true, muestra también el tiempo desde la última actualización */
  showLastUpdate?: boolean;
  size?: 'small' | 'medium';
}

const WebSocketStatus: React.FC<WebSocketStatusProps> = ({
  connected, lastUpdate, showLastUpdate = true, size = 'small',
}) => {
  const lastUpdateStr = React.useMemo(() => {
    if (!lastUpdate) return null;
    try {
      return formatDistanceToNow(parseISO(lastUpdate), { locale: es, addSuffix: true });
    } catch {
      return null;
    }
  }, [lastUpdate]);

  const tooltipText = connected
    ? `WebSocket conectado${lastUpdateStr ? ` · Última actualización ${lastUpdateStr}` : ''}`
    : 'WebSocket desconectado — reconectando automáticamente…';

  return (
    <Tooltip title={tooltipText} arrow placement="bottom">
      <Box
        sx={{
          display:     'inline-flex',
          alignItems:  'center',
          gap:         0.75,
          px:          1.25,
          py:          0.4,
          borderRadius: '20px',
          bgcolor:     connected ? alpha('#4caf50', 0.1) : alpha('#ff9800', 0.1),
          border:      '1px solid',
          borderColor: connected ? alpha('#4caf50', 0.35) : alpha('#ff9800', 0.35),
          cursor:      'help',
          transition:  'all 0.3s ease',
        }}
      >
        {/* Dot animado */}
        <Box
          sx={{
            width:    7,
            height:   7,
            borderRadius: '50%',
            bgcolor:  connected ? '#4caf50' : '#ff9800',
            flexShrink: 0,
            ...(connected ? {
              boxShadow: '0 0 0 0 rgba(76,175,80,0.4)',
              animation: 'ws-pulse 2s ease-in-out infinite',
            } : {}),
          }}
        />
        <Typography
          variant="caption"
          fontWeight={700}
          sx={{
            color:    connected ? '#2e7d32' : '#e65100',
            fontSize: size === 'small' ? '0.65rem' : '0.72rem',
            lineHeight: 1,
          }}
        >
          {connected ? 'EN VIVO' : 'RECONECTANDO'}
        </Typography>

        {showLastUpdate && lastUpdateStr && (
          <Typography
            variant="caption"
            sx={{
              color:    'text.disabled',
              fontSize: '0.6rem',
              lineHeight: 1,
              borderLeft: '1px solid',
              borderColor: 'divider',
              pl: 0.75,
              ml: 0.25,
            }}
          >
            {lastUpdateStr}
          </Typography>
        )}

        <style>{`
          @keyframes ws-pulse {
            0%   { box-shadow: 0 0 0 0 rgba(76,175,80,0.5); }
            70%  { box-shadow: 0 0 0 5px rgba(76,175,80,0); }
            100% { box-shadow: 0 0 0 0 rgba(76,175,80,0); }
          }
        `}</style>
      </Box>
    </Tooltip>
  );
};

export default WebSocketStatus;
