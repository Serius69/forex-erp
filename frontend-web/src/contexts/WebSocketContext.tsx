// src/contexts/WebSocketContext.tsx
// WebSocket con exponential backoff, polling fallback y estado stale
import React, { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react';
import { useAuth } from './AuthContext';
import { getAccessToken } from '../services/api';
import { useSnackbar } from 'notistack';

// ── Backoff exponencial ───────────────────────────────────────────────────────
const WS_MAX_RETRIES      = 5;
const WS_BASE_DELAY_MS    = 1_000;
const WS_MAX_DELAY_MS     = 30_000;
const WS_POLL_INTERVAL_MS = 30_000;  // fallback polling cada 30s cuando WS está caído

function wsBackoffDelay(attempt: number): number {
  const delay = WS_BASE_DELAY_MS * Math.pow(2, attempt);
  return Math.min(delay + Math.random() * 500, WS_MAX_DELAY_MS);
}

// ── Tipos ─────────────────────────────────────────────────────────────────────

type WsStatus = 'connected' | 'reconnecting' | 'disconnected' | 'polling';

interface WebSocketContextType {
  socket:             WebSocket | null;
  rates:              any;
  alerts:             any[];
  connected:          boolean;
  wsStatus:           WsStatus;
  isRatesStale:       boolean;
  ratesAge:           number;         // ms desde la última actualización de tasas
  sendMessage:        (type: string, data?: any) => void;
  lastCapitalUpdate:  number;
  lastSheetsSync:     number;
  newAlertLog:        any | null;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const useWebSocket = () => {
  const ctx = useContext(WebSocketContext);
  if (!ctx) throw new Error('useWebSocket must be used within a WebSocketProvider');
  return ctx;
};

// ── Provider ──────────────────────────────────────────────────────────────────

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [socket,            setSocket]            = useState<WebSocket | null>(null);
  const [rates,             setRates]             = useState({});
  const [alerts,            setAlerts]            = useState<any[]>([]);
  const [wsStatus,          setWsStatus]          = useState<WsStatus>('disconnected');
  const [ratesUpdatedAt,    setRatesUpdatedAt]    = useState<number>(0);
  const [lastCapitalUpdate, setLastCapitalUpdate] = useState<number>(0);
  const [lastSheetsSync,    setLastSheetsSync]    = useState<number>(0);
  const [newAlertLog,       setNewAlertLog]       = useState<any | null>(null);

  const { user }            = useAuth();
  const { enqueueSnackbar } = useSnackbar();

  const socketRef    = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollRef      = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef   = useRef(true);
  const retriesRef   = useRef(0);

  // ── Polling fallback ───────────────────────────────────────────────────────
  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    setWsStatus('polling');
    pollRef.current = setInterval(async () => {
      if (!mountedRef.current) return;
      try {
        const res = await fetch('/api/rates/live/', { headers: { 'Cache-Control': 'no-cache' } });
        if (res.ok) {
          const data = await res.json();
          if (mountedRef.current) {
            setRates(data);
            setRatesUpdatedAt(Date.now());
          }
        }
      } catch { /* offline — ignore */ }
    }, WS_POLL_INTERVAL_MS);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // ── Conexión WebSocket ─────────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN ||
        socketRef.current?.readyState === WebSocket.CONNECTING) return;
    if (!mountedRef.current || !user) return;

    const token = getAccessToken();
    if (!token) { setTimeout(connect, 500); return; }

    const WS_URL = import.meta.env.VITE_WS_BASE_URL || '/ws';
    const wsBase = WS_URL.startsWith('ws')
      ? WS_URL
      : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${WS_URL}`;

    const companyId = user?.company_id ?? '';
    const branchId  = user?.branch_id  ?? '';
    const wsUrl     = `${wsBase}/rates/?token=${token}&company=${companyId}&branch=${branchId}`;

    setWsStatus('reconnecting');
    const ws = new WebSocket(wsUrl);
    socketRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      retriesRef.current = 0;
      setWsStatus('connected');
      stopPolling();
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      setSocket(ws);
    };

    ws.onclose = (event) => {
      if (!mountedRef.current) return;
      socketRef.current = null;
      setSocket(null);

      // Cierre intencional (código 1000) → no reconectar
      if (event.code === 1000) { setWsStatus('disconnected'); return; }

      retriesRef.current += 1;

      if (retriesRef.current > WS_MAX_RETRIES) {
        // Agotados los reintentos → polling fallback
        setWsStatus('polling');
        startPolling();
        // Mostrar aviso sutil al usuario
        enqueueSnackbar('Conexión en tiempo real no disponible. Datos en modo manual (30s).', {
          variant: 'warning', autoHideDuration: 6000,
        });
        return;
      }

      const delay = wsBackoffDelay(retriesRef.current - 1);
      setWsStatus('reconnecting');
      reconnectRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => { ws.close(); };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleMessage(data);
      } catch { /* invalid JSON — ignore */ }
    };
  }, [user, enqueueSnackbar, startPolling, stopPolling]);

  // ── Manejo de mensajes ─────────────────────────────────────────────────────
  const handleMessage = useCallback((data: any) => {
    switch (data.type) {
      case 'rates_update':
        setRates(data.rates ?? data.data ?? {});
        setRatesUpdatedAt(Date.now());
        break;

      case 'alert':
      case 'inventory_alert': {
        const alert    = data.alert ?? data.data;
        const severity = alert?.severity === 'CRITICAL' ? 'error'
                       : alert?.severity === 'HIGH'     ? 'warning' : 'info';
        setAlerts((prev) => [alert, ...prev.slice(0, 49)]);
        enqueueSnackbar(alert?.message || 'Nueva alerta', { variant: severity, autoHideDuration: 5000 });
        break;
      }

      case 'transaction_created':
        enqueueSnackbar('Nueva transacción registrada', { variant: 'success', autoHideDuration: 3000 });
        break;

      case 'capital_updated':
        setLastCapitalUpdate(Date.now());
        break;

      case 'sheets_sync_complete':
        setLastSheetsSync(Date.now());
        enqueueSnackbar(`Sync completado: ${data.success_rows ?? 0} registros importados`, { variant: 'success', autoHideDuration: 5000 });
        break;

      case 'alert_log': {
        const al = data.alert;
        if (!al) break;
        setNewAlertLog(al);
        const sev     = al.severity ?? 'LOW';
        const variant = sev === 'CRITICAL' || sev === 'HIGH' ? 'error' : sev === 'MEDIUM' ? 'warning' : 'info';
        enqueueSnackbar(al.title || al.message || 'Nueva alerta', { variant, autoHideDuration: 6000 });
        break;
      }

      default: break;
    }
  }, [enqueueSnackbar]);

  useEffect(() => {
    mountedRef.current = true;
    if (user) connect();
    return () => {
      mountedRef.current = false;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      stopPolling();
      if (socketRef.current) {
        socketRef.current.close(1000, 'Component unmounted');
        socketRef.current = null;
      }
    };
  }, [user, connect, stopPolling]);

  // Reconectar cuando el usuario vuelve online
  useEffect(() => {
    const handleOnline = () => {
      if (wsStatus !== 'connected') {
        retriesRef.current = 0;
        stopPolling();
        connect();
      }
    };
    window.addEventListener('online', handleOnline);
    return () => window.removeEventListener('online', handleOnline);
  }, [wsStatus, connect, stopPolling]);

  const sendMessage = useCallback((type: string, data?: any) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type, ...data }));
    }
  }, []);

  const connected     = wsStatus === 'connected';
  const ratesAge      = ratesUpdatedAt ? Date.now() - ratesUpdatedAt : 0;
  // Stale si los datos tienen más de 2 minutos y WS no está activo
  const isRatesStale  = !connected && ratesAge > 120_000;

  return (
    <WebSocketContext.Provider value={{
      socket: socketRef.current, connected, wsStatus, isRatesStale, ratesAge,
      alerts, rates, sendMessage,
      lastCapitalUpdate, lastSheetsSync, newAlertLog,
    }}>
      {children}
    </WebSocketContext.Provider>
  );
};
