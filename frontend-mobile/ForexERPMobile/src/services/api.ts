// src/services/api.ts
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  AuthTokens, LoginCredentials, RatesMap, Prediction,
  Transaction, NewTransactionPayload, DailySummary,
  CurrencyInventory, Alert, Customer, ReportSummary, User,
} from '../types/index';
import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '../config';
import { aggregateDailyReport } from '../utils/reportAggregation';

const BASE_URL = API_BASE_URL; // Ver src/config.ts para cambiar host/puerto

/**
 * fetch con timeout vía AbortController. Si el servidor no responde en
 * REQUEST_TIMEOUT_MS se aborta y se lanza 'Network request timed out',
 * mensaje que offlineQueue.isNetworkError clasifica como error de red.
 */
async function fetchWithTimeout(url: string, options: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timer      = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (controller.signal.aborted) throw new Error('Network request timed out');
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  requirePin?: string,
): Promise<T> {
  const token = await AsyncStorage.getItem('access_token');

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(requirePin ? { 'X-User-PIN': requirePin } : {}),
    ...(options.headers as Record<string, string>),
  };

  const res = await fetchWithTimeout(`${BASE_URL}${endpoint}`, { ...options, headers });

  if (res.status === 401) {
    const refreshed = await refreshToken();
    if (refreshed) {
      headers.Authorization = `Bearer ${refreshed}`;
      const retryRes = await fetchWithTimeout(`${BASE_URL}${endpoint}`, { ...options, headers });
      if (!retryRes.ok) throw new Error(`HTTP ${retryRes.status}`);
      return retryRes.json();
    }
    throw new Error('UNAUTHORIZED');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail || err?.error || `HTTP ${res.status}`);
  }

  // 204 No Content
  if (res.status === 204) return {} as T;

  return res.json();
}

// Single-flight: múltiples 401 simultáneos comparten el mismo POST /auth/refresh/
// en lugar de disparar refreshes en paralelo (que invalidarían tokens entre sí).
let refreshPromise: Promise<string | null> | null = null;

function refreshToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = doRefreshToken().finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

async function doRefreshToken(): Promise<string | null> {
  try {
    const refresh = await AsyncStorage.getItem('refresh_token');
    if (!refresh) return null;
    const res = await fetchWithTimeout(`${BASE_URL}/auth/refresh/`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ refresh }),
    });
    if (!res.ok) return null;
    const data: { access: string } = await res.json();
    await AsyncStorage.setItem('access_token', data.access);
    return data.access;
  } catch {
    return null;
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export const authApi = {
  async login(credentials: LoginCredentials): Promise<AuthTokens & { user: User }> {
    const data = await request<AuthTokens & { user: User }>('/auth/login/', {
      method: 'POST',
      body:   JSON.stringify({
        username: credentials.username,
        password: credentials.password,
      }),
    });
    await AsyncStorage.setItem('access_token',  data.access);
    await AsyncStorage.setItem('refresh_token', data.refresh);
    return data;
  },

  async logout(): Promise<void> {
    await AsyncStorage.multiRemove(['access_token', 'refresh_token', 'user_pin']);
  },

  async getMe(): Promise<User> {
    return request<User>('/users/me/');
  },
};

// ── Tasas ─────────────────────────────────────────────────────────────────────
export const ratesApi = {
  async getCurrent(): Promise<RatesMap> {
    // Devuelve array de tasas — convertimos a mapa por código
    const data = await request<any>('/rates/exchange-rates/current/');
    const map: RatesMap = {};

    if (Array.isArray(data)) {
      data.forEach((r: any) => {
        const code = r.currency_from?.code ?? r.currency_from;
        map[code] = {
          buy:      parseFloat(r.buy_rate),
          sell:     parseFloat(r.sell_rate),
          official: parseFloat(r.official_rate),
          spread:   parseFloat(r.spread_percentage ?? 0),
        };
      });
    } else if (data?.rates) {
      return data.rates;
    }
    return map;
  },
};

// ── Predicciones ──────────────────────────────────────────────────────────────
export const predictionsApi = {
  async getCurrent(pair = 'USD/BOB'): Promise<Prediction[]> {
    const data = await request<any>(
      `/predictions/predictions/current/?currency_pair=${encodeURIComponent(pair)}`
    );
    // La API devuelve { currency_pair, predictions: { PROPHET: [...], LSTM: [...] } }
    const allPredictions: Prediction[] = [];
    if (data?.predictions) {
      Object.values(data.predictions).forEach((arr: any) => {
        if (Array.isArray(arr)) allPredictions.push(...arr);
      });
    }
    return allPredictions.slice(0, 8);
  },
};

// ── Transacciones ─────────────────────────────────────────────────────────────
export const transactionsApi = {
  async create(
    payload: NewTransactionPayload,
    pin: string,
  ): Promise<{ transaction: Transaction; receipt_url: string }> {
    const data = await request<Transaction>(
      '/transactions/',
      { method: 'POST', body: JSON.stringify(payload) },
      pin,
    );
    return { transaction: data, receipt_url: '' };
  },

  async getList(date?: string): Promise<Transaction[]> {
    const params = date ? `?date_from=${date}&date_to=${date}` : '';
    const data   = await request<any>(`/transactions/${params}`);
    return data?.results ?? data ?? [];
  },

  async getDailySummary(date?: string): Promise<DailySummary> {
    const params = date ? `?date=${date}` : '';
    try {
      return await request<DailySummary>(`/transactions/daily-summary/${params}`);
    } catch {
      // Fallback al dashboard stats si daily-summary no existe
      const stats = await request<any>('/dashboard/stats/');
      return {
        transaction_count: stats.today_transactions   ?? 0,
        total_buy:         stats.today_volume_bob      ?? 0,
        total_sell:        stats.today_volume_bob      ?? 0,
        total_profit:      stats.today_profit_bob      ?? 0,
      };
    }
  },

  async searchCustomer(documentNumber: string): Promise<Customer | null> {
    try {
      return await request<Customer>(`/customers/search/?document=${documentNumber}`);
    } catch {
      return null;
    }
  },
};

// ── Inventario ────────────────────────────────────────────────────────────────
export const inventoryApi = {
  async getAll(): Promise<CurrencyInventory[]> {
    const data = await request<any>('/inventory/stock/');
    return data?.results ?? data ?? [];
  },
};

// ── Alertas ───────────────────────────────────────────────────────────────────
export const alertsApi = {
  async getActive(): Promise<Alert[]> {
    // El error se propaga: AlertsScreen lo muestra con ErrorBanner + retry.
    const data = await request<any>('/inventory/alerts/?is_resolved=false');
    return data?.results ?? data ?? [];
  },

  async markRead(id: number): Promise<void> {
    await request(`/inventory/alerts/${id}/resolve/`, {
      method: 'POST',
      body:   JSON.stringify({ notes: 'Leída desde app móvil' }),
    });
  },
};

// ── Tarjetas ──────────────────────────────────────────────────────────────────
export const tarjetasApi = {
  async getInventario(): Promise<any[]> {
    const data = await request<any>('/tarjetas/tipos/inventario/');
    return Array.isArray(data) ? data : data?.results ?? [];
  },

  async vender(tipoId: number, payload: {
    cantidad: number; precio_venta: number;
    medio_pago: string; cliente_nombre?: string;
  }): Promise<any> {
    return request<any>(`/tarjetas/tipos/${tipoId}/vender/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
};

// ── Capital ───────────────────────────────────────────────────────────────────
export const capitalApi = {
  async getActual(): Promise<any> {
    return request<any>('/capital/actual/');
  },
};

// ── Reportes ──────────────────────────────────────────────────────────────────
export const reportsApi = {
  async getDaily(date?: string): Promise<ReportSummary[]> {
    const dateStr = date ?? new Date().toISOString().split('T')[0];
    const data    = await request<any>(
      `/transactions/?date_from=${dateStr}&date_to=${dateStr}&page_size=200`
    );
    const txs: any[] = data?.results ?? data ?? [];
    // Agrupación por divisa con promedio ponderado real (BOB / unidades divisa)
    return aggregateDailyReport(txs);
  },
};