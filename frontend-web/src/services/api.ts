// src/services/api.ts

import axios, { AxiosInstance, InternalAxiosRequestConfig, AxiosError } from 'axios';

// Vite exposes VITE_* variables via import.meta.env (typed in vite-env.d.ts).
// In production with nginx the URLs are relative — nginx proxies to the backend.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';
const WS_URL   = import.meta.env.VITE_WS_BASE_URL  || '/ws';

export { WS_URL };
// ── Instancia principal ───────────────────────────────────────────────────────
export const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// ── Cola de requests en espera durante refresh ────────────────────────────────
let isRefreshing  = false;
let failedQueue:  { resolve: (token: string) => void; reject: (err: any) => void }[] = [];

const processQueue = (error: any, token: string | null) => {
  failedQueue.forEach(({ resolve, reject }) =>
    error ? reject(error) : resolve(token!)
  );
  failedQueue = [];
};

// ── Request interceptor: adjunta token + Idempotency-Key ────────────────────
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) config.headers.Authorization = `Bearer ${token}`;

    // Inyectar Idempotency-Key en POSTs a /transactions/ si no viene ya
    if (
      config.method === 'post' &&
      config.url?.includes('/transactions/') &&
      !config.headers['Idempotency-Key']
    ) {
      config.headers['Idempotency-Key'] = crypto.randomUUID?.()
        ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// ── Response interceptor: refresca en 401 ────────────────────────────────────
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    if (!error.config) return Promise.reject(error);
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status !== 401 || originalRequest._retry) {
      return Promise.reject(error);
    }

    // No intentar refresh en la ruta de login/refresh misma
    if (originalRequest.url?.includes('/auth/')) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      window.location.href = '/login';
      return Promise.reject(error);
    }

    if (isRefreshing) {
      // Encolar mientras se refresca
      return new Promise((resolve, reject) => {
        failedQueue.push({
          resolve: (token) => {
            originalRequest.headers.set('Authorization', `Bearer ${token}`);
            resolve(api(originalRequest));
          },
          reject,
        });
      });
    }

    originalRequest._retry = true;
    isRefreshing            = true;

    try {
      const refresh = localStorage.getItem('refresh_token');
      if (!refresh) throw new Error('No refresh token');

      const { data } = await axios.post(`${BASE_URL}/auth/refresh/`, {
        refresh,
      });

      const newToken = data.access;
      localStorage.setItem('access_token', newToken);
      api.defaults.headers.common.Authorization = `Bearer ${newToken}`;
      processQueue(null, newToken);

      originalRequest.headers.set('Authorization', `Bearer ${newToken}`);
      return api(originalRequest);
    } catch (refreshError) {
      processQueue(refreshError, null);
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      window.location.href = '/login';
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  }
);

export const downloadFile = (blob: Blob, filename: string): void => {
  const url  = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};

// Normaliza tasas — acepta array (REST) O mapa (WebSocket)
export default api;

export function parseRates(data: any): Record<string, any> {
  if (!data) return {};
  const map: Record<string, any> = {};

  if (Array.isArray(data)) {
    data.forEach((r: any) => {
      const code = r.currency_from?.code ?? r.currency_from;
      if (code && code !== 'BOB') {
        map[code] = {
          buy:         parseFloat(r.buy_rate  ?? r.buy  ?? 0),
          sell:        parseFloat(r.sell_rate ?? r.sell ?? 0),
          official:    parseFloat(r.official_rate ?? r.official ?? 0),
          spread:      parseFloat(r.spread_percentage ?? 0),
          scale_factor: r.currency_from?.scale_factor ?? r.scale_factor ?? 1,
          market_type: r.market_type ?? 'parallel',
          id:          r.id,
          name:        r.currency_from?.name ?? code,
        };
      }
    });
  } else if (typeof data === 'object') {
    Object.entries(data).forEach(([code, r]: [string, any]) => {
      map[code] = {
        buy:         parseFloat(r.buy_rate  ?? r.buy  ?? r.sell_rate ?? 0),
        sell:        parseFloat(r.sell_rate ?? r.sell ?? 0),
        official:    parseFloat(r.official_rate ?? r.official ?? 0),
        spread:      parseFloat(r.spread_percentage ?? 0),
        scale_factor: r.scale_factor ?? 1,
        market_type: r.market_type ?? 'parallel',
        name:        r.name ?? code,
      };
    });
  }
  return map;
}