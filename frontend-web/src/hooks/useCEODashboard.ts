import { useState, useCallback, useEffect } from 'react';
import { api } from '../services/api';
import { useWebSocket } from '../contexts/WebSocketContext';

export interface CEOData {
  generated_at: string;
  from_cache:   boolean;
  capital: {
    total_bob:    number;
    efectivo_bob: number;
    digital_bob:  number;
    branches:     number;
  };
  pnl: {
    today:      { ganancia_neta: number; ingreso_ventas: number; gastos_operativos: number };
    week:       { ganancia_neta: number; ingreso_ventas: number; gastos_operativos: number };
    month:      { ganancia_neta: number; ingreso_ventas: number; gastos_operativos: number };
    prev_month?: { ganancia_neta: number; ingreso_ventas: number };
  };
  transactions: {
    today: { count: number; volume_bob: number; buys: number; sells: number };
    week:  { count: number; volume_bob: number; buys: number; sells: number };
    month: { count: number; volume_bob: number; buys: number; sells: number };
  };
  currencies: {
    best:  { currency_code: string; ganancia: number } | null;
    worst: { currency_code: string; ganancia: number } | null;
    all:   { currency: string; ganancia_bob: number }[];
  };
  exposure: {
    total_exposure_bob:  number;
    unrealized_pnl_bob:  number;
    critical_count:      number;
    warning_count:       number;
  };
  rates:      { currency: string; buy: number; sell: number; official: number; updated: string }[];
  ai_pricing: { currency: string; suggested_buy: number; suggested_sell: number; spread_pct: number; recommendation: string }[];
  alerts:     { type: string; severity: string; message: string }[];
  inventory:  { currency: string; branch: string; stock: number; stock_pct: number; status: string }[];
  kpis?: {
    roi_monthly?:         number;
    net_margin?:          number;
    ebitda?:              number;
    monthly_growth_pct?:  number;
    total_capital?:       number;
    accumulated_profit?:  number;
  };
  activity_heatmap?:   { day: number; hour: number; count: number }[];
  monthly_comparison?: { month: string; current: number; previous: number }[];
}

export interface CEODashboardData {
  data:       CEOData | null;
  loading:    boolean;
  refreshing: boolean;
  error:      string | null;
  refresh:    (force?: boolean) => void;
}

export function useCEODashboard(): CEODashboardData {
  const [data,       setData]       = useState<CEOData | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error,      setError]      = useState<string | null>(null);
  const { lastCapitalUpdate }       = useWebSocket();

  const fetchData = useCallback(async (force = false) => {
    try {
      setError(null);
      const res = await api.get(`/dashboard/executive/${force ? '?refresh=true' : ''}`);
      setData(res.data);
    } catch (e: any) {
      setError(e?.response?.data?.error ?? 'Error al cargar el dashboard CEO');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    if (lastCapitalUpdate) fetchData(true);
  }, [lastCapitalUpdate, fetchData]);

  const refresh = useCallback((force = false) => {
    setRefreshing(true);
    fetchData(force);
  }, [fetchData]);

  return { data, loading, refreshing, error, refresh };
}
