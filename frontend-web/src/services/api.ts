// src/services/api.ts
import axios, { AxiosInstance, InternalAxiosRequestConfig, AxiosError } from 'axios';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';
const WS_URL   = import.meta.env.VITE_WS_BASE_URL  || '/ws';

export { WS_URL };

// ── Token storage ─────────────────────────────────────────────────────────────
// Access token: JS memory only (cleared on page reload; re-hydrated via refresh on mount)
// Refresh token: localStorage (survives page reload, cleared on logout)

const REFRESH_KEY = 'kapitalya_refresh';

let _accessToken: string | null = null;

export const setAccessToken   = (t: string | null): void => { _accessToken = t; };
export const getAccessToken   = (): string | null => _accessToken;
export const clearAccessToken = (): void => { _accessToken = null; };

export const setRefreshToken   = (t: string): void => localStorage.setItem(REFRESH_KEY, t);
export const getRefreshToken   = (): string | null => localStorage.getItem(REFRESH_KEY);
export const clearRefreshToken = (): void => localStorage.removeItem(REFRESH_KEY);

export const clearAllTokens = (): void => {
  clearAccessToken();
  clearRefreshToken();
};

// ── Axios instance ────────────────────────────────────────────────────────────
export const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

// ── Refresh queue (prevents parallel refresh storms) ─────────────────────────
let isRefreshing = false;
let failedQueue: { resolve: (t: string) => void; reject: (e: unknown) => void }[] = [];

const drainQueue = (error: unknown, token: string | null): void => {
  failedQueue.forEach(({ resolve, reject }) => (error ? reject(error) : resolve(token!)));
  failedQueue = [];
};

// ── Request interceptor ───────────────────────────────────────────────────────
api.interceptors.request.use(
  (config) => {
    if (_accessToken) {
      config.headers.Authorization = `Bearer ${_accessToken}`;
    }
    // Idempotency key for financial transactions
    if (
      config.method === 'post' &&
      config.url?.includes('/transactions/') &&
      !config.headers['Idempotency-Key']
    ) {
      config.headers['Idempotency-Key'] =
        crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
    return config;
  },
  (err) => Promise.reject(err),
);

// ── Response interceptor — silent 401 → refresh → retry ──────────────────────
api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    if (!error.config) return Promise.reject(error);

    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    // Only handle 401; skip if already retried
    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error);
    }

    // Never try to refresh auth endpoints themselves (avoids infinite loop)
    if (original.url?.includes('/auth/')) {
      clearAllTokens();
      window.location.replace('/login');
      return Promise.reject(error);
    }

    // Queue concurrent requests while a refresh is in-flight
    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        failedQueue.push({
          resolve: (token) => {
            original.headers.set('Authorization', `Bearer ${token}`);
            resolve(api(original));
          },
          reject,
        });
      });
    }

    original._retry = true;
    isRefreshing    = true;

    const refresh = getRefreshToken();
    if (!refresh) {
      clearAllTokens();
      window.location.replace('/login');
      return Promise.reject(error);
    }

    try {
      const { data } = await axios.post(`${BASE_URL}/auth/refresh/`, { refresh });
      const newAccess = data.access;

      setAccessToken(newAccess);
      if (data.refresh) setRefreshToken(data.refresh); // rotated token
      api.defaults.headers.common.Authorization = `Bearer ${newAccess}`;

      drainQueue(null, newAccess);
      original.headers.set('Authorization', `Bearer ${newAccess}`);
      return api(original);
    } catch (refreshErr) {
      drainQueue(refreshErr, null);
      clearAllTokens();
      window.location.replace('/login');
      return Promise.reject(refreshErr);
    } finally {
      isRefreshing = false;
    }
  },
);

// ── Utilities ─────────────────────────────────────────────────────────────────
export const downloadFile = (blob: Blob, filename: string): void => {
  const url  = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href     = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};

export default api;

export function parseRates(data: unknown): Record<string, unknown> {
  if (!data) return {};
  const map: Record<string, unknown> = {};
  if (Array.isArray(data)) {
    data.forEach((r: any) => {
      const code = r.currency_from?.code ?? r.currency_from;
      if (code && code !== 'BOB') {
        map[code] = {
          buy:          parseFloat(r.buy_rate  ?? r.buy  ?? 0),
          sell:         parseFloat(r.sell_rate ?? r.sell ?? 0),
          official:     parseFloat(r.official_rate ?? r.official ?? 0),
          spread:       parseFloat(r.spread_percentage ?? 0),
          scale_factor: r.currency_from?.scale_factor ?? r.scale_factor ?? 1,
          market_type:  r.market_type ?? 'parallel',
          id:           r.id,
          name:         r.currency_from?.name ?? code,
        };
      }
    });
  } else if (typeof data === 'object' && data !== null) {
    Object.entries(data as Record<string, any>).forEach(([code, r]) => {
      map[code] = {
        buy:          parseFloat(r.buy_rate  ?? r.buy  ?? r.sell_rate ?? 0),
        sell:         parseFloat(r.sell_rate ?? r.sell ?? 0),
        official:     parseFloat(r.official_rate ?? r.official ?? 0),
        spread:       parseFloat(r.spread_percentage ?? 0),
        scale_factor: r.scale_factor ?? 1,
        market_type:  r.market_type ?? 'parallel',
        name:         r.name ?? code,
      };
    });
  }
  return map;
}
