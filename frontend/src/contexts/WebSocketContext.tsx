import React, { createContext, useContext, useEffect, useState } from 'react';
import { io, Socket } from 'socket.io-client';
import { useAuth } from './AuthContext';
import { useSnackbar } from 'notistack';

interface WebSocketContextType {
  socket: Socket | null;
  rates: any;
  alerts: any[];
  connected: boolean;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const useWebSocket = () => {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocket must be used within a WebSocketProvider');
  }
  return context;
};

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [rates, setRates] = useState({});
  const [alerts, setAlerts] = useState<any[]>([]);
  const [connected, setConnected] = useState(false);
  const { user } = useAuth();
  const { enqueueSnackbar } = useSnackbar();

  useEffect(() => {
    if (!user) return;

    const token = localStorage.getItem('access_token');
    const wsUrl = process.env.REACT_APP_WS_URL || 'ws://localhost:8000';

    const newSocket = io(wsUrl, {
      auth: {
        token,
      },
      transports: ['websocket'],
    });

    newSocket.on('connect', () => {
      console.log('WebSocket connected');
      setConnected(true);
    });

    newSocket.on('disconnect', () => {
      console.log('WebSocket disconnected');
      setConnected(false);
    });

    newSocket.on('rates_update', (data) => {
      setRates(data.rates);
    });

    newSocket.on('alert', (data) => {
      setAlerts((prev) => [data.alert, ...prev]);
      
      // Mostrar notificación
      const severity = data.alert.severity === 'CRITICAL' ? 'error' : 
                      data.alert.severity === 'HIGH' ? 'warning' : 'info';
      
      enqueueSnackbar(data.alert.message, { 
        variant: severity,
        autoHideDuration: 5000,
      });
    });

    setSocket(newSocket);

    return () => {
      newSocket.close();
    };
  }, [user, enqueueSnackbar]);

  return (
    <WebSocketContext.Provider value={{ socket, rates, alerts, connected }}>
      {children}
    </WebSocketContext.Provider>
  );
};