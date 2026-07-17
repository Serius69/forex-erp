/**
 * useApiQuery — hook universal para fetch + loading + error + retry + stale
 *
 * Uso:
 *   const { data, loading, error, retry, isStale } = useApiQuery(
 *     () => api.get('/api/rates/live/'),
 *     [dependency]
 *   );
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { AxiosResponse } from 'axios';
import { AppError, isAppError } from '../services/errorTypes';

interface QueryState<T> {
  data:     T | null;
  loading:  boolean;
  error:    AppError | null;
  isStale:  boolean;
  retry:    () => void;
}

type FetchFn<T> = () => Promise<AxiosResponse<T>>;

export function useApiQuery<T>(
  fetchFn: FetchFn<T>,
  deps: unknown[] = [],
  options: {
    initialData?:   T;
    pollInterval?:  number;   // ms — 0 = no polling
    enabled?:       boolean;
  } = {},
): QueryState<T> {
  const { initialData = null, pollInterval = 0, enabled = true } = options;

  const [data,    setData]    = useState<T | null>(initialData as T | null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [error,   setError]   = useState<AppError | null>(null);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [tick,    setTick]    = useState(0);    // incrementar para forzar refetch
  const mountedRef = useRef(true);
  const lastFetchRef = useRef<number>(0);

  const execute = useCallback(async () => {
    if (!enabled) return;
    if (!mountedRef.current) return;

    setLoading(true);
    setError(null);

    try {
      const response = await fetchFn();
      if (!mountedRef.current) return;
      setData(response.data);
      setIsStale(false);
      lastFetchRef.current = Date.now();
    } catch (err) {
      if (!mountedRef.current) return;
      if (isAppError(err)) {
        setError(err);
      } else {
        setError({ code: 'UNKNOWN_ERROR', message: String(err), errorId: 'hook-err' });
      }
      // Keep stale data if available
      if (data !== null) setIsStale(true);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, tick, ...deps]);

  useEffect(() => {
    mountedRef.current = true;
    execute();
    return () => { mountedRef.current = false; };
  }, [execute]);

  // Polling fallback
  useEffect(() => {
    if (!pollInterval || pollInterval <= 0 || !enabled) return;
    const id = setInterval(() => {
      if (mountedRef.current) setTick((t) => t + 1);
    }, pollInterval);
    return () => clearInterval(id);
  }, [pollInterval, enabled]);

  const retry = useCallback(() => setTick((t) => t + 1), []);

  return { data, loading, error, isStale, retry };
}

export default useApiQuery;
