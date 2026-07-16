/**
 * useCapital — Single source of truth for /capital/resumen-capital/ and
 * /capital/composicion/hoy/ data.
 *
 * Consolidates three previously scattered fetch sites in CapitalDashboard.tsx:
 *   1. Initial mount load (was duplicated inline in the component)
 *   2. WebSocket `capital_updated` re-fetch (was copy-pasting the Promise.all)
 *   3. Rate-change debounced refresh (only resumen-capital, composicion is unaffected by rates)
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../services/api';
import { useWebSocket } from '../contexts/WebSocketContext';
import { useBranchScope } from '../contexts/BranchScopeContext';

// ── Exported types (moved from CapitalDashboard.tsx) ──────────────────────────

export interface DivisaItem {
  code: string; name: string; scale_factor: number;
  stock: string; tc_venta_unit: string; tc_venta_lote: string;
  tc_compra_lote: string; valor_bob: string; market_type: string;
}

export interface Efectivo {
  fuertes: string; caja_chica: string; monedas: string;
  rotos: string; sueltos: string; total: string;
}

export interface Digital {
  qr_transferencias: string; tarjetas_telefonicas: string; total: string;
}

export interface TarjetaModulo {
  stock: number; precio_prom: string; valor_bob: string;
}

export interface CapitalResumen {
  capital_neto: string; total_activos: string; total_pasivos: string;
  divisas: Record<string, DivisaItem>;
  efectivo: Efectivo;
  digital: Digital;
  tarjetas_modulo: Record<string, TarjetaModulo>;
  totales: { divisas_bob: string; efectivo_bob: string; digital_bob: string; tarjetas_bob: string };
  desglose: { pct_divisas: string; pct_efectivo: string; pct_digital: string; pct_tarjetas: string };
  advertencias: string[];
  calculado_en: string;
}

export interface ComposicionHoy {
  id: number | null; fecha: string;
  fuertes: string; caja_chica: string; monedas: string;
  rotos: string; sueltos: string;
  qr_transferencias: string; tarjetas_telefonicas: string;
  pasivos: string; notas: string;
  total_efectivo: string; total_digital: string;
  total_activos: string; capital_neto_local: string;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

interface UseCapitalReturn {
  capital: CapitalResumen | null;
  composicion: ComposicionHoy | null;
  loading: boolean;
  error: string | null;
  connected: boolean;
  refresh: () => Promise<void>;
}

export function useCapital(): UseCapitalReturn {
  const [capital, setCapital]         = useState<CapitalResumen | null>(null);
  const [composicion, setComposicion] = useState<ComposicionHoy | null>(null);
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState<string | null>(null);
  const debounceRef                   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { rates, connected, lastCapitalUpdate, lastSheetsSync } = useWebSocket();
  const { branchParams }              = useBranchScope();

  // Single fetch function — ONE request per data source per invocation.
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [capRes, compRes] = await Promise.all([
        api.get('/capital/resumen-capital/', { params: branchParams }),
        api.get('/capital/composicion/hoy/'),
      ]);
      setCapital(capRes.data);
      setComposicion(compRes.data);
    } catch (e: any) {
      // 404 = aún sin composición registrada (no es un error de carga)
      if (e.response?.status !== 404) {
        setError('No se pudo cargar el capital. Verifica tu conexión e intenta de nuevo.');
      }
    } finally {
      setLoading(false);
    }
  }, [branchParams]);

  // Initial load.
  useEffect(() => { refresh(); }, [refresh]);

  // WebSocket: transaction processed → immediate full re-fetch.
  useEffect(() => {
    if (!lastCapitalUpdate) return;
    refresh();
  }, [lastCapitalUpdate, refresh]);

  // WebSocket: Google Sheets sync completed → full re-fetch.
  useEffect(() => {
    if (!lastSheetsSync) return;
    refresh();
  }, [lastSheetsSync, refresh]);

  // WebSocket: rate change → only resumen-capital needs updating (composicion is
  // cash counts unaffected by FX rates). Debounced 1.5s to absorb rate bursts.
  useEffect(() => {
    if (!connected || Object.keys(rates).length === 0) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      api.get('/capital/resumen-capital/', { params: branchParams })
        .then(r => setCapital(r.data))
        .catch(() => {});
    }, 1500);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [rates, connected, branchParams]);

  return { capital, composicion, loading, error, connected, refresh };
}
