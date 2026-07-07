/**
 * useOfflineSync — manages the offline transaction queue.
 *
 * Behaviour:
 *  - On mount: reads pending count and attempts a flush.
 *  - On AppState 'active' (app returns to foreground): re-attempts flush.
 *  - On network reconnect (NetInfo offline → online): re-attempts flush.
 *  - Exposes sync() for manual retries and refreshCount() for count updates.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import { transactionsApi } from '../services/api';
import { offlineQueue, FlushResult } from '../services/offlineQueue';

export interface UseOfflineSyncReturn {
  pendingCount: number;
  isSyncing:    boolean;
  sync:         () => Promise<FlushResult>;
  refreshCount: () => Promise<void>;
}

export function useOfflineSync(): UseOfflineSyncReturn {
  const [pendingCount, setPendingCount] = useState(0);
  const [isSyncing,    setIsSyncing]    = useState(false);
  const isSyncingRef                    = useRef(false);
  const appStateRef                     = useRef<AppStateStatus>(AppState.currentState);

  const refreshCount = useCallback(async () => {
    const n = await offlineQueue.count();
    setPendingCount(n);
  }, []);

  const sync = useCallback(async (): Promise<FlushResult> => {
    if (isSyncingRef.current) return { ok: 0, failed: 0 };
    isSyncingRef.current = true;
    setIsSyncing(true);
    try {
      const result = await offlineQueue.flush(
        (payload, pin) => transactionsApi.create(payload, pin).then(r => r.transaction),
      );
      await refreshCount();
      return result;
    } catch {
      return { ok: 0, failed: 0 };
    } finally {
      isSyncingRef.current = false;
      setIsSyncing(false);
    }
  }, [refreshCount]);

  // Initial load + opportunistic flush on mount
  useEffect(() => {
    refreshCount();
    sync(); // silent — fails gracefully if still offline
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-flush when app returns to foreground
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (next === 'active' && appStateRef.current !== 'active') {
        sync();
      }
      appStateRef.current = next;
    });
    return () => sub.remove();
  }, [sync]);

  // Auto-flush on real reconnection (NetInfo offline → online)
  const wasOfflineRef = useRef(false);
  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener(state => {
      const online = !!state.isConnected && state.isInternetReachable !== false;
      if (online && wasOfflineRef.current) {
        sync();
      }
      wasOfflineRef.current = !online;
    });
    return () => unsubscribe();
  }, [sync]);

  return { pendingCount, isSyncing, sync, refreshCount };
}
