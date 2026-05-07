// src/services/ratesApi.ts
// Servicio centralizado para todos los endpoints de tasas y predicciones.
import { api } from './api';

// ── Tipos ────────────────────────────────────────────────────────────────────

export interface LiveRate {
  pair:        string;
  buy:         number;
  sell:        number;
  spread:      number;
  spread_pct:  number;
  source:      string;
  source_url:  string | null;
  confidence:  number;
  timestamp:   string;
  is_live:     boolean;
  anomalies:   { type: string; severity: string; message: string }[];
}

export interface ExchangeRate {
  id:               number;
  currency_from:    { code: string; name: string; scale_factor: number };
  currency_to:      { code: string; name: string };
  buy_rate:         string;
  sell_rate:        string;
  official_rate:    string;
  spread_percentage:string;
  source_method:    'API' | 'SCRAP' | 'MANUAL' | 'INFERENCE';
  source_url:       string | null;
  confidence:       string;
  fetched_at:       string | null;
  is_primary:       boolean;
  is_validated:     boolean;
  market_type:      string;
  valid_from:       string | null;
  valid_until:      string | null;
  created_by?:      { username: string; first_name?: string; last_name?: string } | null;
}

export interface ForecastPrediction {
  datetime: string;
  rate:     number;
  lower:    number;
  upper:    number;
}

export interface ForecastResult {
  currency_pair:       string;
  horizon:             string;
  horizon_hours:       number;
  predicted_rate:      number;
  confidence_interval: { lower: number; upper: number; level: number };
  model_weights:       Record<string, number>;
  backtesting_metrics: { mape?: number; rmse?: number; mae?: number } | null;
  data_freshness:      string;
  predictions:         ForecastPrediction[];
  generated_at:        string;
}

export interface SourceLiveRate {
  source:        string;
  source_label:  string;
  currency:      string;
  buy_rate:      string;
  sell_rate:     string;
  official_rate: string;
  confidence:    number;
  source_method: 'API' | 'SCRAP' | 'MANUAL' | 'INFERENCE';
  market_type:   string;
  fetched_at:    string | null;
  is_stale:      boolean;
  is_primary:    boolean;
  source_url:    string | null;
}

export interface SourcesLiveResponse {
  currency:   string;
  count:      number;
  checked_at: string;
  sources:    SourceLiveRate[];
}

export interface ModelHealthReport {
  [model: string]: {
    status:       'healthy' | 'degraded' | 'stale' | 'untrained';
    last_trained: string | null;
    mape:         number | null;
    drift:        boolean;
    data_points:  number;
  };
}

// ── API calls ─────────────────────────────────────────────────────────────────

export const ratesApi = {
  /** Mejor tasa disponible en tiempo real para una divisa */
  getLiveRate: (currency: string): Promise<LiveRate> =>
    api.get(`/rates/exchange-rates/live/?currency=${currency}`).then(r => r.data),

  /** Lista completa de tasas (todas las fuentes) */
  getExchangeRates: (): Promise<ExchangeRate[]> =>
    api.get('/rates/exchange-rates/').then(r => r.data.results ?? r.data),

  /** Sólo tasas vigentes (is_primary o más recientes por par) */
  getCurrentRates: (): Promise<ExchangeRate[]> =>
    api.get('/rates/exchange-rates/current/').then(r => r.data.results ?? r.data),

  /** Crear tasa manual */
  createRate: (data: Partial<ExchangeRate>): Promise<ExchangeRate> =>
    api.post('/rates/exchange-rates/', data).then(r => r.data),

  /** Actualizar tasa (edición manual o toggle activo) */
  updateRate: (id: number, data: Partial<ExchangeRate>): Promise<ExchangeRate> =>
    api.patch(`/rates/exchange-rates/${id}/`, data).then(r => r.data),

  /** Pronóstico ML ensemble para un par de divisas */
  getForecast: (pair: string, horizon: '1h' | '4h' | '24h' | '7d' = '24h'): Promise<ForecastResult> =>
    api.get(`/predictions/forecast/${pair}/?horizon=${horizon}&ci=true`, { timeout: 90_000 }).then(r => r.data),

  /** Estado de salud de todos los modelos ML */
  getPredictionHealth: (): Promise<ModelHealthReport> =>
    api.get('/predictions/health/').then(r => r.data),

  /** Forzar actualización de tasas del mercado paralelo */
  refreshParallelRates: (): Promise<void> =>
    api.post('/rates/exchange-rates/update_rates/', { source: 'dolarbluebolivia_click' }).then(() => undefined),

  /** Lista de divisas disponibles */
  getCurrencies: () =>
    api.get('/rates/currencies/').then(r => r.data.results ?? r.data),

  /** Todas las tasas activas por fuente para una divisa */
  getSourcesLive: (currency: string, maxAge = 60): Promise<SourcesLiveResponse> =>
    api.get(`/rates/exchange-rates/sources-live/?currency=${currency}&max_age=${maxAge}`).then(r => r.data),
};

export default ratesApi;
