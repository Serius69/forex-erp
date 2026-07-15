import React, { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, Typography, Box,
} from '@mui/material';
import { LockOutlined } from '@mui/icons-material';

interface PinDialogProps {
  open:      boolean;
  onClose:   () => void;
  onConfirm?: (pin: string) => void;
  onSubmit?:  (pin: string) => void;  // alias para compatibilidad
  title?:    string;
  message?:  string;
}

const PinDialog: React.FC<PinDialogProps> = ({
  open, onClose, onConfirm, onSubmit,
  title = 'Confirmar con PIN',
}) => {
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');

  const handleConfirm = () => {
    if (pin.length < 4) { setError('El PIN debe tener al menos 4 dígitos'); return; }
    const handler = onConfirm ?? onSubmit;
    handler?.(pin);
    setPin(''); setError('');
    };

  const handleClose = () => {
    setPin('');
    setError('');
    onClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="xs" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <LockOutlined color="primary" />
          {title}
        </Box>
      </DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" mb={2}>
          Ingresa tu PIN para confirmar la operación
        </Typography>
        <TextField
          fullWidth
          type="password"
          label="PIN"
          value={pin}
          onChange={(e) => setPin(e.target.value)}
          error={!!error}
          helperText={error}
          inputProps={{ maxLength: 6, inputMode: 'numeric', pattern: '[0-9]*' }}
          onKeyPress={(e) => e.key === 'Enter' && handleConfirm()}
          autoFocus
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancelar</Button>
        <Button onClick={handleConfirm} variant="contained">
          Confirmar
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default PinDialog;
