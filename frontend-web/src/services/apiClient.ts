/**
 * apiClient — wrapper sobre el axios instance existente con:
 *   - Clasificación tipada de errores (NetworkError, TimeoutError, AuthError, etc.)
 *   - Retry con backoff exponencial según tipo de error
 *   - Manejo de 429 con Retry-After
 *   - Nunca propaga errores sin clasificar
 */
import axios, { AxiosError, AxiosRequestConfig, AxiosResponse } from 'axios';
import { api } from './api';
import { AppError, ErrorCode, makeErrorId } from './errorTypes';
import { logErrorSync } from './errorLogger';

// ── Clasificación de errores ───────────────────────────────────────────────────

export function classifyAxiosError(error: AxiosError): AppError {
  const errorId  = makeErrorId('API');
  const status   = error.response?.status;
  const data     = error.response?.data as any;
  const requestId = data?.request_id;

  // Sin respuesta → red o timeout
  if (!error.response) {
    if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
      return { code: 'TIMEOUT_ERROR', message: 'La solicitud tardó demasiado. Verifica tu conexión.', errorId, requestId };
    }
    return { code: 'NETWORK_ERROR', message: 'Sin conexión al servidor. Verifica tu red.', errorId, requestId };
  }

  if (status === 401) return { code: 'AUTH_ERROR',      message: data?.error ?? 'Sesión expirada. Inicia sesión nuevamente.', errorId, requestId, status };
  if (status === 403) return { code: 'FORBIDDEN_ERROR', message: data?.error ?? 'No tienes permiso para esta acción.',         errorId, requestId, status };
  if (status === 404) return { code: 'NOT_FOUND_ERROR', message: data?.error ?? 'Recurso no encontrado.',                      errorId, requestId, status };
  if (status === 422) return { code: 'VALIDATION_ERROR', message: data?.error ?? 'Datos inválidos.', details: data?.details, errorId, requestId, status };
  if (status === 429) return { code: 'RATE_LIMIT_ERROR', message: data?.error ?? 'Demasiadas solicitudes. Intenta más tarde.', retryAfter: data?.retry_after ?? 60, errorId, requestId, status };
  if (status === 503) return { code: 'MAINTENANCE_ERROR', message: data?.error ?? 'Sistema en mantenimiento.', errorId, requestId, status };
  if (status && status >= 500) return { code: 'SERVER_ERROR', message: data?.error ?? 'Error en el servidor. El equipo fue notificado.', errorId, requestId, status };

  return { code: 'UNKNOWN_ERROR', message: data?.error ?? error.message ?? 'Error inesperado.', errorId, requestId, status };
}

// ── Retry policy ──────────────────────────────────────────────────────────────

function shouldRetry(error: AppError, attempt: number): boolean {
  if (attempt >= 3) return false;
  return error.code === 'NETWORK_ERROR'
      || error.code === 'TIMEOUT_ERROR'
      || error.code === 'SERVER_ERROR';
}

function retryDelay(attempt: number, error: AppError): number {
  if (error.code === 'RATE_LIMIT_ERROR') return (error.retryAfter ?? 60) * 1000;
  // Backoff exponencial: 1s, 2s, 4s
  return Math.min(1000 * Math.pow(2, attempt), 8000);
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

// ── Cliente con retry ─────────────────────────────────────────────────────────

async function requestWithRetry<T>(config: AxiosRequestConfig): Promise<AxiosResponse<T>> {
  let attempt = 0;
  while (true) {
    try {
      return await api.request<T>(config);
    } catch (err) {
      if (!axios.isAxiosError(err)) {
        const appErr: AppError = { code: 'UNKNOWN_ERROR', message: String(err), errorId: makeErrorId('API') };
        throw appErr;
      }
      const appError = classifyAxiosError(err as AxiosError);

      // Auth errors are already handled by api.ts interceptor (auto-refresh → redirect)
      // Re-throw immediately so callers can show appropriate UI
      if (appError.code === 'AUTH_ERROR' || appError.code === 'FORBIDDEN_ERROR') {
        throw appError;
      }

      if (shouldRetry(appError, attempt)) {
        const delay = retryDelay(attempt, appError);
        attempt++;
        await sleep(delay);
        continue;
      }

      // Log to backend (non-blocking)
      if (appError.code === 'SERVER_ERROR' || appError.code === 'UNKNOWN_ERROR') {
        logErrorSync(err as Error, { code: appError.code, status: appError.status, url: config.url });
      }

      throw appError;
    }
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

export const apiClient = {
  get<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    return requestWithRetry<T>({ ...config, method: 'get', url });
  },
  post<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    return requestWithRetry<T>({ ...config, method: 'post', url, data });
  },
  put<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    return requestWithRetry<T>({ ...config, method: 'put', url, data });
  },
  patch<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    return requestWithRetry<T>({ ...config, method: 'patch', url, data });
  },
  delete<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    return requestWithRetry<T>({ ...config, method: 'delete', url });
  },
};

export default apiClient;
