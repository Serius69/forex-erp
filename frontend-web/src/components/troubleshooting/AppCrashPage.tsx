// Página de fallo total — renderizada por GlobalErrorBoundary
import React from 'react';
import { Box, Button, Paper, Typography } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import HomeIcon from '@mui/icons-material/Home';
import { CopyableErrorId, SupportContact } from './TroubleshootingUtils';

interface Props {
  errorId: string;
  onRetry?: () => void;
}

export function AppCrashPage({ errorId, onRetry }: Props) {
  return (
    <Box
      display="flex"
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      minHeight="100vh"
      sx={{ bgcolor: '#0F172A', p: 3 }}
    >
      <Paper
        elevation={4}
        sx={{
          maxWidth: 480,
          width: '100%',
          p: 4,
          bgcolor: '#1E293B',
          borderRadius: 3,
          textAlign: 'center',
          border: '1px solid rgba(239,68,68,0.25)',
        }}
      >
        {/* Icon */}
        <Box sx={{ fontSize: 56, lineHeight: 1, mb: 2 }}>⚠️</Box>

        <Typography variant="h5" fontWeight={700} color="white" gutterBottom>
          Algo salió mal en Kapitalya
        </Typography>

        <Typography variant="body2" color="text.secondary" mb={3}>
          La aplicación encontró un error inesperado. Tus datos están seguros.
          Puedes intentar recargar o volver al inicio.
        </Typography>

        <Box display="flex" flexDirection="column" gap={1.5} mb={3}>
          <Button
            variant="contained"
            startIcon={<RefreshIcon />}
            onClick={onRetry ?? (() => window.location.reload())}
            fullWidth
            sx={{ bgcolor: '#2563EB', '&:hover': { bgcolor: '#1D4ED8' } }}
          >
            Recargar la aplicación
          </Button>
          <Button
            variant="outlined"
            startIcon={<HomeIcon />}
            onClick={() => { window.location.href = '/dashboard'; }}
            fullWidth
            sx={{ borderColor: 'rgba(255,255,255,0.2)', color: 'white' }}
          >
            Ir al inicio
          </Button>
        </Box>

        <CopyableErrorId errorId={errorId} />
        <SupportContact />
      </Paper>
    </Box>
  );
}

export default AppCrashPage;
