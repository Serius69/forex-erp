// src/contexts/WebSocketContext.tsx
import React, { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react';
import { useAuth } from './AuthContext';
import { useSnackbar } from 'notistack';

interface WebSocketContextType {
  socket:             WebSocket | null;
  rates:              any;
  alerts:             any[];
  connected:          boolean;
  sendMessage:        (type: string, data?: any) => void;
  // Incrementa cada vez que el servidor emite 'capital_updated'.
  lastCapitalUpdate:  number;
  // Incrementa cuando una migración de Google Sheets finaliza con éxito.
  lastSheetsSync:     number;
  // Última alerta persistida recibida por WebSocket (AlertLog entry).
  // useAlerts() la consume para insertar la alerta sin re-fetch completo.
  newAlertLog:        any | null;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const useWebSocket = () => {
  const context = useContext(WebSocketContext);
  if (!context) throw new Error('useWebSocket must be used within a WebSocketProvider');
  return context;
};

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [socket,            setSocket]            = useState<WebSocket | null>(null);
  const [rates,             setRates]             = useState({});
  const [alerts,            setAlerts]            = useState<any[]>([]);
  const [connected,         setConnected]         = useState(false);
  const [lastCapitalUpdate, setLastCapitalUpdate] = useState<number>(0);
  const [lastSheetsSync,    setLastSheetsSync]    = useState<number>(0);
  const [newAlertLog,       setNewAlertLog]       = useState<any | null>(null);
  const { user }                  = useAuth();
  const { enqueueSnackbar }       = useSnackbar();
  const socketRef    = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef   = useRef(true);

  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN ||
        socketRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }
    if (!mountedRef.current || !user) return;

    const token  = localStorage.getItem('access_token');
    const WS_URL = import.meta.env.VITE_WS_BASE_URL || '/ws';
    // En dev el proxy Vite convierte '/ws' → 'ws://localhost:8000/ws'
    // Si WS_URL ya es relativo, construir URL absoluta con el host actual
    const wsBase = WS_URL.startsWith('ws')
      ? WS_URL
      : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${WS_URL}`;
    const ws     = new WebSocket(`${wsBase}/rates/?token=${token}`);
    socketRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      setConnected(true);
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
    };

    ws.onclose = (event) => {
      setConnected(false);
      socketRef.current = null;
      // Solo reconectar si el componente sigue montado y no fue cierre intencional
      if (mountedRef.current && event.code !== 1000) {
        reconnectRef.current = setTimeout(connect, 5000);
      }
    };

    ws.onerror = (error) => {
      console.warn('WebSocket error:', error);
      ws.close();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case 'rates_update':
            setRates(data.rates ?? data.data ?? {});
            break;

          case 'alert':
          case 'inventory_alert': {
            const alert    = data.alert ?? data.data;
            const severity = alert?.severity === 'CRITICAL' ? 'error'
                           : alert?.severity === 'HIGH'     ? 'warning'
                           : 'info';
            setAlerts((prev) => [alert, ...prev.slice(0, 49)]);
            enqueueSnackbar(alert?.message || 'Nueva alerta', {
              variant:          severity,
              autoHideDuration: 5000,
            });
            break;
          }

          case 'transaction_created':
            enqueueSnackbar('Nueva transacción registrada', {
              variant: 'success', autoHideDuration: 3000,
            });
            break;

          case 'capital_updated':
            // Señal que una transacción afectó el capital — componentes suscritos re-fetch
            setLastCapitalUpdate(Date.now());
            break;

          case 'sheets_sync_complete':
            // Migración de Google Sheets completada — refrescar capital, forex, tarjetas
            setLastSheetsSync(Date.now());
            enqueueSnackbar(
              `Sync completado: ${data.success_rows ?? 0} registros importados`,
              { variant: 'success', autoHideDuration: 5000 },
            );
            break;

          case 'alert_log': {
            // Nueva alerta persistida — notificar UI sin re-fetch completo
            const al = data.alert;
            if (!al) break;
            setNewAlertLog(al);
            const severity   = al.severity ?? 'LOW';
            const variant    = severity === 'CRITICAL' || severity === 'HIGH' ? 'error'
                             : severity === 'MEDIUM' ? 'warning' : 'info';
            enqueueSnackbar(al.title || al.message || 'Nueva alerta', {
              variant, autoHideDuration: 6000,
            });
            break;
          }

          default:
            break;
        }
      } catch (e) {
        console.warn('WebSocket mensaje inválido:', event.data);
      }
    };

    setSocket(ws);
    // Note: socketRef.current is already set above — do not reassign here
  }, [user, enqueueSnackbar]);

  useEffect(() => {
    mountedRef.current = true;
    if (user) connect();

    return () => {
      // ── Cleanup total al desmontar ────────────────────────────────────
      mountedRef.current = false;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (socketRef.current) {
        socketRef.current.close(1000, 'Component unmounted');
        socketRef.current = null;
      }
    };
  }, [user, connect]);

  const sendMessage = useCallback((type: string, data?: any) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type, ...data }));
    }
  }, []);

  return (
    <WebSocketContext.Provider value={{
      socket: socketRef.current, connected, alerts, rates, sendMessage,
      lastCapitalUpdate, lastSheetsSync, newAlertLog,
    }}>
      {children}
    </WebSocketContext.Provider>
  );
};