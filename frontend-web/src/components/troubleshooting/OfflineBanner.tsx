// Banner persistente de sin conexión — desaparece al reconectarse
import React, { useEffect, useState } from 'react';
import { Alert, Box, Button, Collapse, LinearProgress } from '@mui/material';
import WifiOffIcon from '@mui/icons-material/WifiOff';
import WifiIcon from '@mui/icons-material/Wifi';
import RefreshIcon from '@mui/icons-material/Refresh';

interface Props {
  onReconnect?: () => void;
}

export function OfflineBanner({ onReconnect }: Props) {
  const [offline,     setOffline]     = useState(!navigator.onLine);
  const [justBack,    setJustBack]    = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  useEffect(() => {
    const handleOffline = () => { setOffline(true);  setJustBack(false); };
    const handleOnline  = () => {
      setOffline(false);
      setJustBack(true);
      // Auto-hide the "back online" message after 4s
      setTimeout(() => setJustBack(false), 4000);
      onReconnect?.();
    };
    window.addEventListener('offline', handleOffline);
    window.addEventListener('online',  handleOnline);
    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online',  handleOnline);
    };
  }, [onReconnect]);

  const handleManualRetry = async () => {
    setReconnecting(true);
    try {
      await fetch('/api/health/', { method: 'GET', cache: 'no-store' });
      setOffline(false);
      setJustBack(true);
      setTimeout(() => setJustBack(false), 4000);
      onReconnect?.();
    } catch {
      // Still offline
    } finally {
      setReconnecting(false);
    }
  };

  return (
    <>
      {/* Offline banner */}
      <Collapse in={offline} unmountOnExit>
        <Box sx={{ position: 'sticky', top: 0, zIndex: 9999 }}>
          <Alert
            severity="error"
            icon={<WifiOffIcon />}
            action={
              <Button
                size="small"
                color="inherit"
                startIcon={<RefreshIcon />}
                onClick={handleManualRetry}
                disabled={reconnecting}
              >
                {reconnecting ? 'Conectando...' : 'Reintentar'}
              </Button>
            }
            sx={{ borderRadius: 0, py: 0.5 }}
          >
            Sin conexión a internet. Los datos mostrados pueden no estar actualizados.
          </Alert>
          {reconnecting && <LinearProgress color="error" />}
        </Box>
      </Collapse>

      {/* Back online notification */}
      <Collapse in={justBack && !offline} unmountOnExit>
        <Box sx={{ position: 'sticky', top: 0, zIndex: 9999 }}>
          <Alert
            severity="success"
            icon={<WifiIcon />}
            sx={{ borderRadius: 0, py: 0.5 }}
          >
            Conexión restaurada. Los datos se están actualizando.
          </Alert>
        </Box>
      </Collapse>
    </>
  );
}

export default OfflineBanner;
