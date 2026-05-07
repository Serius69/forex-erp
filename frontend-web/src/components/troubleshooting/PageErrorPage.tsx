// Página de error a nivel de ruta/página — renderizada por PageErrorBoundary
import React from 'react';
import { Box, Button, Paper, Typography } from '@mui/material';
import WifiOffIcon from '@mui/icons-material/WifiOff';
import LockIcon from '@mui/icons-material/Lock';
import SearchOffIcon from '@mui/icons-material/SearchOff';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import TimerOffIcon from '@mui/icons-material/TimerOff';
import BuildIcon from '@mui/icons-material/Build';
import LoginIcon from '@mui/icons-material/Login';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import RefreshIcon from '@mui/icons-material/Refresh';
import { CopyableErrorId, SupportContact } from './TroubleshootingUtils';

export type PageErrorType =
  | 'not_found'
  | 'forbidden'
  | 'server_error'
  | 'network_error'
  | 'timeout'
  | 'session_expired'
  | 'maintenance';

interface PageConfig {
  icon:    React.ReactNode;
  color:   string;
  title:   string;
  desc:    string;
  actions: { label: string; icon: React.ReactNode; action: () => void; variant: 'contained' | 'outlined' }[];
}

function getConfig(type: PageErrorType, errorId: string, onRetry?: () => void, maintenanceEta?: string): PageConfig {
  const blue  = '#2563EB';
  const back  = () => window.history.length > 1 ? window.history.back() : (window.location.href = '/dashboard');
  const home  = () => { window.location.href = '/dashboard'; };
  const login = () => { window.location.href = '/login'; };
  const retry = onRetry ?? (() => window.location.reload());

  const configs: Record<PageErrorType, PageConfig> = {
    not_found: {
      icon: <SearchOffIcon sx={{ fontSize: 48, color: '#94A3B8' }} />,
      color: '#94A3B8',
      title: 'Página no encontrada',
      desc: 'La página que buscas no existe o fue movida.',
      actions: [
        { label: 'Ir al inicio',   icon: <ArrowBackIcon />, action: home,  variant: 'contained' },
        { label: 'Ir atrás',       icon: <ArrowBackIcon />, action: back,  variant: 'outlined'  },
      ],
    },
    forbidden: {
      icon: <LockIcon sx={{ fontSize: 48, color: '#F59E0B' }} />,
      color: '#F59E0B',
      title: 'Acceso denegado',
      desc: 'No tienes permisos para ver esta página. Contacta a tu administrador.',
      actions: [
        { label: 'Ir al inicio',       icon: <ArrowBackIcon />, action: home,  variant: 'contained' },
        { label: 'Cambiar cuenta',     icon: <LoginIcon />,     action: login, variant: 'outlined'  },
      ],
    },
    server_error: {
      icon: <ErrorOutlineIcon sx={{ fontSize: 48, color: '#EF4444' }} />,
      color: '#EF4444',
      title: 'Error del servidor',
      desc: 'Ocurrió un problema en el servidor. El equipo técnico fue notificado.',
      actions: [
        { label: 'Reintentar',     icon: <RefreshIcon />,   action: retry, variant: 'contained' },
        { label: 'Ir al inicio',   icon: <ArrowBackIcon />, action: home,  variant: 'outlined'  },
      ],
    },
    network_error: {
      icon: <WifiOffIcon sx={{ fontSize: 48, color: '#6366F1' }} />,
      color: '#6366F1',
      title: 'Sin conexión',
      desc: 'No se puede conectar al servidor. Verifica tu conexión a internet.',
      actions: [
        { label: 'Reintentar',         icon: <RefreshIcon />,   action: retry, variant: 'contained' },
        { label: 'Ir al inicio',       icon: <ArrowBackIcon />, action: home,  variant: 'outlined'  },
      ],
    },
    timeout: {
      icon: <TimerOffIcon sx={{ fontSize: 48, color: '#F59E0B' }} />,
      color: '#F59E0B',
      title: 'Tiempo de espera agotado',
      desc: 'La solicitud tardó demasiado. Puede ser un problema temporal.',
      actions: [
        { label: 'Reintentar',   icon: <RefreshIcon />,   action: retry, variant: 'contained' },
        { label: 'Ir al inicio', icon: <ArrowBackIcon />, action: home,  variant: 'outlined'  },
      ],
    },
    session_expired: {
      icon: <LoginIcon sx={{ fontSize: 48, color: '#2563EB' }} />,
      color: '#2563EB',
      title: 'Sesión expirada',
      desc: 'Tu sesión ha expirado por seguridad. Inicia sesión nuevamente.',
      actions: [
        { label: 'Iniciar sesión', icon: <LoginIcon />, action: login, variant: 'contained' },
      ],
    },
    maintenance: {
      icon: <BuildIcon sx={{ fontSize: 48, color: '#10B981' }} />,
      color: '#10B981',
      title: 'En mantenimiento',
      desc: maintenanceEta
        ? `El sistema estará disponible aproximadamente a las ${maintenanceEta}.`
        : 'El sistema está en mantenimiento. Vuelve pronto.',
      actions: [
        { label: 'Reintentar', icon: <RefreshIcon />, action: retry, variant: 'contained' },
      ],
    },
  };

  return configs[type] ?? configs.server_error;
}

interface Props {
  type:            PageErrorType;
  errorId?:        string;
  onRetry?:        () => void;
  maintenanceEta?: string;
}

export function PageErrorPage({ type, errorId = makeId(), onRetry, maintenanceEta }: Props) {
  const cfg = getConfig(type, errorId, onRetry, maintenanceEta);

  return (
    <Box
      display="flex"
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      minHeight="80vh"
      sx={{ p: 3 }}
    >
      <Paper
        elevation={2}
        sx={{
          maxWidth: 440,
          width: '100%',
          p: 4,
          bgcolor: '#1E293B',
          borderRadius: 3,
          textAlign: 'center',
          border: `1px solid ${cfg.color}33`,
        }}
      >
        <Box mb={2}>{cfg.icon}</Box>

        <Typography variant="h6" fontWeight={700} color="white" gutterBottom>
          {cfg.title}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={3}>
          {cfg.desc}
        </Typography>

        <Box display="flex" flexDirection="column" gap={1.5} mb={2}>
          {cfg.actions.map((a) => (
            <Button
              key={a.label}
              variant={a.variant}
              startIcon={a.icon}
              onClick={a.action}
              fullWidth
              sx={a.variant === 'contained' ? { bgcolor: cfg.color, '&:hover': { filter: 'brightness(0.9)' } } : { borderColor: 'rgba(255,255,255,0.2)', color: 'white' }}
            >
              {a.label}
            </Button>
          ))}
        </Box>

        <CopyableErrorId errorId={errorId} />
        <SupportContact />
      </Paper>
    </Box>
  );
}

function makeId() {
  return `PAGE-${Date.now().toString(36).toUpperCase()}`;
}

export default PageErrorPage;
