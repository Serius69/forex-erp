/**
 * useDashboard — Centralizes the four parallel fetches for the Capital tabs:
 *   - /capital/actual/
 *   - /capital/gastos/
 *   - /capital/gastos/resumen/
 *   - /capital/snapshots/   (admin/supervisor only)
 *
 * Extracted from Capital.tsx to keep that component focused on rendering.
 */
import { useState, useEffect, useCallback } from 'react';
import { useSnackbar } from 'notistack';
import { api } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { useWebSocket } from '../contexts/WebSocketContext';
import { useBranchScope } from '../contexts/BranchScopeContext';

// ── Exported types (moved from Capital.tsx) ───────────────────────────────────

export interface DetalleDivisa {
  stock: string; tc_venta: string; valor_bob: string;
  tc_compra: string; branch: string;
}

export interface CapitalActual {
  efectivo_bob: string; qr_bob: string; divisas_bob: string;
  tarjetas_bob: string; pasivos_bob: string; total_bob: string;
  detalle_divisas: Record<string, DetalleDivisa>;
  detalle_tarjetas: Record<string, any>;
  calculado_en: string; advertencias: string[];
}

export interface Gasto {
  id: number; fecha: string; categoria: string;
  descripcion: string; monto_bob: string; medio_pago: string;
  proveedor: string; nro_factura: string; branch_name: string;
}

export interface ResumenGastos {
  total_bob: string; total_gastos: number;
  por_categoria: { categoria: string; total: string; count: number }[];
}

export interface IngresoExtra {
  id: number; fecha: string; tipo: string;
  monto_bob: string; medio_pago: string; notas: string; branch_nombre: string;
}

export interface ResumenIngresos {
  total_bob: string; total_ingresos: number;
  por_tipo: { tipo: string; total: string; count: number }[];
}

export interface CapitalSnapshot {
  id: number; fecha: string; branch_name: string;
  efectivo_bob: string; qr_bob: string; divisas_bob: string;
  tarjetas_bob: string; pasivos_bob: string; total_bob: string;
  tipo: string; generado_por_nombre: string; created_at: string;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

interface UseDashboardReturn {
  capital: CapitalActual | null;
  gastos: Gasto[];
  resumenGastos: ResumenGastos | null;
  ingresos: IngresoExtra[];
  resumenIngresos: ResumenIngresos | null;
  snapshots: CapitalSnapshot[];
  loading: boolean;
  canSnapshot: boolean;
  refresh: () => Promise<void>;
}

export function useDashboard(dateFrom: string, dateTo: string): UseDashboardReturn {
  const [capital, setCapital]             = useState<CapitalActual | null>(null);
  const [gastos, setGastos]               = useState<Gasto[]>([]);
  const [resumenGastos, setResumenGastos] = useState<ResumenGastos | null>(null);
  const [ingresos, setIngresos]           = useState<IngresoExtra[]>([]);
  const [resumenIngresos, setResumenIngresos] = useState<ResumenIngresos | null>(null);
  const [snapshots, setSnapshots]         = useState<CapitalSnapshot[]>([]);
  const [loading, setLoading]             = useState(true);
  const { user }                          = useAuth();
  const { enqueueSnackbar }               = useSnackbar();
  const { lastSheetsSync }                = useWebSocket();
  const { branchParams }                  = useBranchScope();

  const canSnapshot = user?.role === 'ADMIN' || user?.role === 'SUPERVISOR';

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [capitalRes, gastosRes, resumenRes, ingresosRes, resumenIngRes, snapshotsRes] = await Promise.all([
        api.get('/capital/actual/', { params: branchParams }),
        api.get('/capital/gastos/', { params: { date_from: dateFrom, date_to: dateTo } }),
        api.get('/capital/gastos/resumen/', { params: { date_from: dateFrom, date_to: dateTo } }),
        api.get('/capital/ingresos/', { params: { date_from: dateFrom, date_to: dateTo } }),
        api.get('/capital/ingresos/resumen/', { params: { date_from: dateFrom, date_to: dateTo } }),
        canSnapshot
          ? api.get('/capital/snapshots/', { params: { date_from: dateFrom, date_to: dateTo } })
          : Promise.resolve({ data: { results: [] } }),
      ]);
      setCapital(capitalRes.data);
      setGastos(gastosRes.data?.results ?? gastosRes.data ?? []);
      setResumenGastos(resumenRes.data);
      setIngresos(ingresosRes.data?.results ?? ingresosRes.data ?? []);
      setResumenIngresos(resumenIngRes.data);
      setSnapshots(snapshotsRes.data?.results ?? snapshotsRes.data ?? []);
    } catch {
      enqueueSnackbar('Error al cargar datos de capital', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, canSnapshot, enqueueSnackbar, branchParams]);

  useEffect(() => { refresh(); }, [refresh]);

  // Google Sheets sync completed → full re-fetch.
  useEffect(() => {
    if (!lastSheetsSync) return;
    refresh();
  }, [lastSheetsSync, refresh]);

  return { capital, gastos, resumenGastos, ingresos, resumenIngresos, snapshots, loading, canSnapshot, refresh };
}
