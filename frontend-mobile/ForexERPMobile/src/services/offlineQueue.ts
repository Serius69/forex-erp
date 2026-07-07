/**
 * offlineQueue — AsyncStorage-backed queue for transactions that fail due to
 * loss of connectivity. Items are flushed automatically on next successful sync.
 *
 * Data layout  : JSON array stored at QUEUE_KEY.
 * Retry policy : items with ≥ MAX_ATTEMPTS are dropped as unrecoverable;
 *                network errors stop the flush and leave remaining items queued;
 *                server errors (4xx/5xx) are removed immediately (permanent fail).
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { NewTransactionPayload } from '../types';

const QUEUE_KEY    = '@kapitalya/offline_tx_queue';
const MAX_ATTEMPTS = 3;

export interface QueuedTransaction {
  id:         string;
  payload:    NewTransactionPayload;
  pin:        string;
  created_at: string;
  attempts:   number;
}

export interface FlushResult {
  ok:     number;
  failed: number;
}

// ── Network error detection ───────────────────────────────────────────────────

export function isNetworkError(err: unknown): boolean {
  const msg = String((err as any)?.message ?? '').toLowerCase();
  return (
    msg.includes('network request failed') ||
    msg.includes('failed to fetch') ||
    msg.includes('network error') ||
    msg.includes('econnrefused') ||
    msg.includes('etimedout') ||
    msg.includes('timeout') ||
    msg.includes('timed out') ||
    msg.includes('socket hang up')
  );
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function generateId(): string {
  return `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

async function readQueue(): Promise<QueuedTransaction[]> {
  try {
    const raw = await AsyncStorage.getItem(QUEUE_KEY);
    return raw ? (JSON.parse(raw) as QueuedTransaction[]) : [];
  } catch {
    return [];
  }
}

async function writeQueue(queue: QueuedTransaction[]): Promise<void> {
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
}

// ── Public API ────────────────────────────────────────────────────────────────

export const offlineQueue = {

  getAll: readQueue,

  async count(): Promise<number> {
    return (await readQueue()).length;
  },

  async enqueue(payload: NewTransactionPayload, pin: string): Promise<QueuedTransaction> {
    const item: QueuedTransaction = {
      id:         generateId(),
      payload,
      pin,
      created_at: new Date().toISOString(),
      attempts:   0,
    };
    const queue = await readQueue();
    queue.push(item);
    await writeQueue(queue);
    return item;
  },

  async remove(id: string): Promise<void> {
    const queue = (await readQueue()).filter(i => i.id !== id);
    await writeQueue(queue);
  },

  /**
   * Attempt to submit each queued transaction in FIFO order.
   *
   * - Success → removed from queue.
   * - Network error → attempts incremented, flush stops (still offline).
   * - Server error (4xx/5xx) → removed from queue (permanent failure).
   * - Exceeded MAX_ATTEMPTS → removed from queue.
   */
  async flush(
    submitFn: (payload: NewTransactionPayload, pin: string) => Promise<any>,
  ): Promise<FlushResult> {
    const snapshot = await readQueue();
    if (snapshot.length === 0) return { ok: 0, failed: 0 };

    let ok = 0, failed = 0;

    for (const item of snapshot) {
      if (item.attempts >= MAX_ATTEMPTS) {
        await offlineQueue.remove(item.id);
        failed++;
        continue;
      }

      try {
        await submitFn(item.payload, item.pin);
        await offlineQueue.remove(item.id);
        ok++;
      } catch (err) {
        if (isNetworkError(err)) {
          // Still offline — increment attempt and abort flush
          const current = await readQueue();
          const idx     = current.findIndex(i => i.id === item.id);
          if (idx >= 0) {
            current[idx].attempts += 1;
            await writeQueue(current);
          }
          break;
        } else {
          // Server rejected — discard (avoid re-sending invalid payloads)
          await offlineQueue.remove(item.id);
          failed++;
        }
      }
    }

    return { ok, failed };
  },
};
