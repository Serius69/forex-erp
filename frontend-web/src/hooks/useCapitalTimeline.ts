/**
 * useCapitalTimeline — Fetches and normalises capital snapshots for charting.
 *
 * Data source: GET /capital/snapshots/?date_from=&date_to=
 *
 * Returns ready-to-render chart points plus range controls so the component
 * stays free of any data-fetching concern.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { subDays, format, parseISO } from 'date-fns';
import { useSnackbar } from 'notistack';
import { api } from '../services/api';
import type { CapitalSnapshot } from './useDashboard';

// ── Types ─────────────────────────────────────────────────────────────────────

export type RangePreset = '7D' | '30D' | '90D' | '6M' | '1Y' | 'custom';

export interface TimelinePoint {
  /** ISO date string — used as the chart X key */
  fecha: string;
  /** Human-readable label for the X axis tick */
  label: string;
  capital_neto: number;
  total_activos: number;
  efectivo_bob: number;
  divisas_bob: number;
  tarjetas_bob: number;
  qr_bob: number;
  pasivos_bob: number;
  tipo: string;
  branch_name: string;
  generado_por: string;
}

export interface UseCapitalTimelineReturn {
  data: TimelinePoint[];
  loading: boolean;
  error: string | null;
  /** Date range currently applied */
  dateFrom: string;
  dateTo: string;
  preset: RangePreset;
  /** Set one of the quick-select presets */
  setPreset: (p: RangePreset) => void;
  /** Set an explicit custom range (switches preset to 'custom') */
  setCustomRange: (from: string, to: string) => void;
  refresh: () => void;
  /** Stats derived from current data — avoids recomputing in the component */
  stats: {
    max: number;
    min: number;
    latest: number;
    earliest: number;
    delta: number;
    deltaPct: number;
    count: number;
  } | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const today = () => format(new Date(), 'yyyy-MM-dd');

const presetRange = (preset: RangePreset): { from: string; to: string } => {
  const to = today();
  const map: Record<Exclude<RangePreset, 'custom'>, number> = {
    '7D': 7, '30D': 30, '90D': 90, '6M': 182, '1Y': 365,
  };
  if (preset === 'custom') return { from: to, to };
  return { from: format(subDays(new Date(), map[preset]), 'yyyy-MM-dd'), to };
};

const toPoint = (s: CapitalSnapshot): TimelinePoint => {
  const total    = parseFloat(s.total_bob)   || 0;
  const pasivos  = parseFloat(s.pasivos_bob) || 0;
  return {
    fecha:        s.fecha,
    label:        format(parseISO(s.fecha), 'dd/MM'),
    capital_neto: parseFloat((total - pasivos).toFixed(2)),
    total_activos: total,
    efectivo_bob: parseFloat(s.efectivo_bob) || 0,
    divisas_bob:  parseFloat(s.divisas_bob)  || 0,
    tarjetas_bob: parseFloat(s.tarjetas_bob) || 0,
    qr_bob:       parseFloat(s.qr_bob)       || 0,
    pasivos_bob:  pasivos,
    tipo:         s.tipo,
    branch_name:  s.branch_name,
    generado_por: s.generado_por_nombre,
  };
};

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useCapitalTimeline(initialPreset: RangePreset = '30D'): UseCapitalTimelineReturn {
  const [preset, setPresetState]   = useState<RangePreset>(initialPreset);
  const [dateFrom, setDateFrom]    = useState(() => presetRange(initialPreset).from);
  const [dateTo, setDateTo]        = useState(() => presetRange(initialPreset).to);
  const [raw, setRaw]              = useState<CapitalSnapshot[]>([]);
  const [loading, setLoading]      = useState(true);
  const [error, setError]          = useState<string | null>(null);
  const { enqueueSnackbar }        = useSnackbar();

  const fetch = useCallback(async (from: string, to: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get('/capital/snapshots/', {
        params: { date_from: from, date_to: to, ordering: 'fecha', page_size: 500 },
      });
      const list: CapitalSnapshot[] = res.data?.results ?? res.data ?? [];
      setRaw(list.sort((a, b) => a.fecha.localeCompare(b.fecha)));
    } catch (e: any) {
      const msg = e.response?.data?.detail ?? 'Error al cargar historial de capital';
      setError(msg);
      enqueueSnackbar(msg, { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => { fetch(dateFrom, dateTo); }, [dateFrom, dateTo, fetch]);

  const setPreset = useCallback((p: RangePreset) => {
    if (p === 'custom') return; // caller must use setCustomRange
    const { from, to } = presetRange(p);
    setPresetState(p);
    setDateFrom(from);
    setDateTo(to);
  }, []);

  const setCustomRange = useCallback((from: string, to: string) => {
    setPresetState('custom');
    setDateFrom(from);
    setDateTo(to);
  }, []);

  const refresh = useCallback(() => { fetch(dateFrom, dateTo); }, [fetch, dateFrom, dateTo]);

  const data = useMemo(() => raw.map(toPoint), [raw]);

  const stats = useMemo(() => {
    if (data.length === 0) return null;
    const values   = data.map(d => d.capital_neto);
    const latest   = values[values.length - 1];
    const earliest = values[0];
    const delta    = latest - earliest;
    return {
      max:       Math.max(...values),
      min:       Math.min(...values),
      latest,
      earliest,
      delta:     parseFloat(delta.toFixed(2)),
      deltaPct:  earliest !== 0 ? parseFloat(((delta / earliest) * 100).toFixed(2)) : 0,
      count:     data.length,
    };
  }, [data]);

  return {
    data, loading, error,
    dateFrom, dateTo, preset,
    setPreset, setCustomRange, refresh,
    stats,
  };
}
