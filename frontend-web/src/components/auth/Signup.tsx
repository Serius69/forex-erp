// src/components/auth/Signup.tsx
import React, { useState, useCallback } from 'react';
import {
  Box, TextField, Button, Typography, Alert,
  CircularProgress, InputAdornment, IconButton, Divider, LinearProgress,
} from '@mui/material';
import { Visibility, VisibilityOff, CheckCircleOutline, RadioButtonUnchecked } from '@mui/icons-material';
import { Link as RouterLink } from 'react-router-dom';
import { GoogleLogin } from '@react-oauth/google';
import { useAuth } from '../../contexts/AuthContext';
import { TOKENS } from '../../styles/theme';

interface PasswordRule { label: string; test: (p: string) => boolean; }
const PASSWORD_RULES: PasswordRule[] = [
  { label: 'Mínimo 8 caracteres',   test: p => p.length >= 8 },
  { label: 'Una letra mayúscula',   test: p => /[A-Z]/.test(p) },
  { label: 'Un número',             test: p => /\d/.test(p) },
  { label: 'Un símbolo especial',   test: p => /[!@#$%^&*()\-_=+[\]{};:'",.<>?/\\|`~]/.test(p) },
];

function passwordStrength(password: string): number {
  return PASSWORD_RULES.filter(r => r.test(password)).length;
}

const STRENGTH_COLOR = ['', '#f44336', '#ff9800', '#ffeb3b', '#4caf50'];
const STRENGTH_LABEL = ['', 'Muy débil', 'Débil', 'Regular', 'Fuerte'];

const Signup: React.FC = () => {
  const { signup, loginGoogle } = useAuth();

  const [form, setForm] = useState({
    email:            '',
    first_name:       '',
    last_name:        '',
    password:         '',
    password_confirm: '',
  });
  const [showPass,    setShowPass]    = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState('');
  const [success,     setSuccess]     = useState('');

  const strength = passwordStrength(form.password);
  const googleEnabled = Boolean(import.meta.env.VITE_GOOGLE_CLIENT_ID);

  const set = (field: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm(prev => ({ ...prev, [field]: e.target.value }));

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!form.email || !form.password || !form.password_confirm) {
      setError('Completa todos los campos obligatorios.');
      return;
    }
    if (form.password !== form.password_confirm) {
      setError('Las contraseñas no coinciden.');
      return;
    }
    if (strength < 4) {
      setError('La contraseña no cumple los requisitos de seguridad.');
      return;
    }

    setLoading(true);
    try {
      const pendingMsg = await signup(form);
      if (pendingMsg) setSuccess(pendingMsg);
    } catch (err: any) {
      const detail = err?.response?.data;
      if (typeof detail === 'object' && detail !== null) {
        const messages = Object.values(detail).flat().join(' ');
        setError(messages || 'Error al crear la cuenta.');
      } else {
        setError('Error al crear la cuenta. Intenta de nuevo.');
      }
    } finally {
      setLoading(false);
    }
  }, [form, strength, signup]);

  const handleGoogleSuccess = useCallback(async (credentialResponse: any) => {
    const credential = credentialResponse?.credential;
    if (!credential) { setError('Google no devolvió un token válido.'); return; }
    setLoading(true);
    setError('');
    try {
      const pendingMsg = await loginGoogle(credential);
      if (pendingMsg) setSuccess(pendingMsg);
    } catch {
      setError('Error al registrarse con Google.');
    } finally {
      setLoading(false);
    }
  }, [loginGoogle]);

  const handleGoogleError = useCallback(() => {
    setError('No se pudo iniciar sesión con Google.');
  }, []);

  return (
    <Box sx={{
      minHeight: '100vh',
      '@supports (min-height: 100dvh)': { minHeight: '100dvh' },
      display: 'grid',
      gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
      bgcolor: TOKENS.bg,
    }}>
      {/* ── Left panel ── */}
      <Box sx={{
        display: { xs: 'none', md: 'flex' },
        flexDirection: 'column',
        justifyContent: 'space-between',
        bgcolor: TOKENS.navy,
        p: 5,
        position: 'relative',
        overflow: 'hidden',
      }}>
        <Box sx={{
          position: 'absolute', inset: 0,
          backgroundImage: `radial-gradient(circle at 20% 50%, ${TOKENS.blue}22 0%, transparent 60%),
                            radial-gradient(circle at 80% 20%, ${TOKENS.green}18 0%, transparent 50%)`,
        }} />
        <Box sx={{ position: 'relative', zIndex: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
            <Box sx={{ width: 40, height: 40, borderRadius: '10px', bgcolor: TOKENS.blue, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography sx={{ fontSize: 20, lineHeight: 1 }}>₿</Typography>
            </Box>
            <Typography variant="h5" fontWeight={800} color="white">Kapitalya</Typography>
          </Box>
          <Typography variant="caption" sx={{ color: TOKENS.muted, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            Sistema de Gestión Financiera
          </Typography>
        </Box>
        <Box sx={{ position: 'relative', zIndex: 1 }}>
          <Typography variant="h2" fontWeight={800} color="white" mb={2} sx={{ lineHeight: 1.2 }}>
            Únete a<br />
            <Box component="span" sx={{ color: TOKENS.blueMid }}>Kapitalya</Box><br />
            hoy mismo.
          </Typography>
          <Typography sx={{ color: TOKENS.muted, lineHeight: 1.7, maxWidth: 360 }}>
            Crea tu cuenta y empieza a gestionar divisas, tasas y reportes ASFI con precisión institucional.
          </Typography>
        </Box>
        <Box sx={{ position: 'relative', zIndex: 1, display: 'flex', gap: 3 }}>
          {[{ label: 'Seguridad', value: 'JWT' }, { label: 'Cumplimiento', value: 'ASFI' }, { label: 'Cifrado', value: 'AES-256' }].map(s => (
            <Box key={s.label}>
              <Typography variant="h5" fontWeight={800} color="white">{s.value}</Typography>
              <Typography variant="caption" sx={{ color: TOKENS.muted }}>{s.label}</Typography>
            </Box>
          ))}
        </Box>
      </Box>

      {/* ── Right panel: form ── */}
      <Box sx={{
        display: 'flex', flexDirection: 'column',
        justifyContent: 'center', alignItems: 'center',
        p: { xs: 3, sm: 5 },
        bgcolor: TOKENS.bg,
        overflowY: 'auto',
      }}>
        <Box sx={{ width: '100%', maxWidth: 420 }}>
          {/* Mobile logo */}
          <Box sx={{ display: { xs: 'flex', md: 'none' }, alignItems: 'center', gap: 1.5, mb: 4 }}>
            <Box sx={{ width: 36, height: 36, borderRadius: '9px', bgcolor: TOKENS.blue, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography sx={{ fontSize: 18, lineHeight: 1 }}>₿</Typography>
            </Box>
            <Typography variant="h6" fontWeight={800}>Kapitalya</Typography>
          </Box>

          <Typography variant="h4" fontWeight={800} mb={0.5}>Crear cuenta</Typography>
          <Typography variant="body2" color="text.secondary" mb={3}>
            Tu rol inicial será <strong>Cajero</strong>. Un administrador puede cambiarlo.
          </Typography>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
              {error}
            </Alert>
          )}

          {success && (
            <Alert severity="success" sx={{ mb: 2 }}>
              {success}
            </Alert>
          )}

          {/* Google sign-up */}
          {googleEnabled && (
            <>
              <Box sx={{ mb: 2 }}>
                <GoogleLogin
                  onSuccess={handleGoogleSuccess}
                  onError={handleGoogleError}
                  width="100%"
                  text="signup_with"
                  shape="rectangular"
                  logo_alignment="left"
                />
              </Box>
              <Divider sx={{ my: 2 }}>
                <Typography variant="caption" color="text.secondary">O con email</Typography>
              </Divider>
            </>
          )}

          <form onSubmit={handleSubmit} noValidate>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5 }}>
                <Box>
                  <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 0.75, display: 'block', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Nombre
                  </Typography>
                  <TextField fullWidth placeholder="Juan" value={form.first_name} onChange={set('first_name')} disabled={loading} />
                </Box>
                <Box>
                  <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 0.75, display: 'block', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Apellido
                  </Typography>
                  <TextField fullWidth placeholder="Pérez" value={form.last_name} onChange={set('last_name')} disabled={loading} />
                </Box>
              </Box>

              <Box>
                <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 0.75, display: 'block', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Email <Box component="span" sx={{ color: 'error.main' }}>*</Box>
                </Typography>
                <TextField
                  fullWidth
                  type="email"
                  placeholder="usuario@empresa.com"
                  value={form.email}
                  onChange={set('email')}
                  autoComplete="email"
                  disabled={loading}
                  required
                />
              </Box>

              <Box>
                <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 0.75, display: 'block', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Contraseña <Box component="span" sx={{ color: 'error.main' }}>*</Box>
                </Typography>
                <TextField
                  fullWidth
                  type={showPass ? 'text' : 'password'}
                  placeholder="••••••••"
                  value={form.password}
                  onChange={set('password')}
                  autoComplete="new-password"
                  disabled={loading}
                  required
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton onClick={() => setShowPass(p => !p)} edge="end" size="small" tabIndex={-1} sx={{ color: 'text.secondary' }}>
                          {showPass ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                        </IconButton>
                      </InputAdornment>
                    ),
                  }}
                />
                {form.password && (
                  <Box sx={{ mt: 1 }}>
                    <LinearProgress
                      variant="determinate"
                      value={strength * 25}
                      sx={{
                        borderRadius: 4, height: 4, mb: 0.75,
                        bgcolor: `${TOKENS.border}`,
                        '& .MuiLinearProgress-bar': { bgcolor: STRENGTH_COLOR[strength] },
                      }}
                    />
                    <Typography variant="caption" sx={{ color: STRENGTH_COLOR[strength], fontWeight: 600 }}>
                      {STRENGTH_LABEL[strength]}
                    </Typography>
                    <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 0.4 }}>
                      {PASSWORD_RULES.map(rule => (
                        <Box key={rule.label} sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                          {rule.test(form.password)
                            ? <CheckCircleOutline sx={{ fontSize: 14, color: '#4caf50' }} />
                            : <RadioButtonUnchecked sx={{ fontSize: 14, color: 'text.disabled' }} />
                          }
                          <Typography variant="caption" sx={{ color: rule.test(form.password) ? '#4caf50' : 'text.secondary' }}>
                            {rule.label}
                          </Typography>
                        </Box>
                      ))}
                    </Box>
                  </Box>
                )}
              </Box>

              <Box>
                <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 0.75, display: 'block', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Confirmar contraseña <Box component="span" sx={{ color: 'error.main' }}>*</Box>
                </Typography>
                <TextField
                  fullWidth
                  type={showConfirm ? 'text' : 'password'}
                  placeholder="••••••••"
                  value={form.password_confirm}
                  onChange={set('password_confirm')}
                  autoComplete="new-password"
                  disabled={loading}
                  required
                  error={!!form.password_confirm && form.password !== form.password_confirm}
                  helperText={form.password_confirm && form.password !== form.password_confirm ? 'Las contraseñas no coinciden' : ''}
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton onClick={() => setShowConfirm(p => !p)} edge="end" size="small" tabIndex={-1} sx={{ color: 'text.secondary' }}>
                          {showConfirm ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                        </IconButton>
                      </InputAdornment>
                    ),
                  }}
                />
              </Box>

              <Button
                fullWidth
                type="submit"
                variant="contained"
                size="large"
                disabled={loading || !form.email || !form.password || !form.password_confirm}
                sx={{
                  mt: 1, py: 1.5, fontSize: '1rem', fontWeight: 700, borderRadius: '10px',
                  background: loading ? undefined : `linear-gradient(135deg, ${TOKENS.blue} 0%, ${TOKENS.blueMid} 100%)`,
                  boxShadow: `0 4px 14px ${TOKENS.blue}40`,
                  '&:hover': { boxShadow: `0 6px 20px ${TOKENS.blue}50` },
                  '&:disabled': { opacity: 0.7 },
                }}
              >
                {loading
                  ? <><CircularProgress size={18} sx={{ color: 'white', mr: 1 }} /> Creando cuenta…</>
                  : 'Crear cuenta'
                }
              </Button>
            </Box>
          </form>

          <Typography variant="body2" color="text.secondary" textAlign="center" mt={3}>
            ¿Ya tienes cuenta?{' '}
            <RouterLink to="/login" style={{ color: TOKENS.blue, fontWeight: 600, textDecoration: 'none' }}>
              Iniciar sesión
            </RouterLink>
          </Typography>
        </Box>
      </Box>
    </Box>
  );
};

export default Signup;
