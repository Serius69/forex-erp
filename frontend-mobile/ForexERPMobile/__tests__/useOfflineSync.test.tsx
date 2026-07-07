/**
 * Tests de useOfflineSync — sync automático al reconectar (NetInfo).
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { describe, it, expect, beforeEach, jest } from '@jest/globals';
import NetInfo from '@react-native-community/netinfo';
import { useOfflineSync } from '../src/hooks/useOfflineSync';

jest.mock('../src/services/api', () => ({
  transactionsApi: { create: jest.fn() },
}));

jest.mock('../src/services/offlineQueue', () => ({
  offlineQueue: {
    count: jest.fn(() => Promise.resolve(0)),
    flush: jest.fn(() => Promise.resolve({ ok: 0, failed: 0 })),
  },
}));

const { offlineQueue } = jest.requireMock('../src/services/offlineQueue') as {
  offlineQueue: { count: any; flush: any };
};

function Probe(): null {
  useOfflineSync();
  return null;
}

/** Último listener registrado en NetInfo.addEventListener. */
function netInfoListener(): (state: any) => void {
  const calls = (NetInfo.addEventListener as any).mock.calls;
  return calls[calls.length - 1][0];
}

describe('useOfflineSync + NetInfo', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('dispara sync cuando la red pasa de offline a online', async () => {
    let tree: renderer.ReactTestRenderer | undefined;
    await act(async () => {
      tree = renderer.create(<Probe />);
    });

    const flushEnMount = offlineQueue.flush.mock.calls.length; // flush del mount
    const listener = netInfoListener();

    // Se cae la red → no sync
    await act(async () => {
      listener({ isConnected: false, isInternetReachable: false });
    });
    expect(offlineQueue.flush.mock.calls.length).toBe(flushEnMount);

    // Vuelve la red → sync automático
    await act(async () => {
      listener({ isConnected: true, isInternetReachable: true });
    });
    expect(offlineQueue.flush.mock.calls.length).toBe(flushEnMount + 1);

    await act(async () => {
      tree?.unmount();
    });
  });

  it('no dispara sync si ya estaba online (evento repetido)', async () => {
    let tree: renderer.ReactTestRenderer | undefined;
    await act(async () => {
      tree = renderer.create(<Probe />);
    });

    const flushEnMount = offlineQueue.flush.mock.calls.length;
    const listener = netInfoListener();

    await act(async () => {
      listener({ isConnected: true, isInternetReachable: true });
    });
    await act(async () => {
      listener({ isConnected: true, isInternetReachable: true });
    });
    expect(offlineQueue.flush.mock.calls.length).toBe(flushEnMount);

    await act(async () => {
      tree?.unmount();
    });
  });
});
