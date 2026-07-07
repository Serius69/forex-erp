/**
 * useRatesWebSocket — hook para conectarse al feed de consenso en tiempo real.
 *
 * Conecta a /ws/rates-live/ y mantiene reconexión automática con backoff exponencial.
 * Retorna el estado actual del consenso, estado de conexión y timestamp del último update.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { getAccessToken } from '../services/api';

export interface ConsensusPar {
  consenso:     number;
  compra:       number | null;
  venta:        number | null;
  fuentes:      number;
  confianza:    number;
  cambio_pct:   number;
  tendencia:    'ALCISTA' | 'BAJISTA' | 'NEUTRAL';
}

export interface RatesWsState {
  rates:       Record<string, ConsensusPar>;
  connected:   boolean;
  lastUpdate:  string | null;
}

const WS_BASE = (() => {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host  = (window as any).__WS_HOST__ || window.location.host;
  return `${proto}//${host}`;
})();

const INITIAL_DELAY = 1000;
const MAX_DELAY     = 30_000;

export function useRatesWebSocket(): RatesWsState {
  const [rates,      setRates]      = useState<Record<string, ConsensusPar>>({});
  const [connected,  setConnected]  = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);

  const wsRef    = useRef<WebSocket | null>(null);
  const delayRef = useRef(INITIAL_DELAY);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmounted = useRef(false);

  const connect = useCallback(() => {
    if (unmounted.current) return;

    const token = getAccessToken();
    const url   = `${WS_BASE}/ws/rates-live/${token ? `?token=${token}` : ''}`;
    const ws    = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmounted.current) { ws.close(); return; }
      setConnected(true);
      delayRef.current = INITIAL_DELAY;
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'rates_update' && msg.pares) {
          setRates(msg.pares as Record<string, ConsensusPar>);
          setLastUpdate(msg.timestamp || new Date().toISOString());
        }
      } catch (_) { /* ignore parse errors */ }
    };

    ws.onclose = () => {
      if (unmounted.current) return;
      setConnected(false);
      wsRef.current = null;
      // Backoff exponencial: 1s → 2s → 4s → … → 30s
      timerRef.current = setTimeout(() => {
        delayRef.current = Math.min(delayRef.current * 2, MAX_DELAY);
        connect();
      }, delayRef.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    unmounted.current = false;
    connect();
    return () => {
      unmounted.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { rates, connected, lastUpdate };
}
