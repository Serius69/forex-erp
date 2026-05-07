// Tipos de error tipados para toda la aplicación

export type ErrorCode =
  | 'NETWORK_ERROR'
  | 'TIMEOUT_ERROR'
  | 'AUTH_ERROR'
  | 'FORBIDDEN_ERROR'
  | 'NOT_FOUND_ERROR'
  | 'VALIDATION_ERROR'
  | 'SERVER_ERROR'
  | 'RATE_LIMIT_ERROR'
  | 'MAINTENANCE_ERROR'
  | 'UNKNOWN_ERROR';

export interface AppError {
  code:       ErrorCode;
  message:    string;
  status?:    number;
  details?:   Record<string, string>;
  retryAfter?: number;
  requestId?:  string;
  errorId:    string;
}

export function makeErrorId(module = 'app'): string {
  const ts = Date.now().toString(36).toUpperCase();
  const rnd = Math.random().toString(36).slice(2, 6).toUpperCase();
  return `${module.toUpperCase().slice(0, 4)}-${ts}-${rnd}`;
}

export function isAppError(e: unknown): e is AppError {
  return typeof e === 'object' && e !== null && 'code' in e && 'errorId' in e;
}

export function isNetworkError(e: AppError): boolean {
  return e.code === 'NETWORK_ERROR' || e.code === 'TIMEOUT_ERROR';
}

export function isAuthError(e: AppError): boolean {
  return e.code === 'AUTH_ERROR' || e.code === 'FORBIDDEN_ERROR';
}
