// src/contexts/WebSocketContext.tsx
import React, { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react';
import { useAuth } from './AuthContext';
import { useSnackbar } from 'notistack';

interface WebSocketContextType {
  socket:    WebSocket | null;
  rates:     any;
  alerts:    any[];
  connected: boolean;
  sendMessage: (type: string, data?: any) => void;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const useWebSocket = () => {
  const context = useContext(WebSocketContext);
  if (!context) throw new Error('useWebSocket must be used within a WebSocketProvider');
  return context;
};

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [socket,    setSocket]    = useState<WebSocket | null>(null);
  const [rates,     setRates]     = useState({});
  const [alerts,    setAlerts]    = useState<any[]>([]);
  const [connected, setConnected] = useState(false);
  const reconnectTimer            = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { user }                  = useAuth();
  const { enqueueSnackbar }       = useSnackbar();

  const connect = useCallback(() => {
    if (!user) return;

    const token = localStorage.getItem('access_token');
    const WS_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000';
    const url    = `${WS_URL}/ws/rates/?token=${token}`;

    const ws = new WebSocket(url);

    ws.onopen = () => {
      console.log('WebSocket conectado');
      setConnected(true);
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };

    ws.onclose = () => {
      console.log('WebSocket desconectado — reintentando en 5s');
      setConnected(false);
      setSocket(null);
      // Reconectar automáticamente
      reconnectTimer.current = setTimeout(connect, 5000);
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

          default:
            break;
        }
      } catch (e) {
        console.warn('WebSocket mensaje inválido:', event.data);
      }
    };

    setSocket(ws);
  }, [user, enqueueSnackbar]);

  useEffect(() => {
    if (user) connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (socket) socket.close();
    };
  }, [user]); // eslint-disable-line react-hooks/exhaustive-deps

  const sendMessage = useCallback((type: string, data?: any) => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type, ...data }));
    }
  }, [socket]);

  return (
    <WebSocketContext.Provider value={{ socket, rates, alerts, connected, sendMessage }}>
      {children}
    </WebSocketContext.Provider>
  );
};