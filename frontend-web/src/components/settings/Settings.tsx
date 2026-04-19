// src/components/settings/Settings.tsx
import React, { useState } from 'react';
import {
  Box, Typography, Paper, Tabs, Tab, Grid,
  TextField, Button, Switch, FormControlLabel,
  Divider, Alert, Card, CardContent, Avatar,
  List, ListItem, ListItemText, ListItemSecondaryAction,
  Chip,
} from '@mui/material';
import {
  Person, Lock, Notifications, Business, Security,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { useAuth } from '../../contexts/AuthContext';
import { api } from '../../services/api';
import PinDialog from '../common/PinDialog';

const Settings: React.FC = () => {
  const [tab,          setTab]          = useState(0);
  const [pinOpen,      setPinOpen]      = useState(false);
  const [loading,      setLoading]      = useState(false);
  const [oldPassword,  setOldPassword]  = useState('');
  const [newPassword,  setNewPassword]  = useState('');
  const [confirmPass,  setConfirmPass]  = useState('');
  const [newPin,       setNewPin]       = useState('');
  const [twoFAData,    setTwoFAData]    = useState<any>(null);
  const [twoFAToken,   setTwoFAToken]   = useState('');
  const { user }                        = useAuth();
  const { enqueueSnackbar }             = useSnackbar();

  const handleChangePassword = async () => {
    if (newPassword !== confirmPass) {
      enqueueSnackbar('Las contraseñas no coinciden', { variant: 'error' });
      return;
    }
    if (newPassword.length < 8) {
      enqueueSnackbar('La contraseña debe tener al menos 8 caracteres', { variant: 'error' });
      return;
    }
    setLoading(true);
    try {
      await api.post('/users/change-password/', {
        old_password: oldPassword,
        new_password: newPassword,
      });
      enqueueSnackbar('Contraseña actualizada exitosamente', { variant: 'success' });
      setOldPassword(''); setNewPassword(''); setConfirmPass('');
    } catch (e: any) {
      enqueueSnackbar(e.response?.data?.error || 'Error al cambiar contraseña', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleSetPin = async (currentPin: string) => {
    try {
      await api.post('/users/set-pin/', { pin: newPin, current_pin: currentPin });
      enqueueSnackbar('PIN actualizado exitosamente', { variant: 'success' });
      setPinOpen(false);
      setNewPin('');
    } catch {
      enqueueSnackbar('Error al actualizar PIN', { variant: 'error' });
    }
  };

  const handleEnable2FA = async () => {
    try {
      const res = await api.post('/users/enable-two-factor/');
      setTwoFAData(res.data);
    } catch {
      enqueueSnackbar('Error al habilitar 2FA', { variant: 'error' });
    }
  };

  const handleConfirm2FA = async () => {
    try {
      await api.post('/users/confirm-two-factor/', { token: twoFAToken });
      enqueueSnackbar('2FA habilitado exitosamente', { variant: 'success' });
      setTwoFAData(null);
      setTwoFAToken('');
    } catch {
      enqueueSnackbar('Token inválido', { variant: 'error' });
    }
  };

  return (
    <Box>
      <Typography variant="h4" fontWeight="bold" mb={3}>Configuración</Typography>

      <Paper sx={{ mb: 3 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab icon={<Person />}        iconPosition="start" label="Perfil" />
          <Tab icon={<Lock />}          iconPosition="start" label="Seguridad" />
          <Tab icon={<Business />}      iconPosition="start" label="Sucursal" />
          <Tab icon={<Notifications />} iconPosition="start" label="Notificaciones" />
        </Tabs>
      </Paper>

      {/* ── Tab 0: Perfil ── */}
      {tab === 0 && (
        <Grid container spacing={3}>
          <Grid item xs={12} md={4}>
            <Card>
              <CardContent sx={{ textAlign: 'center', py: 4 }}>
                <Avatar sx={{ width: 80, height: 80, mx: 'auto', mb: 2, bgcolor: 'primary.main', fontSize: 32 }}>
                  {user?.first_name?.[0] ?? user?.username?.[0]}
                </Avatar>
                <Typography variant="h6">{user?.first_name} {user?.last_name}</Typography>
                <Typography color="text.secondary">@{user?.username}</Typography>
                <Chip
                  label={user?.role}
                  color={user?.role === 'ADMIN' ? 'error' : user?.role === 'SUPERVISOR' ? 'warning' : 'default'}
                  sx={{ mt: 1 }}
                />
                {user?.branch && (
                  <Typography variant="body2" color="text.secondary" mt={1}>
                    Sucursal: {(user as any).branch?.name}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={8}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" mb={2}>Información Personal</Typography>
              <Grid container spacing={2}>
                <Grid item xs={6}>
                  <TextField fullWidth label="Nombre" defaultValue={user?.first_name} disabled />
                </Grid>
                <Grid item xs={6}>
                  <TextField fullWidth label="Apellido" defaultValue={user?.last_name} disabled />
                </Grid>
                <Grid item xs={12}>
                  <TextField fullWidth label="Email" defaultValue={user?.email} disabled />
                </Grid>
                <Grid item xs={12}>
                  <TextField fullWidth label="Usuario" defaultValue={user?.username} disabled />
                </Grid>
              </Grid>
              <Alert severity="info" sx={{ mt: 2 }}>
                Para modificar datos personales contacta al administrador del sistema.
              </Alert>
            </Paper>
          </Grid>
        </Grid>
      )}

      {/* ── Tab 1: Seguridad ── */}
      {tab === 1 && (
        <Grid container spacing={3}>
          {/* Cambiar contraseña */}
          <Grid item xs={12} md={6}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" mb={2}>Cambiar Contraseña</Typography>
              <Grid container spacing={2}>
                <Grid item xs={12}>
                  <TextField fullWidth label="Contraseña Actual" type="password"
                    value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} />
                </Grid>
                <Grid item xs={12}>
                  <TextField fullWidth label="Nueva Contraseña" type="password"
                    value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
                </Grid>
                <Grid item xs={12}>
                  <TextField fullWidth label="Confirmar Contraseña" type="password"
                    value={confirmPass} onChange={(e) => setConfirmPass(e.target.value)}
                    error={confirmPass !== '' && confirmPass !== newPassword}
                    helperText={confirmPass !== '' && confirmPass !== newPassword ? 'No coincide' : ''} />
                </Grid>
                <Grid item xs={12}>
                  <Button fullWidth variant="contained" onClick={handleChangePassword}
                    disabled={loading || !oldPassword || !newPassword || newPassword !== confirmPass}>
                    Actualizar Contraseña
                  </Button>
                </Grid>
              </Grid>
            </Paper>
          </Grid>

          {/* PIN y 2FA */}
          <Grid item xs={12} md={6}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" mb={2}>PIN de Operaciones</Typography>
              <TextField fullWidth label="Nuevo PIN (4-6 dígitos)" type="password"
                value={newPin} onChange={(e) => setNewPin(e.target.value)}
                inputProps={{ maxLength: 6 }} sx={{ mb: 2 }} />
              <Button fullWidth variant="outlined"
                onClick={() => setPinOpen(true)}
                disabled={newPin.length < 4}>
                Actualizar PIN
              </Button>

              <Divider sx={{ my: 3 }} />

              <Typography variant="h6" mb={1}>Autenticación de Dos Factores</Typography>
              <Typography variant="body2" color="text.secondary" mb={2}>
                {user?.is_two_factor_enabled
                  ? '2FA está habilitado en tu cuenta.'
                  : 'Agrega una capa extra de seguridad a tu cuenta.'}
              </Typography>

              {!user?.is_two_factor_enabled && !twoFAData && (
                <Button variant="outlined" color="warning" startIcon={<Security />}
                  onClick={handleEnable2FA}>
                  Habilitar 2FA
                </Button>
              )}

              {twoFAData && (
                <Box>
                  <Alert severity="info" sx={{ mb: 2 }}>
                    Escanea el código QR con Google Authenticator o Authy
                  </Alert>
                  <Box textAlign="center" mb={2}>
                    <img
                      src={`data:image/png;base64,${twoFAData.qr_code}`}
                      alt="QR 2FA"
                      style={{ width: 200, height: 200 }}
                    />
                  </Box>
                  <TextField fullWidth label="Código de verificación" value={twoFAToken}
                    onChange={(e) => setTwoFAToken(e.target.value)} sx={{ mb: 2 }} />
                  <Button fullWidth variant="contained" onClick={handleConfirm2FA}
                    disabled={twoFAToken.length < 6}>
                    Confirmar 2FA
                  </Button>
                </Box>
              )}

              {user?.is_two_factor_enabled && (
                <Chip label="2FA Activo" color="success" icon={<Security />} />
              )}
            </Paper>
          </Grid>
        </Grid>
      )}

      {/* ── Tab 2: Sucursal ── */}
      {tab === 2 && (
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" mb={2}>Información de Sucursal</Typography>
          {(user as any)?.branch ? (
            <List>
              {[
                ['Nombre',    (user as any).branch.name],
                ['Código',    (user as any).branch.code],
                ['Dirección', (user as any).branch.address],
                ['Teléfono',  (user as any).branch.phone],
              ].map(([label, value]) => (
                <ListItem key={label} divider>
                  <ListItemText primary={label} />
                  <ListItemSecondaryAction>
                    <Typography>{value}</Typography>
                  </ListItemSecondaryAction>
                </ListItem>
              ))}
            </List>
          ) : (
            <Alert severity="warning">No tienes sucursal asignada.</Alert>
          )}
        </Paper>
      )}

      {/* ── Tab 3: Notificaciones ── */}
      {tab === 3 && (
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" mb={2}>Preferencias de Notificaciones</Typography>
          {[
            ['Alertas de inventario bajo',        true],
            ['Nuevas transacciones',              true],
            ['Reportes generados',                true],
            ['Alertas de seguridad',              true],
            ['Actualizaciones de tasas',          false],
            ['Resumen diario por email',          false],
          ].map(([label, defaultVal]) => (
            <Box key={label as string} display="flex" justifyContent="space-between"
              alignItems="center" py={1} borderBottom="1px solid" borderColor="divider">
              <Typography>{label as string}</Typography>
              <Switch defaultChecked={defaultVal as boolean} />
            </Box>
          ))}
          <Button variant="contained" sx={{ mt: 3 }}>
            Guardar Preferencias
          </Button>
        </Paper>
      )}

      <PinDialog
        open={pinOpen}
        onClose={() => setPinOpen(false)}
        onConfirm={handleSetPin}
        title="Confirmar con PIN actual"
      />
    </Box>
  );
};

export default Settings;