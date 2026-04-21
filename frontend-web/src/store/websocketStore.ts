// src/store/websocketStore.ts
/**
 * Zustand store for WebSocket real-time state.
 * Replaces the WebSocketContext for global WS state management.
 * Keeps Redux for server-fetched data; Zustand for live/ephemeral WS state.
 */
import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface RateData {
  code: string;
  name?: string;
  buy: number;
  sell: number;
  official: number;
  market_type: string;
  scale_factor?: number;
}

export interface AlertData {
  id?: number;
  source: string;
  alert_type: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  title: string;
  message: string;
  accion_sugerida?: string;
  data?: Record<string, unknown>;
  created_at?: string;
  is_acknowledged?: boolean;
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface WebSocketState {
  // Connection
  socket: WebSocket | null;
  status: ConnectionStatus;
  reconnectAttempts: number;
  lastPing: Date | null;

  // Live data
  rates: Record<string, RateData>;
  alerts: AlertData[];
  lastCapitalUpdate: Date | null;
  lastSheetsSync: Date | null;
  newAlertLog: AlertData | null;

  // Actions
  connect: (token: string) => void;
  disconnect: () => void;
  acknowledgeAlert: (index: number) => void;
  clearAlerts: () => void;
  sendMessage: (msg: Record<string, unknown>) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_BASE_DELAY_MS = 2_000;
const WS_BASE = (() => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = import.meta.env.VITE_WS_HOST || window.location.host;
  return `${protocol}//${host}`;
})();

let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

// ─────────────────────────────────────────────────────────────────────────────
// Store
// ─────────────────────────────────────────────────────────────────────────────

export const useWebSocketStore = create<WebSocketState>()(
  subscribeWithSelector((set, get) => ({
    socket: null,
    status: 'disconnected',
    reconnectAttempts: 0,
    lastPing: null,
    rates: {},
    alerts: [],
    lastCapitalUpdate: null,
    lastSheetsSync: null,
    newAlertLog: null,

    connect(token: string) {
      const { socket, reconnectAttempts } = get();

      // Close existing connection
      if (socket && socket.readyState < WebSocket.CLOSING) {
        socket.close();
      }

      if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        set({ status: 'error' });
        return;
      }

      set({ status: 'connecting' });

      const ws = new WebSocket(`${WS_BASE}/ws/rates/?token=${token}`);

      ws.onopen = () => {
        set({ status: 'connected', reconnectAttempts: 0, lastPing: new Date() });
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data as string) as Record<string, unknown>;
          _handleMessage(msg, set);
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        set((s) => ({ status: 'disconnected', socket: null }));
        _scheduleReconnect(token, get, set);
      };

      ws.onerror = () => {
        set({ status: 'error' });
        ws.close();
      };

      set({ socket: ws });
    },

    disconnect() {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      const { socket } = get();
      if (socket) {
        socket.close();
      }
      set({ socket: null, status: 'disconnected', reconnectAttempts: 0 });
    },

    acknowledgeAlert(index: number) {
      set((s) => ({
        alerts: s.alerts.map((a, i) =>
          i === index ? { ...a, is_acknowledged: true } : a
        ),
      }));
    },

    clearAlerts() {
      set({ alerts: [] });
    },

    sendMessage(msg: Record<string, unknown>) {
      const { socket } = get();
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(msg));
      }
    },
  }))
);

// ─────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────────

type SetFn = Parameters<Parameters<typeof useWebSocketStore>[0]>[0];

function _handleMessage(msg: Record<string, unknown>, set: SetFn) {
  const type = msg.type as string;

  switch (type) {
    case 'rates_update': {
      const incoming = msg.rates as Record<string, RateData>;
      if (incoming) {
        set((s) => ({ rates: { ...s.rates, ...incoming } }));
      }
      break;
    }

    case 'alert':
    case 'inventory_alert': {
      const alert = msg as unknown as AlertData;
      set((s) => ({
        alerts: [alert, ...s.alerts].slice(0, 50), // keep last 50
      }));
      break;
    }

    case 'alert_log': {
      const log = msg.alert as AlertData;
      if (log) {
        set({ newAlertLog: log });
        set((s) => ({
          alerts: [log, ...s.alerts].slice(0, 50),
        }));
      }
      break;
    }

    case 'capital_updated': {
      set({ lastCapitalUpdate: new Date() });
      break;
    }

    case 'sheets_sync_complete': {
      set({ lastSheetsSync: new Date() });
      break;
    }

    case 'pong': {
      set({ lastPing: new Date() });
      break;
    }

    default:
      break;
  }
}

function _scheduleReconnect(
  token: string,
  get: () => WebSocketState,
  set: SetFn
) {
  const attempts = get().reconnectAttempts;
  if (attempts >= MAX_RECONNECT_ATTEMPTS) return;

  const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** attempts, 30_000);
  reconnectTimer = setTimeout(() => {
    set((s) => ({ reconnectAttempts: s.reconnectAttempts + 1 }));
    get().connect(token);
  }, delay);
}

// ─────────────────────────────────────────────────────────────────────────────
// Selector hooks (memoized slices)
// ─────────────────────────────────────────────────────────────────────────────

export const useRates = () => useWebSocketStore((s) => s.rates);
export const useAlerts = () => useWebSocketStore((s) => s.alerts);
export const useWsStatus = () => useWebSocketStore((s) => s.status);
export const useWsConnect = () => useWebSocketStore((s) => s.connect);
export const useWsDisconnect = () => useWebSocketStore((s) => s.disconnect);
