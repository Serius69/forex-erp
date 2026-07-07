// SystemStatusBar — indicador sutil de estado del sistema en el layout
import React, { useEffect, useRef, useState } from 'react';
import { Box, Chip, Tooltip, Typography } from '@mui/material';
import CircleIcon from '@mui/icons-material/Circle';
import { useWebSocket } from '../../contexts/WebSocketContext';

function formatAge(ms: number): string {
  if (ms < 60_000)  return `${Math.floor(ms / 1000)}s`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
  return `${Math.floor(ms / 3_600_000)}h`;
}

type DotColor = 'success' | 'warning' | 'error';

export function SystemStatusBar() {
  const { wsStatus, isRatesStale, ratesAge } = useWebSocket();
  const [_tick, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Refresh the age display every 10 seconds
  useEffect(() => {
    intervalRef.current = setInterval(() => setTick((t) => t + 1), 10_000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  const dotColor: DotColor =
    wsStatus === 'connected'    ? 'success' :
    wsStatus === 'reconnecting' ? 'warning' :
    wsStatus === 'polling'      ? 'warning' : 'error';

  const dotSx = {
    success: { color: '#22C55E' },
    warning: { color: '#F59E0B' },
    error:   { color: '#EF4444' },
  }[dotColor];

  const wsLabel =
    wsStatus === 'connected'    ? 'Tiempo real' :
    wsStatus === 'reconnecting' ? 'Reconectando...' :
    wsStatus === 'polling'      ? 'Modo manual' : 'Desconectado';

  const wsTooltip =
    wsStatus === 'connected'    ? 'WebSocket conectado — datos en tiempo real' :
    wsStatus === 'reconnecting' ? 'Reconectando al servidor...' :
    wsStatus === 'polling'      ? 'Sin WebSocket — actualizando cada 30 segundos' :
                                   'Sin conexión al servidor';

  return (
    <Box
      display="flex"
      alignItems="center"
      gap={1.5}
      sx={{ px: 1.5, py: 0.5, bgcolor: 'transparent' }}
    >
      {/* WS status dot */}
      <Tooltip title={wsTooltip} arrow placement="bottom">
        <Chip
          size="small"
          icon={<CircleIcon sx={{ fontSize: '0.6rem !important', ...dotSx }} />}
          label={wsLabel}
          sx={{
            fontSize: '0.68rem',
            height: 22,
            bgcolor: 'rgba(255,255,255,0.06)',
            color: 'rgba(255,255,255,0.6)',
            border: '1px solid rgba(255,255,255,0.08)',
            cursor: 'default',
            '& .MuiChip-icon': { ml: '6px' },
          }}
        />
      </Tooltip>

      {/* Stale data badge */}
      {isRatesStale && ratesAge > 0 && (
        <Tooltip title={`Última actualización hace ${formatAge(ratesAge)}`} arrow placement="bottom">
          <Chip
            size="small"
            label={`Tasas: ${formatAge(ratesAge)} atrás`}
            sx={{
              fontSize: '0.68rem',
              height: 22,
              bgcolor: 'rgba(245,158,11,0.12)',
              color: '#F59E0B',
              border: '1px solid rgba(245,158,11,0.25)',
              cursor: 'default',
            }}
          />
        </Tooltip>
      )}
    </Box>
  );
}

export default SystemStatusBar;
