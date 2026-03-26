import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  AuthTokens,
  LoginCredentials,
  RatesMap,
  Prediction,
  Transaction,
  NewTransactionPayload,
  DailySummary,
  CurrencyInventory,
  Alert,
  Customer,
  ReportSummary,
  User,
} from '../types';

const BASE_URL = 'http://10.0.2.2:8000/api'; // Android emulator → localhost
// const BASE_URL = 'http://localhost:8000/api'; // iOS simulator
// const BASE_URL = 'https://tu-app.railway.app/api'; // Producción Railway

// ─── Cliente HTTP base ────────────────────────────────────────────────────────
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

  const res = await fetch(`${BASE_URL}${endpoint}`, { ...options, headers });

  if (res.status === 401) {
    // Token expirado → intentar refresh
    const refreshed = await refreshToken();
    if (refreshed) {
      headers.Authorization = `Bearer ${refreshed}`;
      const retryRes = await fetch(`${BASE_URL}${endpoint}`, { ...options, headers });
      return retryRes.json();
    }
    throw new Error('UNAUTHORIZED');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail || `HTTP ${res.status}`);
  }

  return res.json();
}

async function refreshToken(): Promise<string | null> {
  try {
    const refresh = await AsyncStorage.getItem('refresh_token');
    if (!refresh) return null;
    const res = await fetch(`${BASE_URL}/auth/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    });
    if (!res.ok) return null;
    const data: { access: string } = await res.json();
    await AsyncStorage.setItem('access_token', data.access);
    return data.access;
  } catch {
    return null;
  }
}

// ─── Auth ─────────────────────────────────────────────────────────────────────
export const authApi = {
  async login(credentials: LoginCredentials): Promise<AuthTokens> {
    const data = await request<AuthTokens>('/auth/login/', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
    await AsyncStorage.setItem('access_token', data.access);
    await AsyncStorage.setItem('refresh_token', data.refresh);
    return data;
  },

  async logout(): Promise<void> {
    await AsyncStorage.multiRemove(['access_token', 'refresh_token', 'user_pin']);
  },

  async getMe(): Promise<User> {
    return request<User>('/auth/me/');
  },
};

// ─── Tasas ────────────────────────────────────────────────────────────────────
export const ratesApi = {
  getCurrent(): Promise<RatesMap> {
    return request<RatesMap>('/rates/current/');
  },
};

// ─── Predicciones ─────────────────────────────────────────────────────────────
export const predictionsApi = {
  getCurrent(pair = 'USD/BOB'): Promise<Prediction[]> {
    return request<Prediction[]>(`/predictions/current/?pair=${encodeURIComponent(pair)}`);
  },
};

// ─── Transacciones ────────────────────────────────────────────────────────────
export const transactionsApi = {
  async create(
    payload: NewTransactionPayload,
    pin: string,
  ): Promise<{ transaction: Transaction; receipt_url: string }> {
    return request('/transactions/', { method: 'POST', body: JSON.stringify(payload) }, pin);
  },

  getList(date?: string): Promise<Transaction[]> {
    const q = date ? `?date=${date}` : '';
    return request<Transaction[]>(`/transactions/${q}`);
  },

  getDailySummary(date?: string): Promise<DailySummary> {
    const q = date ? `?date=${date}` : '';
    return request<DailySummary>(`/transactions/daily-summary/${q}`);
  },

  searchCustomer(documentNumber: string): Promise<Customer | null> {
    return request<Customer>(`/customers/search/?document=${documentNumber}`).catch(() => null);
  },
};

// ─── Inventario ───────────────────────────────────────────────────────────────
export const inventoryApi = {
  getAll(): Promise<CurrencyInventory[]> {
    return request<CurrencyInventory[]>('/inventory/');
  },
};

// ─── Alertas ──────────────────────────────────────────────────────────────────
export const alertsApi = {
  getActive(): Promise<Alert[]> {
    return request<Alert[]>('/alerts/active/');
  },

  markRead(id: number): Promise<void> {
    return request(`/alerts/${id}/read/`, { method: 'POST' });
  },
};

// ─── Reportes ─────────────────────────────────────────────────────────────────
export const reportsApi = {
  getDaily(date?: string): Promise<ReportSummary[]> {
    const q = date ? `?date=${date}` : '';
    return request<ReportSummary[]>(`/reports/daily/${q}`);
  },
};
