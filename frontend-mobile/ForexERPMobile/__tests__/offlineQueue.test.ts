/**
 * Tests de offlineQueue: encolado, flush y política de reintentos.
 * AsyncStorage usa el mock oficial (ver jest.setup.js).
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { describe, it, expect, beforeEach, jest } from '@jest/globals';
import { offlineQueue, isNetworkError } from '../src/services/offlineQueue';
import { NewTransactionPayload } from '../src/types';

const payload = (n: number): NewTransactionPayload => ({
  transaction_type: 'BUY',
  currency_from:    'USD',
  currency_to:      'BOB',
  amount_from:      100 + n,
  customer_name:    `Cliente ${n}`,
} as unknown as NewTransactionPayload);

type SubmitFn = (payload: NewTransactionPayload, pin: string) => Promise<any>;

const networkError: SubmitFn = () => Promise.reject(new Error('Network request failed'));
const serverError:  SubmitFn = () => Promise.reject(new Error('HTTP 400'));

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe('offlineQueue — enqueue / count / getAll', () => {
  it('encola items y los expone via count() y getAll()', async () => {
    expect(await offlineQueue.count()).toBe(0);

    const a = await offlineQueue.enqueue(payload(1), '1111');
    const b = await offlineQueue.enqueue(payload(2), '2222');

    expect(await offlineQueue.count()).toBe(2);
    const all = await offlineQueue.getAll();
    expect(all.map(i => i.id)).toEqual([a.id, b.id]);
    expect(a.id).not.toBe(b.id);
    expect(all[0].attempts).toBe(0);
    expect(all[0].pin).toBe('1111');
    expect(all[1].payload).toEqual(payload(2));
  });
});

describe('offlineQueue — flush', () => {
  it('flush exitoso elimina los items de la cola', async () => {
    await offlineQueue.enqueue(payload(1), '1111');
    await offlineQueue.enqueue(payload(2), '2222');

    const submitFn = jest.fn<SubmitFn>().mockResolvedValue({ ok: true });
    const result   = await offlineQueue.flush(submitFn);

    expect(result).toEqual({ ok: 2, failed: 0 });
    expect(submitFn).toHaveBeenCalledTimes(2);
    expect(submitFn).toHaveBeenCalledWith(payload(1), '1111');
    expect(await offlineQueue.count()).toBe(0);
  });

  it('error de red incrementa attempts y aborta el flush', async () => {
    await offlineQueue.enqueue(payload(1), '1111');
    await offlineQueue.enqueue(payload(2), '2222');

    const submitFn = jest.fn(networkError);
    const result   = await offlineQueue.flush(submitFn);

    expect(result).toEqual({ ok: 0, failed: 0 });
    expect(submitFn).toHaveBeenCalledTimes(1);   // abortó tras el primer item

    const all = await offlineQueue.getAll();
    expect(all).toHaveLength(2);                 // nada se descartó
    expect(all[0].attempts).toBe(1);
    expect(all[1].attempts).toBe(0);
  });

  it('el timeout de api.ts se clasifica como error de red', () => {
    expect(isNetworkError(new Error('Network request timed out'))).toBe(true);
    expect(isNetworkError(new Error('HTTP 500'))).toBe(false);
  });

  it('error de servidor descarta el item y continúa con el resto', async () => {
    await offlineQueue.enqueue(payload(1), '1111');
    await offlineQueue.enqueue(payload(2), '2222');

    const submitFn = jest.fn<SubmitFn>()
      .mockImplementationOnce(serverError)
      .mockResolvedValueOnce({ ok: true });
    const result = await offlineQueue.flush(submitFn);

    expect(result).toEqual({ ok: 1, failed: 1 });
    expect(await offlineQueue.count()).toBe(0);  // rechazado descartado, ok removido
  });

  it('items con MAX_ATTEMPTS agotados se descartan sin reintentar', async () => {
    await offlineQueue.enqueue(payload(1), '1111');

    // 3 flushes con error de red → attempts llega a MAX_ATTEMPTS (3)
    for (let i = 1; i <= 3; i++) {
      await offlineQueue.flush(jest.fn(networkError));
      const [item] = await offlineQueue.getAll();
      expect(item.attempts).toBe(i);
    }

    // 4.º flush: se descarta sin llamar a submitFn
    const submitFn = jest.fn(networkError);
    const result   = await offlineQueue.flush(submitFn);

    expect(result).toEqual({ ok: 0, failed: 1 });
    expect(submitFn).not.toHaveBeenCalled();
    expect(await offlineQueue.count()).toBe(0);
  });
});
