// src/services/analyticsApi.ts
import { api } from './api';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface KPIPeriod {
  ganancia_neta_bob: string;
  volumen_bob: string;
  num_transacciones: number;
  spread_promedio_bob: string;
}

export interface OverviewResponse {
  kpis: {
    today: KPIPeriod;
    week: KPIPeriod;
    month: KPIPeriod;
  };
  exposure: {
    total_exposure_bob?: string;
    divisas?: Array<{ currency_code: string; exposure_bob: string; pct_of_capital: string }>;
  };
  top_currencies: Array<{ currency_code: string; ganancia_bob: string; ops: number }>;
  inventory_health: { total: number; healthy: number; low_stock: number; overstocked: number };
  alerts_summary: { critical: number; high: number; medium: number; unacknowledged: number };
  calculado_en: string;
  branch: string;
}

export interface TrendSeries {
  pnl?: Array<{ fecha: string; ganancia_neta_bob: string; ganancia_bruta_bob: string; margen_neto_pct: string }>;
  volume?: Array<{ fecha: string; volumen_bob: string; num_transacciones: number }>;
  spread?: Array<{ fecha: string; spread_promedio_bob: string; spread_pct: string }>;
  transactions?: Array<{ fecha: string; buy_count: number; sell_count: number; total: number }>;
}

export interface TrendsResponse {
  period: { desde: string; hasta: string; granularity: string };
  series: TrendSeries;
  summary: { trend_direction: 'UP' | 'DOWN' | 'STABLE'; growth_pct: string };
  calculado_en: string;
}

export interface Anomaly {
  type: string;
  source: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  title: string;
  description: string;
  value: string;
  threshold: string;
  deviation_pct: string;
  detected_at: string;
  recommendation: string;
}

export interface AnomaliesResponse {
  anomalies: Anomaly[];
  summary: { total: number; critical: number; high: number; medium: number; low: number };
  branch: string;
  last_checked: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// API functions
// ─────────────────────────────────────────────────────────────────────────────

export const analyticsApi = {
  overview: (params?: { all_branches?: boolean }) =>
    api.get<OverviewResponse>('/analytics/overview/', { params }),

  trends: (params?: {
    date_from?: string;
    date_to?: string;
    granularity?: 'daily' | 'weekly';
    metrics?: string;
  }) => api.get<TrendsResponse>('/analytics/trends/', { params }),

  anomalies: (params?: {
    severity?: string;
    source?: string;
    limit?: number;
  }) => api.get<AnomaliesResponse>('/analytics/anomalies/', { params }),

  pnl: (params?: { date_from?: string; date_to?: string; currency?: string }) =>
    api.get('/analytics/pnl/', { params }),

  exposure: (params?: { currency?: string; days?: number }) =>
    api.get('/analytics/exposure/', { params }),

  spread: (params?: { currency?: string; market_type?: string; days?: number }) =>
    api.get('/analytics/spread/', { params }),

  decision: (params: { currency: string; branch_id?: number }) =>
    api.get('/analytics/decision/', { params }),

  decisionHistory: (params?: {
    currency?: string;
    decision?: string;
    date_from?: string;
    date_to?: string;
    page?: number;
    page_size?: number;
  }) => api.get('/analytics/decision/history/', { params }),
};
