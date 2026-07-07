/**
 * useAlerts — Single source of truth for the persistent AlertLog.
 *
 * Fetches from GET /api/alerts/ and provides:
 *   - alerts[]      — paginated list (most recent first)
 *   - summary       — counts by severity/source + latest 5
 *   - acknowledge() — mark one alert as read
 *   - acknowledgeAll(source?) — bulk-acknowledge
 *   - refresh()     — manual re-fetch
 *
 * Also reacts to WebSocket `alert_log` messages so new alerts appear
 * instantly without polling.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useSnackbar } from 'notistack';
import { api } from '../services/api';
import { useWebSocket } from '../contexts/WebSocketContext';

// ── Types ─────────────────────────────────────────────────────────────────────

export type AlertSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
// AlertGenerator categories added in migration 0002 (PRECIO/RIESGO/OPERATIVO/OPORTUNIDAD)
export type AlertSource =
  | 'SNAPSHOT' | 'TRANSACTION' | 'ANOMALY' | 'SYSTEM' | 'INVENTORY' | 'RATES'
  | 'PRECIO' | 'RIESGO' | 'OPERATIVO' | 'OPORTUNIDAD';

export interface AlertLogEntry {
  id:                   string;
  source:               AlertSource;
  source_display:       string;
  alert_type:           string;
  severity:             AlertSeverity;
  severity_display:     string;
  title:                string;
  message:              string;
  data:                 Record<string, any>;
  branch:               number | null;
  branch_name:          string | null;
  triggered_by:         number | null;
  triggered_by_name:    string | null;
  is_acknowledged:      boolean;
  acknowledged_by:      number | null;
  acknowledged_by_name: string | null;
  acknowledged_at:      string | null;
  created_at:           string;
}

export interface AlertSummary {
  total_active: number;
  by_severity:  Record<AlertSeverity, number>;
  by_source:    Record<AlertSource, number>;
  latest:       AlertLogEntry[];
}

interface UseAlertsReturn {
  alerts:          AlertLogEntry[];
  summary:         AlertSummary | null;
  loading:         boolean;
  unacknowledged:  number;
  acknowledge:     (id: string) => Promise<void>;
  acknowledgeAll:  (source?: AlertSource) => Promise<void>;
  refresh:         () => Promise<void>;
}

// ── Defaults ──────────────────────────────────────────────────────────────────

const DEFAULT_SUMMARY: AlertSummary = {
  total_active: 0,
  by_severity:  { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 },
  by_source:    {} as Record<AlertSource, number>,
  latest:       [],
};

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAlerts(): UseAlertsReturn {
  const [alerts,  setAlerts]  = useState<AlertLogEntry[]>([]);
  const [summary, setSummary] = useState<AlertSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const { enqueueSnackbar }   = useSnackbar();
  const { lastSheetsSync, lastCapitalUpdate, newAlertLog } = useWebSocket();
  const summaryRef = useRef<AlertSummary | null>(null);

  // ── Fetch ─────────────────────────────────────────────────────────────────

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [alertsRes, summaryRes] = await Promise.all([
        api.get('/alerts/'),
        api.get('/alerts/summary/'),
      ]);
      const list = alertsRes.data?.results ?? alertsRes.data ?? [];
      setAlerts(list);
      const sum = summaryRes.data ?? DEFAULT_SUMMARY;
      setSummary(sum);
      summaryRef.current = sum;
    } catch {
      enqueueSnackbar('Error al cargar alertas', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar]);

  // Initial load
  useEffect(() => { refresh(); }, [refresh]);

  // Refresh when capital or sheets sync events arrive
  useEffect(() => { if (lastCapitalUpdate) refresh(); }, [lastCapitalUpdate, refresh]);
  useEffect(() => { if (lastSheetsSync)    refresh(); }, [lastSheetsSync,    refresh]);

  // Insert new alert from WebSocket without a full re-fetch
  useEffect(() => {
    if (!newAlertLog) return;
    setAlerts(prev => {
      const exists = prev.some(a => a.id === newAlertLog.id);
      if (exists) return prev;
      return [newAlertLog, ...prev];
    });
    // Bump summary counts
    setSummary(prev => {
      const base = prev ?? DEFAULT_SUMMARY;
      const sev  = newAlertLog.severity as AlertSeverity;
      return {
        ...base,
        total_active: base.total_active + 1,
        by_severity:  { ...base.by_severity, [sev]: (base.by_severity[sev] ?? 0) + 1 },
        latest:       [newAlertLog, ...base.latest].slice(0, 5),
      };
    });
  }, [newAlertLog]);

  // ── Actions ───────────────────────────────────────────────────────────────

  const acknowledge = useCallback(async (id: string) => {
    try {
      const res = await api.post(`/alerts/${id}/acknowledge/`);
      setAlerts(prev => prev.map(a => a.id === id ? res.data : a));
      setSummary(prev => {
        if (!prev) return prev;
        const alert = alerts.find(a => a.id === id);
        if (!alert || alert.is_acknowledged) return prev;
        const sev = alert.severity;
        return {
          ...prev,
          total_active: Math.max(0, prev.total_active - 1),
          by_severity:  { ...prev.by_severity, [sev]: Math.max(0, (prev.by_severity[sev] ?? 0) - 1) },
        };
      });
    } catch {
      enqueueSnackbar('Error al reconocer alerta', { variant: 'error' });
    }
  }, [alerts, enqueueSnackbar]);

  const acknowledgeAll = useCallback(async (source?: AlertSource) => {
    try {
      const res = await api.post('/alerts/acknowledge_all/', source ? { source } : {});
      const count = res.data?.acknowledged ?? 0;
      setAlerts(prev => prev.map(a =>
        (!source || a.source === source) && !a.is_acknowledged
          ? { ...a, is_acknowledged: true }
          : a,
      ));
      // Refresh summary after bulk ack
      refresh();
      if (count > 0) {
        enqueueSnackbar(`${count} alerta${count !== 1 ? 's' : ''} reconocida${count !== 1 ? 's' : ''}`,
          { variant: 'success', autoHideDuration: 3000 });
      }
    } catch {
      enqueueSnackbar('Error al reconocer alertas', { variant: 'error' });
    }
  }, [enqueueSnackbar, refresh]);

  const unacknowledged = summary?.total_active ?? alerts.filter(a => !a.is_acknowledged).length;

  return { alerts, summary, loading, unacknowledged, acknowledge, acknowledgeAll, refresh };
}
