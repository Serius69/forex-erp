/**
 * useDecisions — Fetches AI pricing decisions for one currency and derives
 * the trading signal (COMPRAR / VENDER / ESPERAR).
 *
 * Data source: GET /rates/ai-pricing/?currency={code}&limit=8
 * Auto-refresh: every 30 s via a single interval (no duplicate requests).
 *
 * Signal derivation:
 *   COMPRAR → stock_pct < 25 OR inventory_factor < 0.997   (low stock)
 *   VENDER  → stock_pct > 75 OR inventory_factor > 1.003   (excess stock)
 *   ESPERAR → neutral zone
 */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { api } from '../services/api';

// ── Shared type (re-exported for components) ──────────────────────────────────

export interface PricingDecision {
  id:                   number;
  currency:             string;
  suggested_buy:        number;
  suggested_sell:       number;
  suggested_spread_pct: number;
  base_rate:            number;
  inventory_factor:     number;
  demand_factor:        number;
  stock_pct:            number | null;
  actual_buy:           number | null;
  actual_sell:          number | null;
  deviation_pct:        number | null;
  recommendation:       string;
  trigger:              string;
  created_at:           string;
  rates_used: {
    bcb?:         number;
    binance?:     number;
    historical?:  number;
    competition?: number;
  };
}

export type DecisionSignal = 'COMPRAR' | 'VENDER' | 'ESPERAR';
export type RiskLevel      = 'ALTO'    | 'MEDIO'  | 'BAJO';

export interface DecisionAnalysis {
  signal:     DecisionSignal;
  confidence: number;                         // 0–100
  risk:       RiskLevel;
  /** last ≤7 suggested_sell values chronologically for the sparkline */
  sparkline: { created_at: string; value: number }[];
}

// ── Derivation helpers ────────────────────────────────────────────────────────

function deriveSignal(d: PricingDecision): DecisionSignal {
  const stock = d.stock_pct ?? 50;
  const inv   = d.inventory_factor;
  if (stock < 25 || inv < 0.997) return 'COMPRAR';
  if (stock > 75 || inv > 1.003) return 'VENDER';
  return 'ESPERAR';
}

function deriveConfidence(d: PricingDecision): number {
  let c  = 50;
  c += Math.min(Math.abs(d.deviation_pct ?? 0) * 8, 25);        // price divergence
  c += Math.abs((d.stock_pct ?? 50) - 50) / 50 * 18;            // stock extremity
  c += Math.min(Math.abs(d.demand_factor - 1) * 200, 7);        // demand signal
  return Math.min(Math.round(c), 98);
}

function deriveRisk(d: PricingDecision): RiskLevel {
  const dev   = Math.abs(d.deviation_pct ?? 0);
  const stock = d.stock_pct ?? 50;
  if (dev > 2   || stock < 10 || stock > 90) return 'ALTO';
  if (dev > 0.5 || stock < 25 || stock > 75) return 'MEDIO';
  return 'BAJO';
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export interface UseDecisionsReturn {
  decisions: PricingDecision[];
  latest:    PricingDecision | null;
  analysis:  DecisionAnalysis | null;
  loading:   boolean;
  error:     string | null;
  /** Manual refresh — safe to call from UI; respects the in-flight guard */
  refresh:   () => void;
}

const POLL_INTERVAL_MS = 30_000;

export function useDecisions(currency: string): UseDecisionsReturn {
  const [decisions, setDecisions] = useState<PricingDecision[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);

  // Guards against concurrent duplicate fetches (React StrictMode, tab focus, etc.)
  const inFlightRef  = useRef(false);
  const intervalRef  = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetch = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const res = await api.get('/rates/ai-pricing/', {
        params: { currency, limit: 8 },
      });
      setDecisions(res.data?.decisions ?? []);
      setError(null);
    } catch (e: any) {
      setError(e.response?.data?.error ?? 'Error al cargar decisiones');
    } finally {
      setLoading(false);
      inFlightRef.current = false;
    }
  }, [currency]);

  useEffect(() => {
    setLoading(true);
    setDecisions([]);
    fetch();
    intervalRef.current = setInterval(fetch, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetch]);

  const latest = decisions[0] ?? null;

  const analysis = useMemo((): DecisionAnalysis | null => {
    if (!latest) return null;
    return {
      signal:     deriveSignal(latest),
      confidence: deriveConfidence(latest),
      risk:       deriveRisk(latest),
      sparkline:  [...decisions].reverse().slice(0, 7).map(d => ({
        created_at: d.created_at,
        value:      d.suggested_sell,
      })),
    };
  }, [latest, decisions]);

  return { decisions, latest, analysis, loading, error, refresh: fetch };
}
