// Error inline a nivel de sección — no interrumpe el resto de la página
import React from 'react';
import { Alert, Box, Button, Typography } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';

export type SectionErrorType = 'empty' | 'load_failed' | 'stale_data' | 'partial';

interface Props {
  type?:       SectionErrorType;
  message?:    string;
  onRetry?:    () => void;
  compact?:    boolean;
  entityName?: string;
}

const typeConfig: Record<SectionErrorType, { severity: 'error' | 'warning' | 'info'; label: string; icon: React.ReactNode }> = {
  load_failed: { severity: 'error',   label: 'Error al cargar',          icon: null },
  stale_data:  { severity: 'warning', label: 'Datos desactualizados',     icon: <WarningAmberIcon fontSize="small" /> },
  partial:     { severity: 'warning', label: 'Datos incompletos',         icon: <WarningAmberIcon fontSize="small" /> },
  empty:       { severity: 'info',    label: 'Sin datos disponibles',     icon: <InfoOutlinedIcon fontSize="small" /> },
};

export function SectionError({ type = 'load_failed', message, onRetry, compact = false, entityName }: Props) {
  const cfg = typeConfig[type];

  const defaultMessages: Record<SectionErrorType, string> = {
    load_failed: `No se pudieron cargar ${entityName ?? 'los datos'}.`,
    stale_data:  `Los datos de ${entityName ?? 'esta sección'} pueden estar desactualizados.`,
    partial:     `Solo se cargaron algunos datos de ${entityName ?? 'esta sección'}.`,
    empty:       `No hay ${entityName ?? 'datos'} para mostrar.`,
  };

  const text = message ?? defaultMessages[type];

  if (compact) {
    return (
      <Alert
        severity={cfg.severity}
        icon={cfg.icon ?? undefined}
        action={
          onRetry ? (
            <Button color="inherit" size="small" startIcon={<RefreshIcon fontSize="small" />} onClick={onRetry}>
              Reintentar
            </Button>
          ) : undefined
        }
        sx={{ borderRadius: 1, py: 0.5 }}
      >
        {text}
      </Alert>
    );
  }

  return (
    <Box
      display="flex"
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      py={4}
      px={2}
      sx={{ border: '1px dashed rgba(255,255,255,0.1)', borderRadius: 2, minHeight: 120 }}
    >
      {cfg.icon && <Box sx={{ mb: 1, opacity: 0.6 }}>{cfg.icon}</Box>}
      <Typography variant="body2" color="text.secondary" textAlign="center" mb={onRetry ? 2 : 0}>
        {text}
      </Typography>
      {onRetry && (
        <Button size="small" startIcon={<RefreshIcon fontSize="small" />} onClick={onRetry} variant="outlined" sx={{ borderColor: 'rgba(255,255,255,0.2)', color: 'white' }}>
          Reintentar
        </Button>
      )}
    </Box>
  );
}

export default SectionError;
