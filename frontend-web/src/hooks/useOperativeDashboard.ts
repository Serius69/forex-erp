import { useState, useCallback, useEffect, useRef } from 'react';
import { useSnackbar } from 'notistack';
import { api, parseRates } from '../services/api';
import { useWebSocket } from '../contexts/WebSocketContext';

export interface DashboardStats {
  today_transactions:   number;
  count_change_pct:     number;
  today_volume_bob:     number;
  volume_change_pct:    number;
  today_profit_bob:     number;
  unique_customers:     number;
  current_rates:        Record<string, any>;
  transactions_by_hour: { hour: string; count: number }[];
  recent_transactions:  any[];
  month_revenue?:       number;
  avg_ticket?:          number;
  avg_spread?:          number;
  pending_transactions?: number;
  daily_cash_flow?:     number;
  current_capital?:     number;
  daily_variation_pct?: number;
}

export interface AlertItem {
  id:        string;
  message:   string;
  severity:  'critical' | 'warning' | 'info';
  category?: string;
  time?:     string;
}

export interface ChartData {
  revenue_30d?:         { date: string; revenue: number; transactions: number }[];
  volume_by_currency?:  { currency: string; volume: number; profit: number }[];
  capital_timeline?:    { date: string; capital: number }[];
  income_distribution?: { name: string; value: number }[];
  alerts?:              AlertItem[];
}

export interface OperativeDashboardData {
  stats:      DashboardStats | null;
  charts:     ChartData;
  rates:      Record<string, any>;
  loading:    boolean;
  refreshing: boolean;
  error:      string | null;
  refresh:    () => void;
}

const AUTO_REFRESH_MS = 30_000;

export function useOperativeDashboard(): OperativeDashboardData {
  const [stats,      setStats]      = useState<DashboardStats | null>(null);
  const [charts,     setCharts]     = useState<ChartData>({});
  const [rates,      setRates]      = useState<Record<string, any>>({});
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error,      setError]      = useState<string | null>(null);
  const { enqueueSnackbar }         = useSnackbar();
  const { rates: wsRates }          = useWebSocket();
  const timerRef                    = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setError(null);
    try {
      const [statsRes, ratesRes, chartsRes] = await Promise.allSettled([
        api.get('/dashboard/stats/'),
        api.get('/rates/exchange-rates/current/'),
        api.get('/dashboard/charts/'),
      ]);

      if (statsRes.status === 'fulfilled') {
        setStats(statsRes.value.data);
      } else if (!silent) {
        throw statsRes.reason;
      }

      if (ratesRes.status === 'fulfilled') {
        const raw = ratesRes.value.data;
        setRates(parseRates(raw?.results ?? raw));
      }

      if (chartsRes.status === 'fulfilled') {
        setCharts(chartsRes.value.data ?? {});
      }
    } catch (e: any) {
      const msg = e?.response?.data?.error ?? 'Error al cargar el dashboard';
      if (!silent) {
        setError(msg);
        enqueueSnackbar(msg, { variant: 'error' });
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => {
    load();
    timerRef.current = setInterval(() => load(true), AUTO_REFRESH_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [load]);

  useEffect(() => {
    if (wsRates && Object.keys(wsRates).length > 0) {
      setRates(prev => ({ ...prev, ...parseRates(wsRates) }));
    }
  }, [wsRates]);

  const refresh = useCallback(() => {
    setRefreshing(true);
    load();
  }, [load]);

  return { stats, charts, rates, loading, refreshing, error, refresh };
}
