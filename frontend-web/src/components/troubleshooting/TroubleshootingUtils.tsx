// Utilidades compartidas para componentes de troubleshooting
import React from 'react';
import { Box, Button, Chip, Typography } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { useSnackbar } from 'notistack';

export function CopyableErrorId({ errorId }: { errorId: string }) {
  const { enqueueSnackbar } = useSnackbar();
  const copy = () => {
    navigator.clipboard?.writeText(errorId).then(() =>
      enqueueSnackbar('Código copiado', { variant: 'success', autoHideDuration: 2000 })
    ).catch(() => {});
  };
  return (
    <Box display="flex" alignItems="center" gap={1} mt={1}>
      <Chip
        label={errorId}
        size="small"
        sx={{ fontFamily: 'monospace', fontSize: '0.7rem', bgcolor: 'rgba(255,255,255,0.08)' }}
      />
      <Button size="small" startIcon={<ContentCopyIcon fontSize="small" />} onClick={copy} sx={{ fontSize: '0.7rem' }}>
        Copiar código
      </Button>
    </Box>
  );
}

export function SupportContact() {
  return (
    <Typography variant="caption" color="text.secondary" display="block" mt={1}>
      ¿Persiste el problema? Contacta a soporte con el código de error.
    </Typography>
  );
}
