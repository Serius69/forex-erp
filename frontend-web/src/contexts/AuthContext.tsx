// src/contexts/AuthContext.tsx
import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  api, BASE_URL,
  setAccessToken, clearAccessToken,
  setRefreshToken, getRefreshToken, clearRefreshToken,
  clearAllTokens,
} from '../services/api';
import { setErrorLoggerContext } from '../services/errorLogger';
import { User } from '../types';

// Role → default landing page after login
const ROLE_HOME: Record<string, string> = {
  ADMIN:      '/dashboard',
  SUPERVISOR: '/analytics',
  CASHIER:    '/transactions',
};

// ── Types ──────────────────────────────────────────────────────────────────────
export interface SignupData {
  email:            string;
  username?:        string;
  first_name?:      string;
  last_name?:       string;
  password:         string;
  password_confirm: string;
}

interface AuthContextType {
  user:        User | null;
  loading:     boolean;
  login:       (usernameOrEmail: string, password: string) => Promise<void>;
  /** Devuelve un mensaje si la cuenta quedó pendiente de aprobación (sin sesión); null si inició sesión. */
  signup:      (data: SignupData) => Promise<string | null>;
  /** Igual que signup: mensaje de "pendiente de aprobación" para cuentas nuevas, null si inició sesión. */
  loginGoogle: (credential: string) => Promise<string | null>;
  logout:      () => Promise<void>;
  verifyPin:   (pin: string) => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = (): AuthContextType => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};

// ── Provider ──────────────────────────────────────────────────────────────────
export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user,    setUser]    = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate   = useNavigate();
  const initDone   = useRef(false);  // guard against StrictMode double-invoke

  // ── On mount: try to restore session via refresh token ───────────────────
  useEffect(() => {
    if (initDone.current) return;
    initDone.current = true;

    const refresh = getRefreshToken();
    if (!refresh) {
      // No stored refresh token → stay logged out immediately
      setLoading(false);
      return;
    }

    (async () => {
      try {
        // Exchange refresh token for new access token.
        // BASE_URL (no '/api' fijo): con VITE_API_BASE_URL absoluta (Tailscale)
        // el refresh al recargar debe ir al mismo origen que el resto del API.
        const { data } = await axios.post(`${BASE_URL}/auth/refresh/`, { refresh });
        const newAccess = data.access;
        if (data.refresh) setRefreshToken(data.refresh); // rotation

        setAccessToken(newAccess);
        api.defaults.headers.common.Authorization = `Bearer ${newAccess}`;

        // Load current user profile
        const { data: me } = await api.get('/users/me/');
        setUser(me);
      } catch {
        // Refresh token expired/invalid → clean slate
        clearAllTokens();
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // ── Helpers ───────────────────────────────────────────────────────────────
  const _applySession = useCallback((access: string, refresh: string, userData: User) => {
    setAccessToken(access);
    setRefreshToken(refresh);
    api.defaults.headers.common.Authorization = `Bearer ${access}`;
    setUser(userData);
    setErrorLoggerContext(userData.id ?? null, userData.company_id ?? null);
  }, []);

  const _redirectForRole = useCallback((role: string) => {
    navigate(ROLE_HOME[role] ?? '/dashboard', { replace: true });
  }, [navigate]);

  // ── Login ─────────────────────────────────────────────────────────────────
  // Throws on failure so the Login component can catch and show the error.
  const login = useCallback(async (usernameOrEmail: string, password: string): Promise<void> => {
    const { data } = await api.post('/auth/login/', {
      username: usernameOrEmail,
      password,
    });
    _applySession(data.access, data.refresh, data.user);
    _redirectForRole(data.user.role);
  }, [_applySession, _redirectForRole]);

  // ── Signup ────────────────────────────────────────────────────────────────
  // El backend ya no emite tokens al registrarse: la cuenta queda inactiva
  // hasta que un ADMIN la apruebe y le asigne empresa.
  const signup = useCallback(async (formData: SignupData): Promise<string | null> => {
    const { data } = await api.post('/auth/signup/', formData);
    if (data.pending_approval) {
      return data.detail ?? 'Cuenta creada. Un administrador debe aprobarla antes de que puedas ingresar.';
    }
    _applySession(data.access, data.refresh, data.user);
    _redirectForRole(data.user.role);
    return null;
  }, [_applySession, _redirectForRole]);

  // ── Google OAuth ──────────────────────────────────────────────────────────
  const loginGoogle = useCallback(async (credential: string): Promise<string | null> => {
    const { data } = await api.post('/auth/google/', { credential });
    if (data.pending_approval) {
      return data.detail ?? 'Cuenta creada. Un administrador debe aprobarla antes de que puedas ingresar.';
    }
    _applySession(data.access, data.refresh, data.user);
    _redirectForRole(data.user.role);
    return null;
  }, [_applySession, _redirectForRole]);

  // ── Logout ────────────────────────────────────────────────────────────────
  const logout = useCallback(async (): Promise<void> => {
    const refresh = getRefreshToken();
    if (refresh) {
      try {
        // Blacklist the refresh token server-side
        await api.post('/auth/logout/', { refresh });
      } catch {
        // Network failure: token will expire naturally, proceed anyway
      }
    }
    clearAllTokens();
    delete api.defaults.headers.common.Authorization;
    setUser(null);
    navigate('/login', { replace: true });
  }, [navigate]);

  // ── PIN verify ────────────────────────────────────────────────────────────
  const verifyPin = useCallback(async (pin: string): Promise<boolean> => {
    try {
      const { data } = await api.post('/users/verify-pin/', { pin });
      return Boolean(data.valid);
    } catch {
      return false;
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, loginGoogle, logout, verifyPin }}>
      {children}
    </AuthContext.Provider>
  );
};
