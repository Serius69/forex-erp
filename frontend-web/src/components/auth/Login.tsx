// src/components/auth/Login.tsx
import React, { useState, useRef } from 'react';
import {
  Box, TextField, Button, Typography, Alert,
  CircularProgress, InputAdornment, IconButton, Divider,
} from '@mui/material';
import { Visibility, VisibilityOff } from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { TOKENS } from '../../styles/theme';

const Login: React.FC = () => {
  const navigate        = useNavigate();
  const location        = useLocation();
  const { login }       = useAuth();
  const passRef         = useRef<HTMLInputElement>(null);

  const [username,     setUsername]     = useState('');
  const [password,     setPassword]     = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState('');

  const from = (location.state as any)?.from?.pathname || '/dashboard';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('Completa todos los campos.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch {
      setError('Credenciales incorrectas. Verifica tu usuario y contraseña.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{
      minHeight: '100vh',
      display: 'grid',
      gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
      bgcolor: TOKENS.bg,
    }}>
      {/* ── Left panel: brand ── */}
      <Box sx={{
        display: { xs: 'none', md: 'flex' },
        flexDirection: 'column',
        justifyContent: 'space-between',
        bgcolor: TOKENS.navy,
        p: 5,
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* Background pattern */}
        <Box sx={{
          position: 'absolute', inset: 0,
          backgroundImage: `radial-gradient(circle at 20% 50%, ${TOKENS.blue}22 0%, transparent 60%),
                            radial-gradient(circle at 80% 20%, ${TOKENS.green}18 0%, transparent 50%)`,
        }} />

        {/* Logo */}
        <Box sx={{ position: 'relative', zIndex: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
            <Box sx={{
              width: 40, height: 40, borderRadius: '10px',
              bgcolor: TOKENS.blue, display: 'flex',
              alignItems: 'center', justifyContent: 'center',
            }}>
              <Typography sx={{ fontSize: 20, lineHeight: 1 }}>₿</Typography>
            </Box>
            <Typography variant="h5" fontWeight={800} color="white">Kapitalya</Typography>
          </Box>
          <Typography variant="caption" sx={{ color: TOKENS.muted, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            Sistema de Gestión Financiera
          </Typography>
        </Box>

        {/* Center content */}
        <Box sx={{ position: 'relative', zIndex: 1 }}>
          <Typography variant="h2" fontWeight={800} color="white" mb={2} sx={{ lineHeight: 1.2 }}>
            Opera con<br />
            <Box component="span" sx={{ color: TOKENS.blueMid }}>precisión</Box><br />
            y velocidad.
          </Typography>
          <Typography sx={{ color: TOKENS.muted, lineHeight: 1.7, maxWidth: 360 }}>
            Gestión de divisas en tiempo real. Control de inventario, tasas, clientes y reportes ASFI — todo en un solo lugar.
          </Typography>
        </Box>

        {/* Stats */}
        <Box sx={{ position: 'relative', zIndex: 1, display: 'flex', gap: 3 }}>
          {[
            { label: 'Divisas', value: '9+' },
            { label: 'Reportes ASFI', value: '100%' },
            { label: 'Uptime', value: '99.9%' },
          ].map(s => (
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
      }}>
        <Box sx={{ width: '100%', maxWidth: 420 }}>
          {/* Mobile logo */}
          <Box sx={{ display: { xs: 'flex', md: 'none' }, alignItems: 'center', gap: 1.5, mb: 4 }}>
            <Box sx={{ width: 36, height: 36, borderRadius: '9px', bgcolor: TOKENS.blue, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography sx={{ fontSize: 18, lineHeight: 1 }}>₿</Typography>
            </Box>
            <Typography variant="h6" fontWeight={800}>Kapitalya</Typography>
          </Box>

          <Typography variant="h4" fontWeight={800} mb={0.5}>Bienvenido</Typography>
          <Typography variant="body2" color="text.secondary" mb={4}>
            Ingresa tus credenciales para continuar
          </Typography>

          {error && (
            <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError('')}>
              {error}
            </Alert>
          )}

          <form onSubmit={handleSubmit} noValidate>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Box>
                <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 0.75, display: 'block', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                  Usuario
                </Typography>
                <TextField
                  fullWidth
                  placeholder="nombre.usuario"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  autoComplete="username"
                  autoFocus
                  disabled={loading}
                  onKeyDown={e => { if (e.key === 'Enter') passRef.current?.focus(); }}
                  inputProps={{ spellCheck: false }}
                />
              </Box>

              <Box>
                <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 0.75, display: 'block', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                  Contraseña
                </Typography>
                <TextField
                  fullWidth
                  placeholder="••••••••"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  autoComplete="current-password"
                  disabled={loading}
                  inputRef={passRef}
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton
                          onClick={() => setShowPassword(p => !p)}
                          edge="end"
                          size="small"
                          tabIndex={-1}
                          sx={{ color: 'text.secondary' }}
                        >
                          {showPassword ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
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
                disabled={loading || !username || !password}
                sx={{
                  mt: 1,
                  py: 1.5,
                  fontSize: '1rem',
                  fontWeight: 700,
                  borderRadius: '10px',
                  background: loading ? undefined : `linear-gradient(135deg, ${TOKENS.blue} 0%, ${TOKENS.blueMid} 100%)`,
                  boxShadow: `0 4px 14px ${TOKENS.blue}40`,
                  '&:hover': { boxShadow: `0 6px 20px ${TOKENS.blue}50` },
                  '&:disabled': { opacity: 0.7 },
                }}
              >
                {loading
                  ? <><CircularProgress size={18} sx={{ color: 'white', mr: 1 }} /> Ingresando…</>
                  : 'Ingresar al sistema'
                }
              </Button>
            </Box>
          </form>

          <Divider sx={{ my: 3 }} />

          <Box sx={{ display: 'flex', gap: 1, justifyContent: 'center', flexWrap: 'wrap' }}>
            {['ADMIN', 'SUPERVISOR', 'CAJERO'].map(role => (
              <Box key={role} sx={{
                px: 1.5, py: 0.5, borderRadius: '6px',
                bgcolor: role === 'ADMIN' ? TOKENS.blueLight : TOKENS.bg,
                border: `1px solid ${TOKENS.border}`,
              }}>
                <Typography variant="caption" fontWeight={600} color="text.secondary">{role}</Typography>
              </Box>
            ))}
          </Box>
          <Typography variant="caption" color="text.secondary" textAlign="center" display="block" mt={1}>
            Acceso por rol asignado por el administrador
          </Typography>
        </Box>
      </Box>
    </Box>
  );
};

export default Login;
