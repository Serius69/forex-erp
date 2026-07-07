/**
 * Tests de src/services/api.ts con fetch global mockeado:
 *   • 401 → refresh → retry (una sola vez)
 *   • refresh single-flight: N requests concurrentes → 1 POST /auth/refresh/
 *   • timeout: aborta y lanza 'Network request timed out' (reconocible
 *     por offlineQueue.isNetworkError)
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { describe, it, expect, beforeEach, afterEach, jest } from '@jest/globals';
import { authApi } from '../src/services/api';
import { isNetworkError } from '../src/services/offlineQueue';

type FetchFn = (url: string, opts?: RequestInit) => Promise<any>;

const okJson = (data: any) => ({
  ok:     true,
  status: 200,
  json:   async () => data,
});

const unauthorized = () => ({
  ok:     false,
  status: 401,
  json:   async () => ({ detail: 'Token inválido' }),
});

let fetchMock = jest.fn<FetchFn>();

beforeEach(async () => {
  await AsyncStorage.clear();
  await AsyncStorage.setItem('access_token',  'viejo');
  await AsyncStorage.setItem('refresh_token', 'refresh-1');
  fetchMock = jest.fn<FetchFn>();
  (global as any).fetch = fetchMock;
});

afterEach(() => {
  jest.useRealTimers();
});

describe('api — 401 → refresh → retry', () => {
  it('ante un 401 refresca el token y reintenta una sola vez', async () => {
    const user = { id: 1, username: 'cajero1' };

    fetchMock.mockImplementation((url: string, opts: RequestInit = {}) => {
      if (url.includes('/auth/refresh/')) {
        return Promise.resolve(okJson({ access: 'nuevo' }));
      }
      const auth = (opts.headers as Record<string, string>)?.Authorization;
      return Promise.resolve(auth === 'Bearer nuevo' ? okJson(user) : unauthorized());
    });

    const me = await authApi.getMe();

    expect(me).toEqual(user);
    // 3 llamadas: request original (401) + refresh + retry
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(await AsyncStorage.getItem('access_token')).toBe('nuevo');
  });

  it('si el refresh falla lanza UNAUTHORIZED sin reintentar', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes('/auth/refresh/')) {
        return Promise.resolve({ ok: false, status: 401, json: async () => ({}) });
      }
      return Promise.resolve(unauthorized());
    });

    await expect(authApi.getMe()).rejects.toThrow('UNAUTHORIZED');
    expect(fetchMock).toHaveBeenCalledTimes(2);   // request + refresh, sin retry
  });
});

describe('api — refresh single-flight', () => {
  it('dos requests concurrentes con 401 comparten un solo POST /auth/refresh/', async () => {
    const user = { id: 1, username: 'cajero1' };
    let refreshCalls = 0;

    fetchMock.mockImplementation((url: string, opts: RequestInit = {}) => {
      if (url.includes('/auth/refresh/')) {
        refreshCalls += 1;
        return Promise.resolve(okJson({ access: 'nuevo' }));
      }
      const auth = (opts.headers as Record<string, string>)?.Authorization;
      return Promise.resolve(auth === 'Bearer nuevo' ? okJson(user) : unauthorized());
    });

    const [a, b] = await Promise.all([authApi.getMe(), authApi.getMe()]);

    expect(a).toEqual(user);
    expect(b).toEqual(user);
    expect(refreshCalls).toBe(1);   // single-flight: un solo refresh compartido
  });
});

describe('api — timeout', () => {
  it('aborta tras REQUEST_TIMEOUT_MS con un error de red reconocible', async () => {
    jest.useFakeTimers();

    // fetch que nunca responde; solo rechaza cuando la señal se aborta
    fetchMock.mockImplementation((_url: string, opts: RequestInit = {}) =>
      new Promise((_resolve, reject) => {
        opts.signal?.addEventListener('abort', () => reject(new Error('Aborted')));
      }),
    );

    const pending = authApi.getMe();
    const guarded = pending.catch((err: Error) => err);   // evitar unhandled rejection

    await jest.advanceTimersByTimeAsync(15000 + 1);

    const err = (await guarded) as Error;
    expect(err.message).toBe('Network request timed out');
    expect(isNetworkError(err)).toBe(true);
  });
});
