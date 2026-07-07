/**
 * BranchScopeContext — selector global de sucursal para ADMIN.
 *
 * ADMIN puede ver los datos de una sucursal específica o de todas
 * (branchId = null). Los demás roles quedan fijados a su propia sucursal
 * (el backend ignora/valida branch_id según rol, esto es solo UI).
 *
 * La selección se persiste en localStorage para sobrevivir recargas.
 */
import React, {
  createContext, useContext, useState, useEffect, useCallback, useMemo,
} from 'react';
import api from '../services/api';
import { useAuth } from './AuthContext';
import type { Branch } from '../types';

const STORAGE_KEY = 'kapitalya_branch_scope';

interface BranchScopeContextType {
  /** Sucursal seleccionada (null = todas las sucursales — solo ADMIN). */
  branchId: number | null;
  setBranchId: (id: number | null) => void;
  /** Sucursales activas de la empresa (solo se carga para ADMIN). */
  branches: Branch[];
  /** true si el usuario puede cambiar de sucursal. */
  canSelectBranch: boolean;
  /**
   * Params listos para axios: { branch_id } si hay selección, {} si no.
   * Uso: api.get('/capital/actual/', { params: { ...branchParams } })
   */
  branchParams: Record<string, number>;
}

const BranchScopeContext = createContext<BranchScopeContextType>({
  branchId: null,
  setBranchId: () => undefined,
  branches: [],
  canSelectBranch: false,
  branchParams: {},
});

export const BranchScopeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  const canSelectBranch = user?.role === 'ADMIN';

  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchId, setBranchIdState] = useState<number | null>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? Number(stored) || null : null;
  });

  // Cargar sucursales de la empresa — solo tiene sentido para ADMIN.
  useEffect(() => {
    if (!canSelectBranch) return;
    let cancelled = false;
    api.get('/users/branches/')
      .then(res => {
        if (cancelled) return;
        const list: Branch[] = res.data?.results ?? res.data ?? [];
        setBranches(list);
        // Si la selección persistida ya no existe, volver a "todas".
        setBranchIdState(prev =>
          prev && !list.some(b => b.id === prev) ? null : prev
        );
      })
      .catch(() => { /* sin sucursales — el selector simplemente no se muestra */ });
    return () => { cancelled = true; };
  }, [canSelectBranch]);

  const setBranchId = useCallback((id: number | null) => {
    setBranchIdState(id);
    if (id) localStorage.setItem(STORAGE_KEY, String(id));
    else localStorage.removeItem(STORAGE_KEY);
  }, []);

  const value = useMemo<BranchScopeContextType>(() => {
    const effectiveId = canSelectBranch ? branchId : (user?.branch_id ?? null);
    const branchParams: Record<string, number> =
      canSelectBranch && branchId ? { branch_id: branchId } : {};
    return {
      branchId: effectiveId,
      setBranchId,
      branches,
      canSelectBranch,
      branchParams,
    };
  }, [branchId, setBranchId, branches, canSelectBranch, user?.branch_id]);

  return (
    <BranchScopeContext.Provider value={value}>
      {children}
    </BranchScopeContext.Provider>
  );
};

export const useBranchScope = (): BranchScopeContextType => useContext(BranchScopeContext);
